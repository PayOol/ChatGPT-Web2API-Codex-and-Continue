const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");

exports.run = async function () {
  const root = process.env.WEB2API_EDITOR_TEST_ROOT;
  const normalize = (value) => path.resolve(value).toLowerCase();
  const extension = vscode.extensions.getExtension("Continue.continue");
  assert.ok(extension, "Continue must be installed without manual Marketplace installation");
  assert.equal(normalize(path.dirname(extension.extensionPath)),
    normalize(path.join(root, "apps/vscode/data/extensions")));
  const api = await extension.activate();
  assert.ok(api?.extension?.configHandler, "Continue must activate successfully");
  let timer;
  try {
    const result = await Promise.race([
      api.extension.configHandler.loadConfig(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Configuration load timed out")), 120000); }),
    ]);
    assert.ok(result.config, JSON.stringify(result.errors));
    const model = result.config.models.find((entry) => entry.title === "ChatGPT Web2API");
    assert.ok(model, "ChatGPT Web2API must appear in Continue's actual loaded model catalog");
    assert.equal(model.model, "auto");
    assert.match(model.apiBase, /^http:\/\/127\.0\.0\.1:\d+\/v1\/?$/);
    assert.equal(normalize(process.env.CONTINUE_GLOBAL_DIR), normalize(path.join(root, "continue")));
    assert.equal(normalize(process.env.W2A_INSTALL_ROOT), normalize(root));
    assert.equal(normalize(process.env.PATH.split(path.delimiter)[0]), normalize(path.join(root, "apps/node")));
    const report = {passed:true, extension:extension.extensionPath, profile:process.env.CONTINUE_GLOBAL_DIR,
      model:model.title, apiBase:model.apiBase, launcherEnvironment:false};
    fs.writeFileSync(path.join(root, "logs/editor-runtime.json"), JSON.stringify(report, null, 2));
    console.log("WEB2API_EDITOR_RUNTIME_OK " + JSON.stringify(report));
  } finally {
    clearTimeout(timer);
  }
};
