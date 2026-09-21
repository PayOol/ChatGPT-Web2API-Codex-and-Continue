"use strict";
const assert = require("node:assert/strict");
const http = require("node:http");
const { once } = require("node:events");
const path = require("node:path");
const helperPath = path.resolve(__dirname, "../../integration/continue/continue-long-wait.local.cjs");
const { configureLongWait } = require(helperPath);
const patches = require("../../integration/continue/continue-long-wait-changes.json");

(async () => {
  let requests = 0;
  const server = http.createServer((req, res) => {
    requests++;
    if (req.url === "/body") {
      res.writeHead(200); res.write("start");
      return;
    }
    setTimeout(() => { res.writeHead(200); res.end("finished"); }, 80);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const apiBase = `http://127.0.0.1:${server.address().port}/v1`;
    const config = { apiBase, requestOptions: { timeout: 0 } };
    // Run the actual bundle patch, not a hand-copied initializer.
    class FakeOpenAI { constructor(options) { this.fetch = options.fetch; this.maxRetries = 2; } }
    const initialize = new Function("OpenAI", "customFetch", "config3", "require",
      patches[0].after + "\nreturn this.openai;");
    const client = initialize.call({apiBase}, FakeOpenAI, () => fetch, config, () => require(helperPath));
    assert.equal(client.maxRetries, 0);
    const response = await client.fetchWithTimeout(apiBase, {}, 1, new AbortController());
    assert.equal(await response.text(), "finished"); // 80ms response survives 1ms SDK budget.
    assert.equal(requests, 1);
    const abort = new AbortController();
    const pending = client.fetchWithTimeout(apiBase, { signal: abort.signal }, 1, new AbortController());
    setTimeout(() => abort.abort(), 15);
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(requests, 2); // Cancellation must never retry.
    const bodyAbort = new AbortController();
    const bodyResponse = await client.fetchWithTimeout(apiBase.replace("/v1", "/body"),
      { signal: bodyAbort.signal }, 1, new AbortController());
    const reading = bodyResponse.text();
    bodyAbort.abort();
    await assert.rejects(reading, { name: "AbortError" });
    for (const cfg of [
      {apiBase:"https://api.openai.com/v1",requestOptions:{timeout:0}},
      {apiBase:"http://example.com/v1",requestOptions:{timeout:0}},
      {apiBase,requestOptions:{timeout:660}}, {apiBase,requestOptions:{}},
    ]) {
      const original = () => {};
      const other = {fetchWithTimeout:original,maxRetries:2};
      assert.equal(configureLongWait(other, cfg), false);
      assert.equal(other.fetchWithTimeout, original);
      assert.equal(other.maxRetries, 2);
    }
    console.log("PASS: actual adapter patch, delayed HTTP, both cancellation phases, no resends, remote isolation");
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
