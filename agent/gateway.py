"""Configuration and policy-enforcing API gateway for the assessment slice."""
import json
import os
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class GatewayError(Exception):
    pass

class GatewayNotFound(GatewayError):
    pass

class GatewayUnavailable(GatewayError):
    pass

class ToolGateway:
    """Every service call is tenant-bound, budgeted, minimized, and traced."""
    def __init__(self, tenant, member_id, trace, max_steps=24, deadline_s=12, budget_state=None, deadline=None):
        if tenant not in {"plan_a", "plan_b"}:
            raise GatewayError("Unknown tenant")
        self.tenant, self.member_id, self.trace = tenant, member_id, trace
        self.budget_state = budget_state if budget_state is not None else {}
        self.steps, self.max_steps = int(self.budget_state.get("_tool_steps",0)), max_steps
        self.deadline = deadline if deadline is not None else time.monotonic() + deadline_s
        self._step_lock = threading.Lock()
        pack = Path(os.environ.get("PACK_DIR", ROOT))
        data = json.loads((pack / "mock_services/data/tenants.json").read_text(encoding="utf-8"))
        self.token = data["tenants"][tenant]["api_token"]
        self.base = os.environ.get("MEMBER_API_URL", "http://127.0.0.1:8090").rstrip("/")
        self.directory_key = data["directory"]["api_key"]

    def _consume_step(self):
        with self._step_lock:
            if self.steps >= self.max_steps or time.monotonic() > self.deadline:
                raise GatewayError("Conversation tool or latency budget exhausted")
            self.steps += 1
            self.budget_state["_tool_steps"] = self.steps

    def get(self, path, query=None, directory=False):
        if self.tenant not in path and not directory:
            raise GatewayError("Tenant boundary violation")
        self._consume_step()
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": "Bearer " + self.token}
        if directory:
            # Only geography, specialty and network are permitted. Never pass member identifiers.
            if set(query or {}) - {"specialty", "zip", "network_id", "limit"}:
                raise GatewayError("Directory data minimization policy violation")
            headers = {"X-Api-Key": self.directory_key}
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, headers=headers)
            try:
                response = urllib.request.urlopen(req, timeout=max(0.2, self.deadline-time.monotonic()))
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise
                retry = min(float(exc.headers.get("Retry-After", "1")), 2.0)
                if time.monotonic() + retry >= self.deadline:
                    raise GatewayError("The service rate limit exceeded the conversation deadline") from exc
                time.sleep(retry)
                self._consume_step()
                response = urllib.request.urlopen(req, timeout=max(0.2, self.deadline-time.monotonic()))
            with response as res:
                value = json.loads(res.read().decode("utf-8"))
        except GatewayError:
            raise
        except urllib.error.HTTPError as exc:
            self.trace.append({"type":"tool_error", "tool":self._tool_name(path), "error":"http_"+str(exc.code)})
            if exc.code == 404:
                raise GatewayNotFound("The requested member or record was not found") from exc
            if exc.code == 401:
                raise GatewayUnavailable("The mock API rejected its configured credentials") from exc
            raise GatewayUnavailable(f"The member service returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self.trace.append({"type":"tool_error", "tool":self._tool_name(path), "error":type(exc).__name__})
            raise GatewayUnavailable("Cannot reach the member service; check that the mock server is running and MEMBER_API_URL is correct") from exc
        self.trace.append({"type":"tool", "tool":self._tool_name(path), "duration_ms":round((time.monotonic()-start)*1000), "decision":"allow"})
        return value

    def _tool_name(self, path):
        if "/benefits" in path: return "get_benefits"
        if "/claims" in path: return "list_claims"
        if "/grievances" in path: return "list_grievances"
        if "/members/" in path: return "get_member"
        if "/providers" in path: return "search_providers"
        return "service_read"

    def post_grievance(self, category, description, idempotency_key, confirmed):
        if confirmed is not True:
            self.trace.append({"type":"gateway_decision", "action":"grievance_write", "decision":"deny_unconfirmed"})
            raise GatewayError("Explicit confirmation is required")
        if self.tenant not in {"plan_a", "plan_b"} or len(description) > 2000:
            raise GatewayError("Invalid grievance request")
        import hashlib
        self._consume_step()
        body = json.dumps({"category":category,"description":description,"expedite_requested":False}, separators=(",",":" )).encode()
        req = urllib.request.Request(self.base+f"/tenants/{self.tenant}/members/{self.member_id}/grievances", data=body, method="POST", headers={"Authorization":"Bearer "+self.token,"Content-Type":"application/json","Idempotency-Key":idempotency_key})
        try:
            with urllib.request.urlopen(req, timeout=max(0.2,self.deadline-time.monotonic())) as res:
                result=json.loads(res.read().decode())
        except urllib.error.HTTPError as exc:
            # Ambiguous 503 is not retried blindly. Reconcile by reading grievances first.
            if exc.code == 503:
                self.trace.append({"type":"tool_error","tool":"create_grievance","error":"ambiguous_ack"})
                existing=self.get(f"/tenants/{self.tenant}/members/{self.member_id}/grievances")
                matches=[g for g in existing.get("data",[]) if g.get("category")==category and g.get("description")==description]
                if matches: result=matches[-1]
                else: raise GatewayError("Write acknowledgement is uncertain; no blind retry was made") from exc
            else:
                raise GatewayError(f"Grievance service rejected the request ({exc.code})") from exc
        self.trace.append({"type":"tool","tool":"create_grievance","decision":"allow_confirmed","idempotency_key_hash":hashlib.sha256(idempotency_key.encode()).hexdigest()[:12]})
        return result
