"""Authenticated HTTP and local CLI entry points."""
import argparse
import hmac
import json
import os
import threading
from collections.abc import Mapping
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .app import MemberAgent
from .model import AnswerModel
from .session_store import SessionConflict, SessionStore

class RepTokenAuth:
    """Local opaque-token adapter; replace with OIDC/JWT validation in production."""
    def __init__(self, serialized=None):
        raw=serialized if serialized is not None else os.environ.get("REP_AUTH_TOKENS","")
        try: self.tokens=dict(raw) if isinstance(raw,Mapping) else (json.loads(raw) if raw else {})
        except ValueError as exc: raise RuntimeError("REP_AUTH_TOKENS must be a JSON object") from exc
        if not isinstance(self.tokens,dict) or not self.tokens:
            raise RuntimeError("Configure at least one tenant-scoped REP_AUTH_TOKENS credential")
        for claims in self.tokens.values():
            if claims.get("tenant") not in {"plan_a","plan_b"} or not claims.get("sub") or not isinstance(claims.get("members"),list):
                raise RuntimeError("Each rep token needs sub, tenant, and a members allowlist")

    def authenticate(self, header):
        scheme,_,candidate=(header or "").partition(" ")
        if scheme.lower()!="bearer" or not candidate: return None
        for token,claims in self.tokens.items():
            if hmac.compare_digest(token,candidate): return claims
        return None

class Handler(BaseHTTPRequestHandler):
    server_version="AssessmentAgent/1"
    store=None
    auth=None
    request_lock=threading.RLock()

    def _send(self,status,payload):
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path=="/health": return self._send(200,{"status":"ok"})
        return self._send(404,{"error":"not_found"})

    def do_POST(self):
        if self.path!="/chat": return self._send(404,{"error":"not_found"})
        claims=self.auth.authenticate(self.headers.get("Authorization"))
        if claims is None: return self._send(401,{"error":"unauthorized"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length<=0 or length>65536: return self._send(413,{"error":"invalid_request_size"})
            data=json.loads(self.rfile.read(length).decode("utf-8"))
            member_id=data.get("member_id")
            message=data.get("message")
            if not isinstance(member_id,str) or not isinstance(message,str) or not message.strip() or len(message)>8000:
                return self._send(400,{"error":"invalid_request"})
            if member_id not in claims["members"] and "*" not in claims["members"]:
                return self._send(403,{"error":"member_not_authorized"})
            if data.get("tenant") not in (None,claims["tenant"]):
                return self._send(403,{"error":"tenant_mismatch"})
            sid=data.get("conversation_id") or str(uuid.uuid4())
            if not isinstance(sid,str) or len(sid)>128: return self._send(400,{"error":"invalid_conversation_id"})
            with self.request_lock:
                stored=self.store.load(sid)
                context={"sub":claims["sub"],"tenant":claims["tenant"],"member_id":member_id}
                if stored and any(stored.get(k)!=v for k,v in context.items()):
                    raise SessionConflict("conversation context mismatch")
                state=stored.get("state",{}) if stored else {}
                agent=MemberAgent(claims["tenant"],member_id,state,sid)
                answer=agent.answer(message)
                self.store.save(sid,{**context,"state":state})
            return self._send(200,{"conversation_id":sid,"answer":answer,"trace":agent.trace})
        except SessionConflict:
            return self._send(409,{"error":"conversation_context_conflict"})
        except Exception:
            # Never return exception text that could contain paths, request data, or credentials.
            return self._send(500,{"error":"request_failed"})

    def log_message(self,fmt,*args): pass

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True)
    serve=sub.add_parser("serve"); serve.add_argument("--host",default="127.0.0.1"); serve.add_argument("--port",type=int,default=8080)
    chat=sub.add_parser("chat"); chat.add_argument("--tenant",required=True,choices=["plan_a","plan_b"]); chat.add_argument("--member",required=True); chat.add_argument("--show-trace",action="store_true")
    args=p.parse_args()
    if args.cmd=="serve":
        Handler.auth=RepTokenAuth()
        Handler.store=SessionStore()
        AnswerModel() # fail startup on invalid provider/PHI configuration
        print(f"Authenticated agent API listening on http://{args.host}:{args.port}")
        ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
    else:
        agent=MemberAgent(args.tenant,args.member)
        while True:
            try: text=input("rep> ")
            except EOFError: break
            if text.strip().lower() in {"exit","quit"}: break
            answer=agent.answer(text)
            print(answer)
            if args.show_trace:
                print(json.dumps(agent.trace,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
