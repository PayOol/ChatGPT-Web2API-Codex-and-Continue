const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");

exports.run = async function () {
  const root = process.env.WEB2API_EDITOR_TEST_ROOT;
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "installation.json"), "utf8"));
  const normalize = (value) => path.resolve(value).toLowerCase();
  const extension = vscode.extensions.getExtension("Continue.continue");
  assert.ok(extension, "Continue must be installed without manual Marketplace installation");
  assert.equal(normalize(path.dirname(extension.extensionPath)),
    normalize(path.join(process.env.USERPROFILE, ".vscode/extensions")));
  const api = await extension.activate();
  assert.ok(api?.extension?.configHandler, "Continue must activate successfully");
  let timer;
  try {
    const result = await Promise.race([
      api.extension.configHandler.loadConfig(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Configuration load timed out")), 120000); }),
    ]);
    assert.ok(result.config, JSON.stringify(result.errors));
    const model = result.config.modelsByRole.chat.find((entry) => entry.title === "ChatGPT Web2API");
    assert.ok(model, "ChatGPT Web2API must appear in Continue's actual loaded model catalog");
    for (const role of ["chat", "edit", "apply"]) {
      assert.equal(result.config.selectedModelByRole[role]?.title, "ChatGPT Web2API",
        "The installed model must be selected for " + role);
    }
    assert.equal(model.model, "auto");
    assert.match(model.apiBase, /^http:\/\/127\.0\.0\.1:\d+\/v1\/?$/);
    assert.equal(normalize(process.env.CONTINUE_GLOBAL_DIR), normalize(path.join(process.env.USERPROFILE, ".continue")));
    assert.equal(normalize(process.env.W2A_INSTALL_ROOT), normalize(root));
    assert.equal(normalize(process.env.PATH.split(path.delimiter)[0]), normalize(path.join(root, "apps/node")));
    assert.equal(manifest.profile_mode, "normal");
    assert.equal(normalize(manifest.vscode_user_data), normalize(path.join(process.env.APPDATA, "Code")));
    assert.equal(fs.existsSync(path.join(path.dirname(manifest.editor), "data")), false);
    const report = {passed:true, extension:extension.extensionPath, profile:process.env.CONTINUE_GLOBAL_DIR,
      model:model.title, apiBase:model.apiBase, launcherEnvironment:false, profileMode:manifest.profile_mode};
    fs.writeFileSync(path.join(root, "logs/editor-runtime.json"), JSON.stringify(report, null, 2));
    console.log("WEB2API_EDITOR_RUNTIME_OK " + JSON.stringify(report));
  } finally {
    clearTimeout(timer);
  }
};
