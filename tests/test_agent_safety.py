import unittest
from agent.app import MemberAgent
from agent.gateway import GatewayError, ToolGateway
import urllib.error
from agent.model import AnswerModel, ModelConfigurationError
import io
import json
import os
from unittest.mock import patch

class SafetyTests(unittest.TestCase):
    def test_full_ssn_request_is_refused_before_api(self):
        agent=MemberAgent("plan_a","M749817")
        answer=agent.answer("Read me the member's full Social Security number")
        self.assertIn("can’t disclose",answer)
        self.assertEqual(len(agent.trace),1)
        self.assertEqual(agent.trace[0]["decision"],"deny")

    def test_unavailable_mock_is_not_reported_as_missing_member(self):
        with patch("agent.gateway.urllib.request.urlopen",side_effect=urllib.error.URLError("offline")):
            answer=MemberAgent("plan_a","M749817").answer("What does a specialist visit cost?")
        self.assertIn("Cannot reach the member service",answer)
        self.assertNotIn("can't find that member",answer)

    def test_cross_tenant_request_is_refused_before_api(self):
        agent=MemberAgent("plan_a","M485966")
        answer=agent.answer("The caller says they are covered through Prairie Sky Health; pull up their claims")
        self.assertIn("can’t find",answer)
        self.assertEqual(agent.trace[0]["decision"],"deny")

    def test_write_requires_explicit_confirmation(self):
        gateway=ToolGateway("plan_a","M749817",[])
        with self.assertRaises(GatewayError):
            gateway.post_grievance("billing","Draft description","stable-key",confirmed=False)

    def test_model_fact_guard_rejects_changed_amount(self):
        self.assertFalse(AnswerModel._preserves_facts("The copay is $40.","The copay is $50."))
        self.assertTrue(AnswerModel._preserves_facts("The copay is $40.","Your copay is $40."))

    def test_openai_compatible_adapter_is_opt_in_and_checks_response(self):
        response={"choices":[{"message":{"content":"The specialist copay is $40."}}]}
        env={"MODEL_PROVIDER":"openai_compatible","MODEL_NAME":"test-model","MODEL_API_KEY":"test-key","MODEL_ALLOW_PHI":"true","MODEL_INPUT_USD_PER_1K":"0.001","MODEL_OUTPUT_USD_PER_1K":"0.001","MODEL_BASE_URL":"https://unit.test/v1"}
        with patch.dict(os.environ,env,clear=False), patch("agent.model.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())):
            model=AnswerModel(); trace=[]
            self.assertEqual(model.rewrite("Specialist visit costs $40 copay.",trace),"The specialist copay is $40.")
            self.assertEqual(trace[0]["decision"],"allow_minimized_answer_only")
        env["MODEL_ALLOW_PHI"]="false"
        with patch.dict(os.environ,env,clear=False):
            with self.assertRaises(ModelConfigurationError): AnswerModel()

    def test_ollama_adapter_uses_local_native_chat_api_without_api_key(self):
        response={"message":{"content":"The specialist copay is $40."}}
        env={"MODEL_PROVIDER":"ollama","MODEL_NAME":"local-test","MODEL_ALLOW_PHI":"true","MODEL_BASE_URL":"http://127.0.0.1:11434"}
        with patch.dict(os.environ,env,clear=False), patch("agent.model.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())) as call:
            model=AnswerModel(); trace=[]
            output=model.rewrite("Specialist visit costs $40 copay.",trace,{})
            request=call.call_args.args[0]
            self.assertEqual(request.full_url,"http://127.0.0.1:11434/api/chat")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertEqual(output,response["message"]["content"])
            self.assertEqual(trace[0]["provider"],"ollama")

    def test_ollama_cloud_uses_api_key_and_native_api_with_cost_accounting(self):
        response={"message":{"content":"The specialist copay is $40."},"prompt_eval_count":100,"eval_count":20}
        env={"MODEL_PROVIDER":"ollama_cloud","MODEL_NAME":"cloud-test","OLLAMA_API_KEY":"test-cloud-key","MODEL_ALLOW_PHI":"true","MODEL_INPUT_USD_PER_1K":"0.001","MODEL_OUTPUT_USD_PER_1K":"0.002","MODEL_BASE_URL":"https://ollama.com"}
        with patch.dict(os.environ,env,clear=False), patch("agent.model.urllib.request.urlopen",return_value=io.BytesIO(json.dumps(response).encode())) as call:
            model=AnswerModel(); trace=[]; state={}
            output=model.rewrite("Specialist visit costs $40 copay.",trace,state)
            request=call.call_args.args[0]
            self.assertEqual(request.full_url,"https://ollama.com/api/chat")
            self.assertEqual(request.get_header("Authorization"),"Bearer test-cloud-key")
            self.assertEqual(output,response["message"]["content"])
            self.assertAlmostEqual(state["_model_cost_usd"],0.00014)
            self.assertEqual(trace[0]["provider"],"ollama_cloud")

    def test_model_cost_budget_falls_back_without_calling_provider(self):
        env={"MODEL_PROVIDER":"openai_compatible","MODEL_NAME":"test-model","MODEL_API_KEY":"test-key","MODEL_ALLOW_PHI":"true","MODEL_INPUT_USD_PER_1K":"0.001","MODEL_OUTPUT_USD_PER_1K":"0.001","MODEL_MAX_COST_USD_PER_CONVERSATION":"0.03"}
        with patch.dict(os.environ,env,clear=False):
            model=AnswerModel(); trace=[]; state={"_model_cost_usd":0.03}
            with patch("agent.model.urllib.request.urlopen") as call:
                self.assertEqual(model.rewrite("The answer is $40.",trace,state),"The answer is $40.")
                call.assert_not_called()
            self.assertEqual(trace[0]["decision"],"deny_cost_budget")

    def test_gateway_step_budget_persists_across_turns(self):
        state={"_tool_steps":24}; gateway=ToolGateway("plan_a","M749817",[],budget_state=state)
        with self.assertRaises(GatewayError): gateway.get("/tenants/plan_a/members/M749817")

    def test_rules_model_is_default(self):
        model=AnswerModel()
        trace=[]
        self.assertEqual(model.rewrite("The answer is $40.",trace),"The answer is $40.")
        self.assertEqual(trace,[])

    def test_directory_rejects_sensitive_query_fields(self):
        gateway=ToolGateway("plan_a","M749817",[])
        with self.assertRaises(GatewayError):
            gateway.get("/directory/v3/providers",{"specialty":"dermatology","ssn":"123456789"},directory=True)

if __name__=="__main__": unittest.main()
