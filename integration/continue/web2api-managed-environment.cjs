"use strict";
const fs = require("fs");
const path = require("path");

exports.load = function (extensionOutput) {
  extensionOutput = fs.realpathSync(extensionOutput);
  const bindingPath = path.join(extensionOutput, "web2api-installation.json");
  const binding = fs.existsSync(bindingPath) ? JSON.parse(fs.readFileSync(bindingPath, "utf8")) : null;
  let root = binding ? binding.root : extensionOutput;
  for (let depth = 0; !binding && depth < 8; depth++) {
    if (fs.existsSync(path.join(root, "installation.json"))) break;
    root = path.dirname(root);
  }
  const marker = path.join(root, "installation.json");
  if (!fs.existsSync(marker)) return null;
  const manifest = JSON.parse(fs.readFileSync(marker, "utf8"));
  const extension = path.dirname(extensionOutput);
  const normalize = (value) => path.resolve(value).toLowerCase();
  if (manifest.product !== "Web2API-Continue" ||
      normalize(manifest.root) !== normalize(root) ||
      normalize(manifest.extension) !== normalize(extension)) return null;
  const environment = JSON.parse(fs.readFileSync(path.join(root, "environment.json"), "utf8"));
  for (const [key, value] of Object.entries(environment)) {
    if (key.startsWith("W2A_") || key === "PYTHONUTF8" || key === "PYTHONIOENCODING") {
      process.env[key] = String(value);
    }
  }
  const managedPaths = ["apps/node", "apps/npm/node_modules/.bin", "apps/git/cmd", "apps/rg", "venv/Scripts"]
    .map((relative) => path.join(root, relative));
  const managedKeys = new Set(managedPaths.map(normalize));
  const inheritedPaths = (process.env.PATH || "").split(path.delimiter)
    .filter((entry) => entry && !managedKeys.has(normalize(entry)));
  process.env.PATH = [...managedPaths, ...inheritedPaths].join(path.delimiter);
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(root, "browsers");
  // A direct EXE, pinned taskbar icon or OAuth callback has no launcher environment.
  process.env.CONTINUE_GLOBAL_DIR = manifest.continue_dir || path.join(root, "continue");
  return process.env.CONTINUE_GLOBAL_DIR;
};
