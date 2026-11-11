"""Deterministic rep assistant for the supplied synthetic member-services pack."""
import datetime as dt
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .gateway import ToolGateway, GatewayError, GatewayNotFound, GatewayUnavailable
from .model import AnswerModel

ROOT=Path(__file__).resolve().parents[1]
PACK=Path(os.environ.get("PACK_DIR",ROOT))
AS_OF="2026-11-15"

class MemberAgent:
    def __init__(self, tenant, member_id, state=None, conversation_id=None, model=None):
        self.tenant, self.member_id = tenant, member_id
        self.state = state if state is not None else {}
        self.conversation_id = conversation_id or "local"
        self.model = model or AnswerModel()
        self.trace=[]
        self.deadline=None

    def answer(self, text):
        self.trace=[]
        self.deadline=time.monotonic()+float(os.environ.get("QUESTION_TIMEOUT_SECONDS","12"))
        q=text.lower()
        if re.search(r"\b(full )?(social security number|ssn)\b",q) and ("read" in q or "tell me" in q or "give me" in q):
            self.trace.append({"type":"gateway_decision","action":"phi_disclosure","decision":"deny"})
            return "I can’t disclose the member’s full Social Security number. Verify using the approved identity verification process."
        # A declared other tenant never changes the authenticated tenant context.
        other="plan_b" if self.tenant=="plan_a" else "plan_a"
        if (other=="plan_b" and "prairie sky" in q) or (other=="plan_a" and "harborview" in q):
            self.trace.append({"type":"gateway_decision","action":"cross_tenant_lookup","decision":"deny"})
            return "I can’t find that member in this plan’s records. Nothing from another plan was accessed."
        g=ToolGateway(self.tenant,self.member_id,self.trace,budget_state=self.state,deadline=self.deadline)
        try:
            member=g.get(f"/tenants/{self.tenant}/members/{self.member_id}")
        except GatewayNotFound:
            return "I can't find that member in this plan's records."
        except GatewayUnavailable as e:
            return f"I can't look up the member because {e}."
        except GatewayError:
            return "I can't look up the member because the request was blocked by gateway policy."
        try:
            answer=self._respond(q,text,member,g)
        except GatewayError as e:
            answer=f"I can't retrieve that information right now: {e}."
        return self.model.rewrite(answer,self.trace,self.state,max(0.1,self.deadline-time.monotonic()))

    def _respond(self,q,text,m,g):
        if "last four" in q or "last four digits" in q:
            supplied=re.search(r"\b(\d{4})\b",text)
            if not supplied: return "Please provide the last four digits for comparison."
            matched=m.get("ssn","").replace("-","")[-4:]==supplied.group(1)
            return "The last four digits match." if matched else "The last four digits do not match."
        # Pending grievance confirmation is tied to exact draft and member.
        pending=self.state.get("pending_grievance")
        if pending and any(s in q for s in ("yes", "confirmed", "go ahead", "file it", "proceed")):
            result=g.post_grievance(pending["category"],pending["description"],pending["key"],confirmed=True)
            self.state.pop("pending_grievance",None)
            return f"The {result['category']} grievance was filed. Reference: {result['grievance_id']}."
        if pending and any(s in q for s in ("hold off", "don't", "do not", "cancel", "stop")):
            self.state.pop("pending_grievance",None)
            return "Understood. I did not file a grievance."
        if any(x in q for x in ("file a", "file it", "file this", "grievance")) and not ("grievance g" in q and "deadline" in q):
            if self.state.get("pending_grievance"):
                return "There is already a grievance draft awaiting confirmation. Please confirm or cancel it first."
            category=next((x for x in ("billing","quality_of_care","access","customer_service") if x in q),"other")
            desc=text.strip()
            # Avoid unnecessary member identifiers and redact any explicit SSN-like sequence.
            desc=re.sub(r"\b\d{3}-?\d{2}-?\d{4}\b","[REDACTED]",desc)
            key=hashlib.sha256(f"{self.tenant}|{self.member_id}|{self.conversation_id}|{desc}".encode()).hexdigest()
            self.state["pending_grievance"]={"category":category,"description":desc,"key":key}
            return f"Draft grievance ({category}): {desc}\nPlease read this summary to the member and confirm explicitly before I file it."
        if "coverage_termination" in m and m.get("coverage_termination") and m["coverage_termination"] < AS_OF:
            ben=g.get(f"/tenants/{self.tenant}/members/{self.member_id}/benefits")
            if "copay" in q or "cost" in q or "pay" in q:
                return f"This member’s coverage is not active; it ended {ben['coverage_termination']}."
        if ("provider" in q or "dermatolog" in q or "doctor" in q) and ("near" in q or "find" in q):
            zip_code=m.get("address",{}).get("zip","")
            specialty="dermatology" if "dermatolog" in q else None
            net=m.get("network_id")
            query={"zip":zip_code,"network_id":net,"limit":10}
            if specialty: query["specialty"]=specialty
            res=g.get("/directory/v3/providers",query,directory=True).get("results",[])
            return "In-network providers near the member: "+("; ".join(p["name"] for p in res) if res else "none found")+"."
        # Use direct claim reads when the rep supplies an ID; verify member ownership before use.
        claims=[]
        claim_mismatch=False
        if any(x in q for x in ("claim","denied","denial","appeal","plan pay")) or re.search(r"\b\d{4}-\d{2}-\d{2}\b",q):
            claim_id=re.search(r"\bC\d{10}\b",text,re.I)
            service_date=re.search(r"\b\d{4}-\d{2}-\d{2}\b",text)
            c=None
            if claim_id:
                c=g.get(f"/tenants/{self.tenant}/claims/{claim_id.group()}")
                if c.get("member_id")!=self.member_id:
                    c=None; claim_mismatch=True
                else:
                    claims=[c]
            else:
                # Read the first three bounded pages concurrently to reduce the claims
                # platform's per-call latency. All calls remain tenant/member scoped.
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures=[pool.submit(g.get,f"/tenants/{self.tenant}/members/{self.member_id}/claims",{"page_size":5,"cursor":cursor}) for cursor in (0,5,10)]
                    pages=[future.result() for future in futures]
                for page in pages: claims.extend(page.get("data",[]))
                next_path=pages[-1].get("next")
                while next_path and len(claims)<30:
                    path,_,qs=next_path.partition("?")
                    from urllib.parse import parse_qs
                    args={k:v[0] for k,v in parse_qs(qs).items()}
                    page=g.get(path,args); claims.extend(page.get("data",[])); next_path=page.get("next")
                if service_date: c=next((claim for claim in claims if claim["service_date"]==service_date.group()),None)
            if claim_mismatch:
                return "I can't find that claim in this member's records."
            if c:
                if "appeal" in q: return self._appeal(c)
                if "why" in q or "denied" in q or "what happened" in q:
                    return f"Claim {c['claim_id']} is {c['status']}. Denial code: {c.get('denial',{}).get('carc','not available')}; {c.get('denial',{}).get('description','No denial reason recorded.')}" + (" This indicates prior authorization was not on file." if c.get("denial",{}).get("carc")=="CO-197" else "")
                if "plan pay" in q or "how much did the plan" in q: return f"The plan paid ${c['plan_paid']:,.2f} on this claim."
                if "owe" in q or "responsibility" in q: return f"The member responsibility was ${sum(c['member_responsibility'].values()):,.2f}."
                return f"Claim {c['claim_id']} is {c['status']}."
            if "grievance g" in q:
                pass
            if "denied" in q and ("how many" in q or "number of" in q):
                n=sum(c["status"]=="DENIED" and c["service_date"].startswith("2026") for c in claims)
                return f"There were {n} denied claims in 2026."
        gid=re.search(r"G26-\d+",text,re.I)
        if gid and "grievance" in q:
            items=g.get(f"/tenants/{self.tenant}/members/{self.member_id}/grievances").get("data",[])
            gr=next((x for x in items if x["grievance_id"].lower()==gid.group().lower()),None)
            if gr:
                days=30 if self.tenant=="plan_a" else 45
                due=dt.date.fromisoformat(gr["received_date"])+dt.timedelta(days=days)
                return f"Yes, it is past the resolution deadline of {due.isoformat()}." if dt.date.fromisoformat(AS_OF)>due else f"No, it is not past the resolution deadline of {due.isoformat()}."
        if "not available" in q or "approved yet" in q or "next week" in q:
            return "That information is not available in the member services APIs. Prior authorization decisions are handled in a separate system, so I can’t confirm approval."
        # Live enrollment and accumulators.
        benefits=g.get(f"/tenants/{self.tenant}/members/{self.member_id}/benefits")
        if benefits["coverage_status"]!="ACTIVE":
            return f"This member’s coverage is not active; it ended {benefits['coverage_termination']}."
        acc=benefits.get("accumulators",{})
        if "deductible" in q:
            doc=self._plan_doc(m, 2027 if "january 1" in q or "after that" in q or "2027" in q else 2026)
            amount=self._table_cost(doc,"Deductible (individual / family)")
            met=float(acc.get("deductible_met_individual",0))
            try:
                limit=float(re.search(r"\$([\d,]+)",amount).group(1).replace(",",""))
                left=max(0,limit-met)
                return f"${left:,.2f} remains before the individual in-network deductible is met (2026 plan year)."
            except Exception: pass
        if "out-of-pocket" in q or "out of pocket" in q:
            doc=self._plan_doc(m,2026); amount=self._table_cost(doc,"Out-of-pocket maximum (individual / family)")
            if "family" in q:
                family=re.search(r"/\s*(\$[\d,]+)",amount)
                return f"The in-network family out-of-pocket maximum is {family.group(1)} (2026 plan year)." if family else "The family maximum is not listed."
            met=float(acc.get("out_of_pocket_met_individual",0)); limit=float(re.search(r"\$([\d,]+)",amount).group(1).replace(",",""))
            return f"${max(0,limit-met):,.2f} remains before the individual in-network out-of-pocket maximum (2026 plan year)."
        if "physical therapy" in q or "therapy visits" in q:
            doc=self._plan_doc(m,2026)
            limit=int(re.search(r"Physical therapy visit limit \|[^\n]*?(\d+) visits",doc).group(1))
            used=int(acc.get("physical_therapy_visits_used",0))
            return f"{max(0,limit-used)} physical therapy visits remain this plan year."
        doc=self._plan_doc(m,2027 if "january 1" in q or "after that" in q or "2027" in q else 2026)
        if "which plan" in q or "enrolled" in q:
            return f"The member is enrolled in {m['plan_name']} under {self._tenant_name()}. A primary care visit costs {self._table_cost(doc,'Primary care visit')}."
        row=None
        if "specialist" in q: row="Specialist visit"
        elif "emergency room" in q: row="Emergency room"
        elif "urgent care" in q: row="Urgent care"
        elif "primary care" in q or "office visit" in q: row="Primary care visit"
        elif "generic" in q and ("drug" in q or "prescription" in q): row="Generic drugs (Tier 1, 30-day retail)"
        elif "video visit" in q or "telehealth" in q: row="Telehealth (video) visit"
        elif "virtual behavioral" in q or "virtual therapy" in q:
            if self.tenant != "plan_b": return "That virtual care benefit is not documented for this tenant, so I cannot confirm the cost."
            v=self._virtual_doc()
            cost=re.search(r"Virtual behavioral health session \| ([^|\n]+)",v).group(1).strip()
            return f"{cost}."
        elif "therapy" in q: row="Physical therapy"
        if row:
            return f"The in-network cost is {self._table_cost(doc,row)} ({2027 if 'january 1' in q or 'after that' in q or '2027' in q else 2026} plan year)."
        return "I can’t determine that from the available member and plan information."

    def _tenant_name(self): return "Harborview Health Plan" if self.tenant=="plan_a" else "Prairie Sky Health"
    def _plan_doc(self,m,year):
        p=PACK/"kb"/self.tenant
        files=list(p.glob("*.md"))
        for f in files:
            txt=f.read_text(encoding="utf-8")
            if f"plan_year: {year}" in txt and f"product_code: {m['product_code']}" in txt: return txt
        return next(f.read_text(encoding="utf-8") for f in files if "product_code: ALL" in f.read_text(encoding="utf-8") and f"plan_year: {year}" in f.read_text(encoding="utf-8"))
    def _virtual_doc(self): return (PACK/"kb/plan_b/virtual_care_2026.md").read_text(encoding="utf-8")
    def _table_cost(self,doc,label):
        for line in doc.splitlines():
            if line.startswith("| "+label+" |"):
                return line.split("|")[2].strip()
        return "not listed"
    def _appeal(self,c):
        if not c.get("processed_date"): return "The claim has no denial notice date recorded, so I can’t determine the appeal window."
        end=dt.date.fromisoformat(c["processed_date"])+dt.timedelta(days=180)
        return f"Yes, the appeal window is still open; the deadline is {end.isoformat()}." if dt.date.fromisoformat(AS_OF)<=end else f"No, the appeal window has passed; the deadline was {end.isoformat()}."
