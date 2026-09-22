"""Progress announcements must not silently terminate Continue's tool loop."""

import json
import unittest

import test_agent_bridge as fixture

from chatgpt_web2api.tool_bridge import TaskContinuationError, ToolBridge


def history():
    return fixture.MESSAGES + [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_previous", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"demo.py"}'},
        }]},
        {"role": "tool", "tool_call_id": "call_previous", "content": "The search returned no results."},
    ]


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ToolBridge.from_request(fixture.body(messages=history()))

    def parse(self, content, status=None, calls=None):
        data = {"content": content, "tool_calls": calls or []}
        if status is not None:
            data["task_status"] = status
        return self.bridge.parse(self.bridge.opening + json.dumps(data) + "</web2api_response>")

    def test_screenshot_progress_without_calls_is_rejected(self):
        for content in [
            "Je poursuis l'audit à partir des éléments déjà inspectés. Prochaine étape nécessaire : analyser et corriger.",
            "La recherche n'a rien trouvé. Prochaine étape nécessaire : vérifier les routes.",
            "Je n'avais pas terminé la tâche. Je reprends maintenant l'audit complet.",
            "I will continue with the code changes.",
        ]:
            with self.subTest(content=content), self.assertRaises(TaskContinuationError):
                self.parse(content)

    def test_state_handles_other_languages_without_matching_prose(self):
        with self.assertRaises(TaskContinuationError):
            self.parse("Voy a continuar.", "in_progress")

    def test_completed_answer_is_plain_openai_message(self):
        self.assertEqual(self.parse("Audit et corrections terminés.", "completed"),
                         {"role": "assistant", "content": "Audit et corrections terminés."})
        advice = "Analyse terminée. Prochaine étape nécessaire : corriger, hors du périmètre demandé."
        self.assertEqual(self.parse(advice, "completed")["content"], advice)

    def test_legitimate_stops_and_examples_remain_final(self):
        for content in [
            "Le fichier est inaccessible : permission refusée.",
            "Quel environnement dois-je tester ?",
            "J'ai arrêté comme demandé.",
            "Je vais continuer si vous autorisez la modification.",
            "I will continue after you provide access.",
            "Exemple :\n```text\nJe vais modifier le code.\n```",
            '> Je reprends maintenant.\nCette phrase explique le défaut.',
            "Analyse terminée. Aucune modification demandée.",
        ]:
            with self.subTest(content=content):
                self.assertEqual(self.parse(content)["content"], content)

    def test_none_choice_and_new_user_request_are_not_forced_to_call(self):
        self.bridge = ToolBridge.from_request(fixture.body(messages=history(), tool_choice="none"))
        self.assertEqual(self.parse("Je continue demain.")["content"], "Je continue demain.")
        self.bridge = ToolBridge.from_request(fixture.body(messages=history() + [
            {"role": "user", "content": "Traduis : I will continue."},
        ]))
        self.assertEqual(self.parse("Je vais continuer.")["content"], "Je vais continuer.")

    def test_calls_are_preserved_and_never_fabricated(self):
        msg = self.parse("Je poursuis l'audit.", "in_progress", [fixture.CALL])
        self.assertEqual(json.loads(msg["tool_calls"][0]["function"]["arguments"]), {"path": "demo.py"})
        with self.assertRaises(TaskContinuationError):
            self.parse("Done", "completed", [fixture.CALL])

    def test_invalid_status_and_verified_nonce_fallback_are_checked(self):
        with self.assertRaises(TaskContinuationError):
            self.parse("Done", "unknown")
        frame = fixture.wrap(self.bridge, content="Je poursuis l'audit.")
        with self.assertRaises(TaskContinuationError):
            self.bridge.parse_verified_final(frame.replace(self.bridge.nonce, "a" * 32))

    def test_incremental_reminder_keeps_permissions_and_only_available_routes(self):
        prompt = self.bridge.prompt(history()[-2:], prior_messages=fixture.MESSAGES)
        self.assertIn("user forbids inspection", prompt)
        self.assertIn("current results already establish", prompt)
        self.assertNotIn("exec/ALL_TOOLS", prompt)
        self.assertIn("empty tool_calls array ENDS", prompt)


class ContinuationHTTPTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.HTTPTests.asyncSetUp
    asyncTearDown = fixture.HTTPTests.asyncTearDown

    async def test_progress_is_repaired_once_then_actual_tool_and_final(self):
        self.driver.answers = [
            {"content": "Je poursuis l'audit.", "tool_calls": []},
            {"content": "Je vérifie le dernier fichier.", "tool_calls": [fixture.CALL], "task_status": "in_progress"},
            {"content": "Audit terminé, résultat vérifié.", "tool_calls": [], "task_status": "completed"},
        ]
        messages = history()
        req = fixture.body(messages=messages)
        response = await self.client.post("/v1/chat/completions", json=req)
        self.assertEqual(response.status, 200)
        first = (await response.json())["choices"][0]
        self.assertEqual(first["finish_reason"], "tool_calls")
        self.assertEqual(len(self.driver.prompts), 2)
        self.assertIn("only correction attempt", self.driver.prompts[-1])
        retry = await self.client.post("/v1/chat/completions", json=req)
        self.assertEqual((await retry.json())["choices"][0], first)
        self.assertEqual(len(self.driver.prompts), 2)
        messages += [first["message"], {"role": "tool", "content": "Final check passed.",
                     "tool_call_id": first["message"]["tool_calls"][0]["id"]}]
        response = await self.client.post("/v1/chat/completions", json=fixture.body(messages=messages, stream=True))
        output = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn('"finish_reason": "stop"', output)
        events = [json.loads(line[6:]) for line in output.splitlines() if line.startswith("data: {")]
        self.assertIn("Audit terminé", events[0]["choices"][0]["delta"]["content"])
        self.assertEqual(len(self.driver.prompts), 3)

    async def test_repeated_progress_cannot_loop_or_be_reported_as_success(self):
        self.driver.answers = [{"content": "Je poursuis l'audit.", "tool_calls": []}] * 2
        response = await self.client.post("/v1/chat/completions", json=fixture.body(messages=history()))
        self.assertEqual(response.status, 422)
        self.assertNotIn("choices", await response.json())
        self.assertEqual(len(self.driver.prompts), 2)
        self.assertTrue(all(p["repair_attempted"] for p in self.api._agent_state.pending_frames.values()))

    async def test_blocker_passes_without_extra_request(self):
        self.driver.answers = [{"content": "Accès refusé au fichier requis.", "tool_calls": [], "task_status": "blocked"}]
        response = await self.client.post("/v1/chat/completions", json=fixture.body(messages=history()))
        self.assertEqual((await response.json())["choices"][0]["finish_reason"], "stop")
        self.assertEqual(len(self.driver.prompts), 1)
