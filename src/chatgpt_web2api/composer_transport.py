"""Strict composer controls, with an explicit send/stop distinction."""

import asyncio
import json
import time


async def click_control(driver, kind):
    if kind not in ("send", "stop"):
        raise ValueError("Unknown composer control")
    raw = await driver._js_strict(
        """(function(){
      const kind=KIND;
      const composer=document.querySelector('#prompt-textarea');
      const form=composer&&composer.closest('form');
      if(!form)return JSON.stringify({status:'missing'});
      const visible=b=>b.getClientRects().length && !b.disabled;
      const stop=Array.from(form.querySelectorAll('[data-testid="stop-button"]')).find(visible);
      if(kind==='send'&&stop)return JSON.stringify({status:'busy'});
      const buttons=Array.from(form.querySelectorAll('button')).filter(visible);
      const b=kind==='stop'?stop:buttons.find(b=>
        b.dataset.testid!=='stop-button' &&
        !/stop|interrompre|arrêter/i.test(b.getAttribute('aria-label')||'') &&
        (b.dataset.testid==='send-button'||/send|envoyer/i.test(b.getAttribute('aria-label')||'')||b.type==='submit'));
      if(!b)return JSON.stringify({status:'missing'});
      const r=b.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
      const hit=document.elementFromPoint(x,y);
      if(!hit||!b.contains(hit))return JSON.stringify({status:'occluded'});
      // ChatGPT's current composer ignores CDP Input.dispatchMouseEvent while
      // its window is in the background, even though the hit test succeeds.
      // HTMLElement.click() reaches the same strictly selected, visible and
      // enabled control and is verified by the post-send acknowledgment gate.
      b.click();
      return JSON.stringify({status:'clicked'});
    })()""".replace("KIND", json.dumps(kind))
    )
    state = json.loads(raw)
    return state.get("status", "missing")


async def wait_idle(driver, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        value = await driver._js_strict("!!document.querySelector('[data-testid=\"stop-button\"]')")
        if value is False or value in ("false", "0", 0):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def settle_completed_turn(driver, frame):
    """Only reload an idle-stuck UI after an exact validated completed frame."""
    if await wait_idle(driver, 0):
        return
    snapshot = await driver.read_agent_exchange()
    from .cdp_driver import SendReadinessError

    if (
        not snapshot.get("literal")
        or not snapshot.get("paired")
        or snapshot.get("conversation") != driver._current_conv_id
        or not snapshot.get("assistant", "").strip().startswith(frame)
    ):
        raise SendReadinessError("Active conversation changed; refusing to interrupt it")
    await click_control(driver, "stop")
    if await wait_idle(driver, 3):
        return
    # Read-only navigation to the same conversation: never re-send a prompt.
    await driver.navigate_conversation(snapshot["conversation"])
    if not await wait_idle(driver, 5):
        raise SendReadinessError("Previous completed response still blocks the composer")
