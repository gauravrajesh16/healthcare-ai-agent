import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from agent.__main__ import Handler, RepTokenAuth
from agent.session_store import SessionStore

class FakeAgent:
    def __init__(self,tenant,member_id,state,conversation_id):
        self.tenant,self.member_id,self.state=tenant,member_id,state
        self.trace=[]
    def answer(self,message):
        if message=="draft":
            self.state["draft"]="private grievance text"
            return f"draft for {self.tenant}/{self.member_id}"
        if message=="confirm" and self.state.get("draft"):
            self.state.pop("draft")
            return "filed exactly once"
        return "no pending draft"

class AuthenticatedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.key=Fernet.generate_key().decode()
        self.db=Path(self.temp.name)/"sessions.sqlite3"
        Handler.store=SessionStore(self.db,self.key)
        Handler.auth=RepTokenAuth({"rep-token":{"sub":"rep-1","tenant":"plan_a","members":["M123"]}})
        self.agent_patch=patch("agent.__main__.MemberAgent",FakeAgent); self.agent_patch.start()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.url=f"http://127.0.0.1:{self.server.server_port}/chat"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.agent_patch.stop(); self.temp.cleanup()

    def request(self,payload,token="rep-token"):
        headers={"Content-Type":"application/json"}
        if token: headers["Authorization"]="Bearer "+token
        req=urllib.request.Request(self.url,data=json.dumps(payload).encode(),headers=headers,method="POST")
        try:
            with urllib.request.urlopen(req) as response: return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc: return exc.code,json.loads(exc.read())

    def test_http_rejects_missing_auth_and_tenant_spoof(self):
        body={"conversation_id":"c1","member_id":"M123","message":"draft"}
        self.assertEqual(self.request(body,token=None)[0],401)
        self.assertEqual(self.request({**body,"tenant":"plan_b"})[0],403)

    def test_member_scope_is_enforced(self):
        status,_=self.request({"member_id":"M999","message":"draft"})
        self.assertEqual(status,403)

    def test_encrypted_session_survives_server_store_recreation(self):
        body={"conversation_id":"persist-me","member_id":"M123","message":"draft"}
        status,first=self.request(body)
        self.assertEqual(status,200); self.assertIn("plan_a/M123",first["answer"])
        db=sqlite3.connect(self.db)
        try: encrypted=db.execute("SELECT encrypted_payload FROM conversations WHERE conversation_id='persist-me'").fetchone()[0]
        finally: db.close()
        self.assertNotIn(b"private grievance text",encrypted)
        # Reopen from the same durable DB and key, representing a service restart.
        Handler.store=SessionStore(self.db,self.key)
        status,second=self.request({**body,"message":"confirm"})
        self.assertEqual(status,200); self.assertEqual(second["answer"],"filed exactly once")

    def test_conversation_is_bound_to_member(self):
        self.request({"conversation_id":"bound","member_id":"M123","message":"draft"})
        Handler.auth=RepTokenAuth({"rep-token":{"sub":"rep-1","tenant":"plan_a","members":["M123","M456"]}})
        status,_=self.request({"conversation_id":"bound","member_id":"M456","message":"confirm"})
        self.assertEqual(status,409)

if __name__=="__main__": unittest.main()
