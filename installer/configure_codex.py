"""Configure only the owned Web2API Codex distribution and its bridge environment.

OpenCodex registration is delegated to codex_provider. Native Codex tools,
permissions, plugins, and Continue's normal profile are never configured here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

from configure import available_port, read_json, write_changed, write_json

VERSION = "0.4.0"
PRODUCT = "Web2API-Continue"  # Retained for common maintenance/backward compatibility.
TARGET = "codex"


def no_links(path: Path) -> None:
    """Reject redirected managed paths before resolving or writing them."""
    path = path.absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item, "is_junction", lambda: False)()):
            raise ValueError(f"Managed path may not contain a link or junction: {item}")


def validate_root(root: Path, source: Path | None = None) -> dict:
    no_links(root)
    root = root.resolve()
    protected = {Path(root.anchor), Path.home().resolve()}
    for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)", "SystemRoot", "CODEX_HOME", "OPENCODEX_HOME"):
        if value := os.environ.get(name):
            protected.add(Path(value).resolve())
    if value := os.environ.get("LOCALAPPDATA"):
        protected.add((Path(value) / "Programs").resolve())
    protected.update(Path.home() / name for name in (".codex", ".opencodex", ".continue", ".vscode"))
    if root in protected or any(root in p.parents for p in protected):
        raise ValueError("Choose a dedicated installation subdirectory, not a user/system root.")
    if source is not None:
        source = source.resolve()
        if source != root / "app" and (root == source or root in source.parents or source in root.parents):
            raise ValueError("Installation root and source tree must not overlap.")
        for relative in ("pyproject.toml", "src/chatgpt_web2api/__init__.py", "installer/configure_codex.py"):
            if not (source / relative).is_file():
                raise ValueError(f"Incomplete source tree: {relative}")
    if root.exists() and not root.is_dir():
        raise ValueError("Installation root must be a directory.")
    marker = root / "installation.json"
    progress = root / ".installation-in-progress"
    for item in (marker, progress):
        no_links(item)
    old = read_json(marker)
    if marker.exists():
        if not isinstance(old, dict) or old.get("product") != PRODUCT:
            raise ValueError("Installation directory belongs to another product.")
        if old.get("installation_target", "continue") != TARGET:
            raise ValueError("Continue and Codex require separate installation directories.")
        if Path(old.get("root", "")).resolve() != root:
            raise ValueError("Installation marker belongs to another root.")
    elif progress.exists():
        pending = read_json(progress)
        if not isinstance(pending, dict) or pending.get("product") != PRODUCT or pending.get("installation_target") != TARGET or Path(pending.get("root", "")).resolve() != root:
            raise ValueError("Unrecognized installation progress marker.")
    elif root.exists() and any(root.iterdir()):
        raise ValueError("Existing nonempty installation directory is not recognized.")
    # These are the only subtrees written by this configuration/installer.
    for name in ("app", "apps", "venv", "python", "browsers", "browser-profile", "opencodex", "state", "media", "logs", "backups", "cache", "staging", "config.json", "environment.json", "BIENVENUE.md"):
        path = root / name
        no_links(path)
        if path.is_dir():
            for parent, dirs, files in os.walk(path, followlinks=False):
                for child in (*dirs, *files):
                    candidate = Path(parent) / child
                    if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                        target = candidate.resolve()
                        if candidate.parent == root / "python" and candidate.name.startswith("cpython-") and target != candidate and target.parent == root / "python" and target.is_dir():
                            # uv maintains a minor-version alias to its owned patch release.
                            continue
                        raise ValueError(f"Managed tree contains a link or junction: {candidate}")
    return old


def owned_file(root: Path, path: Path) -> Path:
    no_links(path)
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Required file is missing or outside the installation: {path.name}")
    return path


def port(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Invalid installation port.")
    return value


def opencodex_plan(root: Path, old: dict) -> dict:
    """Use the pinned local CLI, retaining an existing user's running service."""
    package = root / "apps/npm/node_modules/@bitkyc08/opencodex"
    metadata = read_json(package / "package.json")
    bins = metadata.get("bin", {})
    relative = bins.get("ocx") if isinstance(bins, dict) else bins
    if not isinstance(relative, str):
        raise ValueError("Pinned OpenCodex CLI entry is missing.")
    entry = owned_file(root, package / relative)
    node = owned_file(root, root / "apps/node/node.exe")
    previous = old.get("opencodex")
    if previous:
        if previous.get("mode") not in ("existing", "managed"):
            raise ValueError("Invalid OpenCodex ownership mode.")
        home = Path(previous["home"]).resolve()
        mode = previous["mode"]
        if mode == "managed" and home != root / "opencodex":
            raise ValueError("Managed OpenCodex home is outside this installation.")
    else:
        external = Path(os.environ.get("OPENCODEX_HOME") or Path.home() / ".opencodex").expanduser().resolve()
        existing = (external / "config.json").exists() or (external / "runtime-port.json").exists()
        mode = "existing" if existing else "managed"
        home = external if existing else root / "opencodex"
    return {
        **(previous or {}),
        "mode": mode,
        "home": str(home),
        "package": str(package),
        "command": [str(node), str(entry)],
        "start_arguments": (previous or {}).get("start_arguments", []),
        "registration": old.get("opencodex", {}).get("registration", "pending"),
    }


def configure(root: Path, source: Path, browser: Path, *, desktop_app_id: str = "", skip_desktop: bool = False) -> dict:
    old = validate_root(root, source)
    root, source = root.resolve(), source.resolve()
    browser = owned_file(root, browser)
    python = owned_file(root, root / "venv/Scripts/python.exe")
    node = owned_file(root, root / "apps/node/node.exe")
    codex_candidates = sorted((root / "apps/npm/node_modules/@openai").rglob("codex.exe"))
    codex_candidates = [p for p in codex_candidates if "x86_64" in str(p)]
    if not codex_candidates:
        raise ValueError("Pinned native Codex binary missing.")
    codex = owned_file(root, codex_candidates[0])
    if not skip_desktop and not desktop_app_id.startswith("OpenAI.Codex_"):
        raise ValueError("A verified OpenAI.Codex desktop application is required.")
    ocx = opencodex_plan(root, old)
    if ocx["mode"] == "managed":
        ocx["codex_binary"] = str(codex)
    codex_home = Path(os.environ["CODEX_HOME"]).expanduser().resolve() if os.environ.get("CODEX_HOME") else ((root / "codex-profile") if skip_desktop else Path.home() / ".codex")
    ocx.setdefault("codex_home", str(codex_home))
    api = port(old["api_port"]) if "api_port" in old else available_port(8081)
    cdp = port(old["cdp_port"]) if "cdp_port" in old else available_port(9223, avoid=(api,))
    if api == cdp:
        raise ValueError("API and browser ports must differ.")
    server = read_json(root / "config.json")
    if not isinstance(server, dict):
        raise ValueError("Bridge configuration must be an object.")
    server.update(
        chrome_path=str(browser), user_data_dir=str(root / "browser-profile"),
        cdp_port=cdp, headless=False, host="127.0.0.1", port=api,
        default_model="auto", tab_mode="owned", parallel_tabs=False,
        request_timeout=0, detector_reasoning_first_content_timeout_seconds=0,
        detector_reasoning_stream_idle_timeout_seconds=0,
        detector_default_first_content_timeout_seconds=0,
        detector_default_stream_idle_timeout_seconds=0, detector_hard_timeout_seconds=0,
        log_level="INFO", log_file=str(root / "logs/server.log"),
    )
    environment = {
        "W2A_INSTALL_ROOT": str(root), "W2A_NODE": str(node), "W2A_CODEX_BINARY": str(codex),
        "W2A_BROWSER_EXECUTABLE": str(browser), "W2A_CHROME_PATH": str(browser),
        "W2A_USER_DATA_DIR": str(root / "browser-profile"), "W2A_CDP_PORT": str(cdp),
        "W2A_PORT": str(api), "W2A_HOST": "127.0.0.1",
        "W2A_STATE_DIR": str(root / "state"), "W2A_MEDIA_DIR": str(root / "media"),
        "W2A_API_BASE": f"http://127.0.0.1:{api}/v1", "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
    }
    manifest = {
        "product": PRODUCT, "version": VERSION, "installation_target": TARGET,
        "root": str(root), "source": str(source), "api_port": api, "cdp_port": cdp,
        "browser": str(browser), "codex": str(codex), "python": str(python),
        "desktop": {"status": "skipped" if skip_desktop else "installed", "app_id": "" if skip_desktop else desktop_app_id},
        "opencodex": ocx, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    backup = root / "backups" / time.strftime("%Y%m%d-%H%M%S")
    for name in ("state", "media", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    write_json(root / "config.json", server, backup)
    write_json(root / "environment.json", environment, backup)
    write_changed(root / "BIENVENUE.md", (
        b"# ChatGPT Web2API pour Codex\n\n"
        b"Connectez votre compte ChatGPT dans le navigateur dedie, puis choisissez "
        b"ChatGPT Web2API dans Codex. Les outils et permissions natifs de Codex sont conserves.\n\n"
        b"Start.ps1 ouvre Codex ; Start.ps1 -ServiceOnly lance la passerelle. "
        b"Doctor.ps1 controle cette installation.\n"
    ), backup)
    write_json(root / "installation.json", manifest, backup)
    return manifest


def save_manifest(root: Path, manifest: dict) -> None:
    write_json(root / "installation.json", manifest, root / "backups" / time.strftime("%Y%m%d-%H%M%S"))


def client_for(plan: dict):
    from codex_provider import OpenCodex

    client = OpenCodex(plan["command"], opencodex_home=plan["home"])
    client.env["CODEX_HOME"] = plan["codex_home"]
    client.env["OPENCODEX_CODEX_SHIM_AUTO_RESTORE"] = "0"
    if plan["mode"] == "managed":
        root = Path(plan["home"]).parent
        client.env["CODEX_CLI_PATH"] = str(owned_file(root, Path(plan["codex_binary"])))
    client.scope["codex_home"] = plan["codex_home"]
    return client


@contextmanager
def provider_environment(plan: dict):
    """Scope provider's home discovery to this short-lived installer process."""
    previous = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = plan["codex_home"]
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = previous


def bootstrap_managed(root: Path, manifest: dict) -> None:
    plan = manifest["opencodex"]
    if plan["mode"] != "managed":
        return
    home = Path(plan["home"])
    if home.resolve() != root / "opencodex":
        raise ValueError("Managed OpenCodex home is outside this installation.")
    no_links(home)
    codex_home = Path(plan["codex_home"])
    no_links(codex_home)
    codex_home.mkdir(parents=True, exist_ok=True)
    path = home / "config.json"
    if path.exists():
        config = read_json(path)
        if not plan.get("port") or config.get("port") != plan["port"]:
            raise ValueError("Existing managed OpenCodex config has no matching ownership record.")
        return
    proxy_port = plan.get("port") or available_port(10100, avoid=(manifest["api_port"], manifest["cdp_port"]))
    config = {
        "port": proxy_port, "hostname": "127.0.0.1", "openaiProviderTierVersion": 2,
        "providers": {"openai": {"adapter": "openai-responses", "baseUrl": "https://chatgpt.com/backend-api/codex", "authMode": "forward", "codexAccountMode": "pool"}},
        "defaultProvider": "openai", "clientIntegrations": {"codex": False, "grok": False, "claude-desktop": False},
        "claudeCode": {"enabled": False}, "codexAutoStart": False, "codexShimAutoRestore": False,
        "syncResumeHistory": False, "syncCodexSubagentDefaults": False, "multiAgentGuidanceEnabled": False,
    }
    plan.update(port=proxy_port, start_arguments=["start", "--port", str(proxy_port)])
    # Journal the selected port before creating the config so an interrupted install resumes.
    save_manifest(root, manifest)
    write_json(path, config, root / "backups" / "opencodex-bootstrap")


def managed_process(plan: dict, process_id: int, *, allow_missing: bool = False) -> dict:
    """Inspect the actual process before stopping it; never rely on a PID file alone."""
    if type(process_id) is not int or process_id <= 0 or os.name != "nt":
        raise ValueError("Managed OpenCodex process identity is unavailable.")
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        f"Get-CimInstance Win32_Process -Filter 'ProcessId = {process_id}' | Select-Object ProcessId,@{{Name='CreationDate';Expression={{$_.CreationDate.ToUniversalTime().ToString('o')}}}},ExecutablePath,CommandLine | ConvertTo-Json -Compress",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode == 0 and not result.stdout.strip() and allow_missing:
        return {}
    try:
        process = json.loads(result.stdout)
        executable = Path(process["ExecutablePath"]).resolve()
        package = Path(plan["package"]).resolve()
        # npm global installs nest Bun, while the private npm prefix hoists it.
        buns = {
            package / "node_modules/bun/bin/bun.exe",
            package.parents[1] / "bun/bin/bun.exe",
        }
        command = process["CommandLine"] or ""
        normalized = command.lower().replace("/", "\\")
        cli = str(package / "src/cli/index.ts").lower().replace("/", "\\")
        if executable not in buns or cli not in normalized or not re.search(r"(?:^|\s)start(?:\s|$)", normalized):
            raise ValueError
        return process
    except (ValueError, TypeError, KeyError):
        raise ValueError("OpenCodex PID is not an owned managed process; it was left untouched.") from None


def start_opencodex(root: Path) -> dict:
    from codex_provider import IntegrationError

    manifest = validate_root(root)
    root = root.resolve()
    if not manifest:
        raise ValueError("Installation manifest missing.")
    plan = manifest["opencodex"]
    if plan["mode"] == "existing":
        # Registration performs attestation. A launcher must never start/restart a borrowed service.
        return {"mode": "existing", "started": False}
    bootstrap_managed(root, manifest)
    client = client_for(plan)
    try:
        client._connect()
    except (IntegrationError, OSError, ValueError):
        pass
    else:
        runtime = read_json(Path(plan["home"]) / "runtime-port.json")
        if runtime.get("port") != plan["port"]:
            raise ValueError("Managed OpenCodex runtime port changed.")
        identity = managed_process(plan, runtime["pid"])
        plan["process"] = {"pid": identity["ProcessId"], "creation_date": identity["CreationDate"]}
        save_manifest(root, manifest)
        return {"mode": "managed", "started": False}
    # Refuse a collision before launching, including an unrelated non-HTTP listener.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port(plan["port"])))
        except OSError:
            raise ValueError("OpenCodex port is occupied by an unverified process; nothing was stopped.") from None
    command = [*plan["command"], *plan["start_arguments"]]
    if plan["start_arguments"] != ["start", "--port", str(plan["port"])]:
        raise ValueError("Unexpected managed OpenCodex startup command.")
    for entry in plan["command"]:
        owned_file(root, Path(entry))
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "opencodex-stdout.log").open("ab") as stdout, (logs / "opencodex-stderr.log").open("ab") as stderr:
        process = subprocess.Popen(command, cwd=root, env=client.env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            client._connect()
            runtime = read_json(Path(plan["home"]) / "runtime-port.json")
            if runtime.get("port") != plan["port"]:
                raise ValueError("Managed OpenCodex runtime port changed.")
            identity = managed_process(plan, runtime["pid"])
            plan["process"] = {"pid": identity["ProcessId"], "creation_date": identity["CreationDate"]}
            save_manifest(root, manifest)
            return {"mode": "managed", "started": True}
        except (IntegrationError, OSError, ValueError, KeyError):
            if process.poll() not in (None, 0):
                raise RuntimeError("Managed OpenCodex failed to start. Inspect logs/opencodex-stderr.log.") from None
            time.sleep(0.5)
    raise RuntimeError("Managed OpenCodex readiness was not verified within 60 seconds. Inspect its logs.")


def route_paths(root: Path, plan: dict) -> tuple[Path, Path]:
    home = Path(plan["codex_home"])
    config = home / "config.toml"
    no_links(config)
    return config, root / "codex-route-state.json"


def root_toml_assignments(text: str) -> tuple[dict, list[str], int]:
    parsed = tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    boundary = next((i for i, line in enumerate(lines) if re.match(r"\s*\[", line)), len(lines))
    return parsed, lines, boundary


def merge_codex_route(root: Path, plan: dict) -> None:
    """Only insert the two root routing keys, keeping every other byte unchanged."""
    config, journal = route_paths(root, plan)
    catalog = Path(plan["codex_home"]) / "opencodex-catalog.json"
    if not catalog.is_file():
        raise ValueError("OpenCodex sync did not produce the expected model catalog.")
    values = {"openai_base_url": f"http://127.0.0.1:{port(plan['port'])}/v1", "model_catalog_json": str(catalog)}
    text = config.read_bytes().decode("utf-8") if config.exists() else ""
    parsed, lines, boundary = root_toml_assignments(text)
    state = read_json(journal)
    if state:
        if state.get("product") != "Web2API-Codex-route" or state.get("path") != str(config):
            raise ValueError("Codex routing ownership journal does not match this profile.")
        if all(parsed.get(key) == value for key, value in values.items()):
            return
        # A crash after journal creation but before write is safe to resume.
        if any(key in parsed for key in values):
            raise ValueError("Codex routing was edited after installation; changes were preserved.")
    elif any(key in parsed for key in values):
        raise ValueError("Codex already has a route/catalog. Existing settings were preserved.")
    backup = root / "backups/codex-config-before.toml"
    if not state:
        backup.parent.mkdir(parents=True, exist_ok=True)
        if config.exists():
            if backup.exists():
                raise ValueError("A Codex config backup already exists without an ownership journal.")
            backup.write_bytes(config.read_bytes())
        state = {"product": "Web2API-Codex-route", "version": 1, "path": str(config), "backup": str(backup) if config.exists() else None, "keys": {key: {"before": {"present": False}, "installed": value} for key, value in values.items()}}
        write_json(journal, state, root / "backups/route-journal")
    newline = "\r\n" if "\r\n" in text else "\n"
    prefix = "".join(lines[:boundary])
    separator = newline if prefix and not prefix.endswith(("\n", "\r")) else ""
    insertion = "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}{newline}" for key, value in values.items())
    updated = prefix + separator + insertion + "".join(lines[boundary:])
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_name(config.name + ".web2api.tmp")
    temporary.write_bytes(updated.encode("utf-8"))
    temporary.replace(config)


def restore_codex_route(root: Path, plan: dict) -> None:
    config, journal = route_paths(root, plan)
    state = read_json(journal)
    if not state:
        return
    if state.get("product") != "Web2API-Codex-route" or state.get("path") != str(config):
        raise ValueError("Invalid Codex routing ownership journal.")
    text = config.read_bytes().decode("utf-8") if config.exists() else ""
    parsed, lines, boundary = root_toml_assignments(text)
    remove = set()
    for key, record in state["keys"].items():
        if key not in ("openai_base_url", "model_catalog_json") or record["before"]["present"]:
            raise ValueError("Unsupported Codex routing ownership record.")
        if key not in parsed:
            continue
        if parsed[key] != record["installed"]:
            raise ValueError("Codex routing was edited by its owner; uninstall preserved it.")
        remove.add(key)
    retained = []
    for i, line in enumerate(lines):
        match = re.match(r"\s*(openai_base_url|model_catalog_json)\s*=", line) if i < boundary else None
        if not match or match.group(1) not in remove:
            retained.append(line)
    result = "".join(retained)
    if any(key in tomllib.loads(result) for key in remove):
        raise ValueError("Codex route formatting changed; uninstall preserved it.")
    if remove:
        config.write_bytes(result.encode("utf-8"))
    journal.unlink()


def registration_diagnostic(root: Path, plan: dict, result: dict) -> dict:
    """Publish only known result codes and owned-model metadata, never raw state."""
    def code(value, allowed):
        return value if isinstance(value, str) and value in allowed else "unknown"

    public = {
        "phase": code(result.get("phase"), {"installing", "installed", "detaching", "detached"}),
        "catalog_status": code(result.get("catalog_status"), {"pending", "synced"}),
        "catalog_degraded": result.get("catalog_degraded") is True,
        "catalog_notices": [v for v in result.get("catalog_notices", []) if isinstance(v, str) and v in {"fallback", "provider-network", "provider-auth"}],
    }
    for key in ("changed", "restart_performed", "native_config_unchanged"):
        public[key] = result.get(key) if type(result.get(key)) is bool else None
    sync = result.get("catalog_diagnostic", {})
    sync = sync if isinstance(sync, dict) else {}
    sync_public = {
        "code": code(sync.get("code"), {"not_attempted", "integration_not_off", "cli_success", "cli_nonzero", "cli_timeout", "cli_output_invalid", "cli_launch_failed"}),
        "exit_code": sync.get("exit_code") if type(sync.get("exit_code")) is int else None,
        "refusal_code": code(sync.get("refusal_code"), {"service-home", "config", "generation", "external-provider", "native-integration-policy", "native-external-provider"}),
    }
    integration_off = None
    try:
        config = read_json(Path(plan["home"]) / "config.json")
        integration_off = config.get("clientIntegrations", {}).get("codex") is False
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    path = Path(plan["codex_home"]) / "opencodex-catalog.json"
    catalog = {"exists": path.is_file(), "read_status": "missing", "model_count": None, "owned_model_count": None, "owned_models": []}
    if catalog["exists"]:
        try:
            rows = read_json(path).get("models")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                catalog["read_status"] = "invalid_models"
            else:
                owned = [row for row in rows if row.get("slug") == "chatgpt-web2api/auto"]
                catalog.update(read_status="ok", model_count=len(rows), owned_model_count=len(owned))
                for row in owned[:10]:
                    modalities = row.get("input_modalities")
                    catalog["owned_models"].append({
                        "slug": "chatgpt-web2api/auto",
                        "display_name": code(row.get("display_name"), {"ChatGPT Web2API"}),
                        "input_modalities": modalities if isinstance(modalities, list) and len(modalities) <= 10 and all(isinstance(v, str) and v in {"text", "image", "audio", "video"} for v in modalities) else "unexpected",
                        "supported_reasoning_levels": [] if row.get("supported_reasoning_levels") == [] else "nonempty_or_invalid",
                    })
        except (ValueError, AttributeError, TypeError):
            catalog["read_status"] = "invalid_json"
        except OSError:
            catalog["read_status"] = "unreadable"
    diagnostic = {"schema": 1, "result": public, "integration_off": integration_off, "sync": sync_public, "catalog": catalog}
    destination = root / "logs/codex-registration-diagnostic.json"
    no_links(destination)
    write_json(destination, diagnostic, root / "backups/diagnostics")
    print("Codex registration diagnostic: " + json.dumps(diagnostic, ensure_ascii=True))
    return diagnostic


def register(root: Path) -> dict:
    import codex_provider

    manifest = validate_root(root)
    root = root.resolve()
    plan = manifest["opencodex"]
    if plan["mode"] == "managed":
        bootstrap_managed(root, manifest)
        start_opencodex(root)
        # Reload the process ownership record written by start_opencodex.
        manifest = read_json(root / "installation.json")
        plan = manifest["opencodex"]
    client = client_for(plan)
    with provider_environment(plan):
        result = codex_provider.install(root, plan["command"], manifest["api_port"], opencodex_home=plan["home"], runner=lambda command, **kwargs: subprocess.run(command, **{**kwargs, "env": client.env}), request=client.request)
    registration_diagnostic(root, plan, result)
    if result.get("catalog_status") != "synced":
        raise RuntimeError("OpenCodex catalog refresh remains pending. See logs/codex-registration-diagnostic.json; retry the installer. No service was restarted.")
    if plan["mode"] == "managed":
        # The provider transaction already refreshes the catalog. A second CLI
        # sync also checks the machine-wide service owner and can reject an
        # otherwise valid isolated side profile. Verify the committed row instead.
        if not codex_provider._catalog_matches(client):
            raise RuntimeError("Managed OpenCodex catalog does not contain the verified Web2API model.")
        merge_codex_route(root, plan)
    plan["registration"] = "installed"
    save_manifest(root, manifest)
    return result


def stop_managed(plan: dict) -> None:
    if plan["mode"] != "managed":
        return
    runtime = read_json(Path(plan["home"]) / "runtime-port.json")
    if not runtime:
        return
    try:
        identity = managed_process(plan, runtime["pid"], allow_missing=True)
    except ValueError:
        # A stale PID must not be turned into permission to stop another process.
        raise ValueError("Managed proxy identity cannot be verified. Stop it manually before uninstalling.") from None
    if not identity:
        return
    client_for(plan)._connect()
    if runtime.get("port") != plan["port"]:
        raise ValueError("Managed OpenCodex runtime port changed.")
    recorded = plan.get("process", {})
    if recorded.get("pid") != identity["ProcessId"] or recorded.get("creation_date") != identity["CreationDate"]:
        raise ValueError("Managed OpenCodex process changed; no process was stopped.")
    pid = identity["ProcessId"]
    creation = str(identity["CreationDate"]).replace("'", "''")
    command = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; if ($p -and $p.CreationDate.ToUniversalTime().ToString('o') -eq '{creation}') {{ Stop-Process -Id {pid} -ErrorAction Stop }} else {{ throw 'Process identity changed' }}"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)


def detach(root: Path) -> dict:
    import codex_provider

    manifest = validate_root(root)
    root = root.resolve()
    plan = manifest["opencodex"]
    client = client_for(plan)
    # Detach owns only journalled provider/model entries; it never starts an external service.
    with provider_environment(plan):
        result = codex_provider.detach(root, plan["command"], opencodex_home=plan["home"], runner=lambda command, **kwargs: subprocess.run(command, **{**kwargs, "env": client.env}), request=client.request)
    if result.get("catalog_status") == "pending":
        raise RuntimeError("OpenCodex catalog detach remains pending; retry before deleting the installation.")
    if plan["mode"] == "managed":
        restore_codex_route(root, plan)
        stop_managed(plan)
    plan["registration"] = "detached"
    save_manifest(root, manifest)
    return result


def check_installation(root: Path) -> dict:
    """Offline, read-only verification; no user configuration or running app needed."""
    manifest = validate_root(root)
    if not manifest:
        raise ValueError("Installation manifest missing.")
    root = root.resolve()
    server = read_json(root / "config.json")
    environment = read_json(root / "environment.json")
    for key in ("browser", "codex", "python"):
        owned_file(root, Path(manifest[key]))
    for relative in ("apps/node/node.exe", "apps/uv/uv.exe", "apps/git/cmd/git.exe", "apps/rg/rg.exe"):
        owned_file(root, root / relative)
    if server.get("host") != "127.0.0.1" or server.get("port") != port(manifest["api_port"]) or server.get("cdp_port") != port(manifest["cdp_port"]) or server.get("user_data_dir") != str(root / "browser-profile"):
        raise ValueError("Bridge configuration does not match its installation.")
    if environment.get("W2A_INSTALL_ROOT") != str(root) or any(key.startswith("CODEX_") or key in ("CONTINUE_GLOBAL_DIR", "PATH") for key in environment):
        raise ValueError("Bridge environment contains an external profile override.")
    return {"ok": True, "installation_target": TARGET, "desktop": manifest["desktop"]["status"], "opencodex": manifest["opencodex"]["mode"], "registration": manifest["opencodex"].get("registration", "pending")}


def examine(root: Path, offline: bool = False) -> dict:
    result = check_installation(root)
    if not offline:
        from urllib.request import ProxyHandler, build_opener

        manifest = read_json(root / "installation.json")
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{manifest['api_port']}/health", timeout=5) as response:
            result["bridge_health"] = json.load(response).get("status")
        # Read-only attestation; no chat/account request, sync, registration or startup.
        client_for(manifest["opencodex"])._connect()
        result["opencodex_attested"] = True
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--desktop-app-id", default="")
    parser.add_argument("--skip-desktop", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--start-opencodex", action="store_true")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--stop-opencodex", action="store_true")
    args = parser.parse_args(argv)
    if args.stop_opencodex:
        manifest = validate_root(args.root)
        stop_managed(manifest["opencodex"])
        result = {"stopped": manifest["opencodex"]["mode"] == "managed"}
    elif args.health:
        result = examine(args.root, offline=False)
    elif args.register:
        result = register(args.root)
    elif args.start_opencodex:
        result = start_opencodex(args.root)
    elif args.detach:
        result = detach(args.root)
    elif args.check:
        result = check_installation(args.root)
    else:
        if args.source is None or args.browser is None:
            parser.error("--source and --browser are required when configuring")
        result = configure(args.root, args.source, args.browser, desktop_app_id=args.desktop_app_id, skip_desktop=args.skip_desktop)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
