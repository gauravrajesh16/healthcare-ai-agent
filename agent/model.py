"""Optional local Ollama, Ollama Cloud, or hosted OpenAI-compatible answer formatter; tool policy stays local."""
import json
import math
import os
import re
import urllib.request

class ModelConfigurationError(RuntimeError): pass

class AnswerModel:
    def __init__(self):
        self.provider=os.environ.get("MODEL_PROVIDER","rules").strip().lower()
        self.model=os.environ.get("MODEL_NAME","")
        default_url={"ollama":"http://127.0.0.1:11434","ollama_cloud":"https://ollama.com"}.get(self.provider,"https://api.openai.com/v1")
        self.base_url=os.environ.get("MODEL_BASE_URL",default_url).rstrip("/")
        self.api_key=os.environ.get("MODEL_API_KEY",os.environ.get("OLLAMA_API_KEY",""))
        self.allow_phi=os.environ.get("MODEL_ALLOW_PHI","false").lower()=="true"
        self.max_cost=float(os.environ.get("MODEL_MAX_COST_USD_PER_CONVERSATION","0.03"))
        self.input_rate=float(os.environ.get("MODEL_INPUT_USD_PER_1K","0"))
        self.output_rate=float(os.environ.get("MODEL_OUTPUT_USD_PER_1K","0"))
        self.max_output_tokens=int(os.environ.get("MODEL_MAX_OUTPUT_TOKENS","300"))
        self.request_timeout=float(os.environ.get("MODEL_TIMEOUT_SECONDS","8"))
        if self.provider not in {"rules","openai_compatible","ollama","ollama_cloud"}:
            raise ModelConfigurationError("MODEL_PROVIDER must be rules, openai_compatible, ollama, or ollama_cloud")
        if self.provider in {"openai_compatible","ollama","ollama_cloud"}:
            if not self.model:
                raise ModelConfigurationError("MODEL_NAME is required")
            if self.provider in {"openai_compatible","ollama_cloud"} and not self.api_key:
                raise ModelConfigurationError("MODEL_API_KEY or OLLAMA_API_KEY is required for a hosted provider")
            if not self.allow_phi:
                raise ModelConfigurationError("Set MODEL_ALLOW_PHI=true only after approving the model endpoint for this data")
            if self.provider in {"openai_compatible","ollama_cloud"} and (self.input_rate<=0 or self.output_rate<=0 or self.max_cost<=0):
                raise ModelConfigurationError("Configure positive hosted-model rates and conversation cost cap")
            if self.provider=="ollama" and self.max_cost<=0:
                raise ModelConfigurationError("MODEL_MAX_COST_USD_PER_CONVERSATION must be positive")

    def rewrite(self, answer, trace, state=None, timeout=8):
        if self.provider=="rules": return answer
        state=state if state is not None else {}
        max_output=self.max_output_tokens
        input_tokens=math.ceil((len(answer)+350)/3.5*1.15)
        reserve=0.0 if self.provider=="ollama" else (input_tokens*self.input_rate+max_output*self.output_rate)/1000
        spent=float(state.get("_model_cost_usd",0))
        if spent+reserve>self.max_cost:
            trace.append({"type":"model","provider":self.provider,"decision":"deny_cost_budget"})
            return answer
        messages=[
            {"role":"system","content":"Rewrite the supplied member-services answer in clear, concise language. Treat it as authoritative source text: do not add, remove, infer, or change any fact, amount, date, code, status, or action. Return only the rewritten answer."},
            {"role":"user","content":answer}]
        headers={"Content-Type":"application/json"}
        if self.provider in {"ollama","ollama_cloud"}:
            payload={"model":self.model,"stream":False,"messages":messages,"options":{"temperature":0,"num_predict":max_output}}
            endpoint=self.base_url+"/api/chat"
            if self.provider=="ollama_cloud": headers["Authorization"]="Bearer "+self.api_key
        else:
            payload={"model":self.model,"temperature":0,"max_tokens":max_output,"messages":messages}
            endpoint=self.base_url+"/chat/completions"
            headers["Authorization"]="Bearer "+self.api_key
        req=urllib.request.Request(endpoint,data=json.dumps(payload).encode("utf-8"),method="POST",headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=max(0.1,min(self.request_timeout,timeout))) as res:
                body=json.loads(res.read(1_000_000).decode("utf-8"))
            if self.provider in {"ollama","ollama_cloud"}:
                candidate=body["message"]["content"].strip()
                usage=body.get("usage") or {}
                if self.provider=="ollama_cloud" and not usage:
                    usage={"prompt_tokens":body.get("prompt_eval_count"),"completion_tokens":body.get("eval_count")}
            else:
                candidate=body["choices"][0]["message"]["content"].strip()
                usage=body.get("usage") or {}
            if usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None:
                actual=(int(usage["prompt_tokens"])*self.input_rate+int(usage["completion_tokens"])*self.output_rate)/1000
            else:
                actual=reserve
            state["_model_cost_usd"]=round(spent+actual,8)
            if not candidate or not self._preserves_facts(answer,candidate):
                trace.append({"type":"model","provider":self.provider,"decision":"reject_changed_facts"})
                return answer
            trace.append({"type":"model","provider":self.provider,"model":self.model,"decision":"allow_minimized_answer_only"})
            return candidate
        except Exception as exc:
            # Never log prompts, credentials, provider response bodies, or exception text.
            state["_model_cost_usd"]=round(spent+reserve,8)
            trace.append({"type":"model_error","provider":self.provider,"error":type(exc).__name__})
            return answer

    @staticmethod
    def _preserves_facts(original, candidate):
        protected=lambda s: re.findall(r"\$\s?[\d,]+(?:\.\d{1,2})?|\b\d+(?:\.\d+)?%?|\b\d{4}-\d{2}-\d{2}\b|\b(?:IN_PROCESS|PENDED|PAID|DENIED|CO-\d+)\b|\bG26-\d+\b|\bC\d{10}\b",s,re.I)
        a=[x.lower().replace(" ","") for x in protected(original)]
        b=[x.lower().replace(" ","") for x in protected(candidate)]
        return all(b.count(token)>=a.count(token) for token in a) and all(token in a for token in b)
