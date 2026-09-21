"""Configure the managed Windows distribution. Never edits the user's normal VS Code profile."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import time

VERSION = "0.3.0"


def write_changed(path: Path, data: bytes, backup: Path):
    if path.exists() and path.read_bytes() == data:
        return False
    if path.exists():
        destination = backup / (
            hashlib.sha256(str(path).encode()).hexdigest()[:12] + "-" + path.name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".install.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return True


def write_json(path, value, backup):
    return write_changed(
        path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), backup
    )


def read_json(path, fallback=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else (fallback or {})


def available_port(preferred, avoid=()):
    for port in range(preferred, preferred + 100):
        if port in avoid:
            continue
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise RuntimeError(f"No free loopback port near {preferred}")


def apply_continue_patches(extension: Path, source: Path, backup: Path):
    if read_json(extension / "package.json").get("version") != "2.0.0":
        raise RuntimeError("This release requires the pinned Continue 2.0.0 extension.")
    changes = []
    for name in ["continue-full-access-changes.json", "continue-auto-compaction-changes.json"]:
        changes.extend(read_json(source / "integration/continue" / name))
    texts = {}
    for change in changes:
        relative = Path(change["file"].replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid patch target")
        path = extension / relative
        text = texts.setdefault(path, path.read_text(encoding="utf-8"))
        if change["after"] in text:
            continue
        if text.count(change["before"]) != 1:
            raise RuntimeError(f"Unsupported Continue bundle: {relative}. No patch was written.")
        texts[path] = text.replace(change["before"], change["after"], 1)
    # Validate every replacement before writing any bundle.
    for path, text in texts.items():
        write_changed(path, text.encode("utf-8"), backup)
    for name in ["continue-full-access.local.cjs", "continue-auto-compaction.local.cjs"]:
        write_changed(
            extension / "out" / name, (source / "integration/continue" / name).read_bytes(), backup
        )
    return {
        str(path.relative_to(extension)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in texts
    }


def configure(root: Path, source: Path, extension: Path, browser: Path):
    root = root.resolve()
    source = source.resolve()
    extension = extension.resolve()
    browser = browser.resolve()
    marker = root / "installation.json"
    old = read_json(marker)
    if old and old.get("product") != "Web2API-Continue":
        raise RuntimeError("Installation directory belongs to another product.")
    if not extension.is_relative_to(root):
        raise ValueError("Only the extension in the managed installation may be patched.")
    backup = root / "backups" / time.strftime("%Y%m%d-%H%M%S")
    patch_hashes = apply_continue_patches(extension, source, backup)
    port = old.get("api_port") or available_port(8080)
    cdp = old.get("cdp_port") or available_port(9222, avoid=(port,))
    continue_dir = root / "continue"
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    node = root / "apps/node/node.exe"
    python = root / "venv/Scripts/python.exe"
    computer_python = root / "computer-venv/Scripts/python.exe"
    codex_candidates = list((root / "apps/npm/node_modules/@openai").rglob("codex.exe"))
    codex_candidates = [p for p in codex_candidates if "x86_64" in str(p)]
    if not codex_candidates:
        raise RuntimeError("Pinned native Codex binary missing.")
    codex = sorted(codex_candidates)[0]
    managed_path = os.pathsep.join(
        [
            str(node.parent),
            str(root / "apps/npm/node_modules/.bin"),
            str(root / "apps/git/cmd"),
            str(root / "apps/rg"),
            str(python.parent),
            os.environ.get("PATH", ""),
        ]
    )
    env = {
        "CONTINUE_GLOBAL_DIR": str(continue_dir),
        "W2A_INSTALL_ROOT": str(root),
        "W2A_NODE": str(node),
        "W2A_CODEX_BINARY": str(codex),
        "W2A_COMPUTER_PYTHON": str(computer_python),
        "W2A_BROWSER_EXECUTABLE": str(browser),
        "W2A_MEDIA_DIR": str(root / "media"),
        "W2A_STATE_DIR": str(state_dir),
        "W2A_API_BASE": f"http://127.0.0.1:{port}/v1",
        "W2A_HOSTINGER_ENTRY": str(
            root / "apps/npm/node_modules/hostinger-api-mcp/src/servers/all.js"
        ),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PATH": managed_path,
    }
    import yaml

    config_path = continue_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config = config or {}
    if not isinstance(config, dict):
        raise ValueError("Continue config must be an object; restore its backup before repairing.")
    config.update(name="ChatGPT Web local", version="1.0.0", schema="v1")
    model = {
        "name": "ChatGPT Web2API",
        "provider": "openai",
        "model": "auto",
        "apiBase": env["W2A_API_BASE"],
        "apiKey": "not-needed",
        "useResponsesApi": False,
        "useLegacyCompletionsEndpoint": False,
        "capabilities": ["tool_use", "image_input"],
        "roles": ["chat", "edit", "apply"],
        "requestOptions": {"timeout": 660},
    }
    config["models"] = [model] + [
        m for m in config.get("models", []) if m.get("name") != model["name"]
    ]
    servers = []
    for name, relative in [
        ("Local", "local-capabilities/server.py"),
        ("Browser", "browser/continue_server.py"),
        ("Computer", "computer-use/continue_server.py"),
        ("Vision", "vision/server.py"),
        ("Connected", "connected/server.py"),
    ]:
        servers.append(
            {
                "name": name,
                "type": "stdio",
                "command": str(python),
                "args": ["-u", str(root / "tools" / relative)],
                "cwd": ".",
                "env": env,
                "connectionTimeout": 60000,
            }
        )
    config["mcpServers"] = servers + [
        s for s in config.get("mcpServers", []) if s.get("name") not in {s["name"] for s in servers}
    ]
    write_changed(
        config_path,
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode("utf-8"),
        backup,
    )
    write_json(
        continue_dir / "full-access.local.json",
        {"enabled": True, "scope": "all-configured-tools"},
        backup,
    )
    write_json(
        continue_dir / "auto-compaction.local.json",
        {
            "enabled": True,
            "threshold": 0.75,
            "keepRecentMessages": 8,
            "minAdvance": 8,
            "cooldownSeconds": 180,
            "maxSummaryChars": 12000,
        },
        backup,
    )
    context_path = continue_dir / "index/globalContext.json"
    context = read_json(context_path)
    context.setdefault("sharedConfig", {}).update(
        disableSessionTitles=True, enableExperimentalTools=True
    )
    context.setdefault("selectedModelsByProfileId", {}).setdefault("local", {}).update(
        {role: "ChatGPT Web2API" for role in ["chat", "edit", "apply"]}
    )
    write_json(context_path, context, backup)
    write_changed(
        continue_dir / "rules/local-agent-tools.md",
        (source / "integration/continue/local-agent-tools.md").read_bytes(),
        backup,
    )
    data = root / "vscode-data"
    settings_path = data / "User/settings.json"
    settings = read_json(settings_path)
    settings.update(
        {
            "continue.enableTabAutocomplete": False,
            "continue.enableNextEdit": False,
            "update.mode": "none",
        }
    )
    write_json(settings_path, settings, backup)
    db = data / "User/globalStorage/state.vscdb"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db, timeout=5) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key='extensions.donotAutoUpdate'"
        ).fetchone()
        values = json.loads(row[0]) if row else []
        if "continue.continue" not in values:
            values.append("continue.continue")
        conn.execute(
            "INSERT OR REPLACE INTO ItemTable(key,value) VALUES (?,?)",
            ("extensions.donotAutoUpdate", json.dumps(values)),
        )
    server = read_json(root / "config.json")
    server.update(
        chrome_path=str(browser),
        user_data_dir=str(root / "browser-profile"),
        cdp_port=cdp,
        headless=False,
        host="127.0.0.1",
        port=port,
        default_model="auto",
        tab_mode="owned",
        parallel_tabs=False,
        request_timeout=600,
        log_level="INFO",
        log_file=str(root / "logs/server.log"),
    )
    write_json(root / "config.json", server, backup)
    # Do not persist the inherited PATH: environment.ps1 rebuilds it at launch.
    stored_env = {k: v for k, v in env.items() if k != "PATH"}
    write_json(root / "environment.json", stored_env, backup)
    write_changed(root / "BIENVENUE.md", (source / "installer/BIENVENUE.md").read_bytes(), backup)
    manifest = {
        "product": "Web2API-Continue",
        "version": VERSION,
        "root": str(root),
        "api_port": port,
        "cdp_port": cdp,
        "extension": str(extension),
        "browser": str(browser),
        "codex": str(codex),
        "source": str(source),
        "continue_patches": patch_hashes,
        "configured_servers": 5,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(marker, manifest, backup)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in ["root", "source", "extension", "browser"]:
        parser.add_argument("--" + arg, required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            configure(args.root, args.source, args.extension, args.browser),
            ensure_ascii=False,
            indent=2,
        )
    )
