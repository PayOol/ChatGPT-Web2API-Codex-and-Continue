"use strict";
const fs = require("fs");
const path = require("path");
const os = require("os");
exports.isEnabled = function (configPath = path.join(process.env.CONTINUE_GLOBAL_DIR || path.join(os.homedir(), ".continue"), "full-access.local.json")) {
  try {
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    return config.enabled === true && config.scope === "all-configured-tools";
  } catch (_) { return false; }
};
