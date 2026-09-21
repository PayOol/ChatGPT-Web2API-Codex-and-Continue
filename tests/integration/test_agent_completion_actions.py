"""The finished action row must belong to the current assistant turn."""

import json
import os
import subprocess

import pytest

from chatgpt_web2api.agent_dom import AGENT_TEXT_JS

HARNESS = r"""
const input=JSON.parse(process.argv[1]);
function scope(count,actions,parentElement){return {parentElement,querySelectorAll(s){
  if(s==='[data-message-author-role=assistant]')return Array(count).fill({});
  return actions.map(visible=>({getClientRects(){return visible?[{}]:[]}}));
}};}
const shared=scope(3,[true],null);
const turn=scope(1,input.current?[input.visible]:[],shared);
const message=scope(0,[],turn);
eval(input.code);
console.log(JSON.stringify(web2apiAgentHasActions(message)));
"""


@pytest.mark.parametrize(
    "current,visible,expected", [(True, True, True), (True, False, False), (False, True, False)]
)
def test_completed_row_does_not_leak_from_older_turn(current, visible, expected):
    result = subprocess.run(
        [
            "node",
            "-e",
            HARNESS,
            json.dumps(dict(code=AGENT_TEXT_JS, current=current, visible=visible)),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    assert json.loads(result.stdout) is expected
