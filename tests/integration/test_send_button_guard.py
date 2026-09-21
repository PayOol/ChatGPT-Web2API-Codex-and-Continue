import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from chatgpt_web2api.cdp_driver import SendReadinessError
from chatgpt_web2api.chatgpt_dom import ChatGPTDom

HARNESS = r"""
const input=JSON.parse(process.argv[1]);
function button(testid,label){const b={disabled:false,dataset:{testid},type:'submit',
 getClientRects(){return [1]},getAttribute(){return label},
 getBoundingClientRect(){return {left:0,top:0,width:20,height:20}},contains(el){return el===b}};return b;}
const send=button('send-button','Envoyer');const stop=button('stop-button','Interrompre la réponse');
const form={querySelectorAll(s){if(s==='[data-testid="stop-button"]')return input.busy?[stop]:[];return input.busy?[stop,send]:[send];}};
const composer={closest(){return form}};
const document={querySelector(){return composer},elementFromPoint(){return send}};
const result=eval(input.code);
process.stdout.write(JSON.stringify({result}));
"""


class SendButtonGuardTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, busy):
        observations = []

        async def js(code):
            p = subprocess.run(
                ["node", "-e", HARNESS, json.dumps({"code": code, "busy": busy})],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=10,
                creationflags=0x08000000,
            )
            value = json.loads(p.stdout)
            observations.append(value)
            return value["result"]

        driver = SimpleNamespace(
            _js_strict=js,
            _cdp=AsyncMock(),
            _capture_selector_diagnostic=AsyncMock(),
            _breakers=None,
        )
        with patch("chatgpt_web2api.chatgpt_dom.SEND_BUTTON_POLL_MAX_WAIT_S", 0):
            if busy:
                with self.assertRaisesRegex(SendReadinessError, "busy"):
                    await ChatGPTDom(driver).click_send()
            else:
                await ChatGPTDom(driver).click_send()
        return driver._cdp.await_args_list

    async def test_generation_active_cannot_dispatch_clicks(self):
        values = await self.run_case(True)
        self.assertEqual(len(values), 0)

    async def test_idle_send_still_dispatches_expected_events(self):
        values = await self.run_case(False)
        self.assertEqual(
            [v.args[1]["type"] for v in values], ["mouseMoved", "mousePressed", "mouseReleased"]
        )


if __name__ == "__main__":
    unittest.main()
