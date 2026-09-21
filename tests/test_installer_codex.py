"""Owned Codex installation fixtures; never install software or touch user profiles."""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "installer"))
import configure_codex as setup


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def distribution(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("LOCALAPPDATA", str(user / "AppData/Local"))
    monkeypatch.setenv("APPDATA", str(user / "AppData/Roaming"))
    monkeypatch.setenv("CODEX_HOME", str(user / ".codex"))
    monkeypatch.setenv("OPENCODEX_HOME", str(user / ".opencodex"))
    root = tmp_path / "distribution espaces-é"
    root.mkdir()
    write_json(root / ".installation-in-progress", {"product": setup.PRODUCT, "installation_target": "codex", "root": str(root)})
    for name in (
        "venv/Scripts/python.exe", "apps/node/node.exe", "apps/uv/uv.exe",
        "apps/git/cmd/git.exe", "apps/rg/rg.exe", "browsers/chromium/chrome.exe",
        "apps/npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe",
        "apps/npm/node_modules/@bitkyc08/opencodex/bin/ocx.mjs",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    write_json(root / "apps/npm/node_modules/@bitkyc08/opencodex/package.json", {"version": "2.59.0", "bin": {"ocx": "bin/ocx.mjs"}})
    return root, user, root / "browsers/chromium/chrome.exe"


def configure(distribution, **kwargs):
    root, _, browser = distribution
    return setup.configure(root, SOURCE, browser, **kwargs)


def test_headless_configuration_is_explicit_and_never_claims_desktop_installed(distribution, monkeypatch):
    monkeypatch.delenv("CODEX_HOME")
    manifest = configure(distribution, skip_desktop=True)
    root, user, _ = distribution
    assert manifest["version"] == "0.4.0"
    assert manifest["product"] == "Web2API-Continue"
    assert manifest["installation_target"] == "codex"
    assert manifest["desktop"] == {"status": "skipped", "app_id": ""}
    assert manifest["opencodex"]["mode"] == "managed"
    assert manifest["opencodex"]["codex_home"] == str(root / "codex-profile")
    assert not (user / ".codex").exists()
    assert not any(key in manifest for key in ("extension", "editor", "continue_dir", "vscode_user_data"))
    assert setup.check_installation(root)["ok"]


def test_explicit_codex_home_is_respected_in_headless_installation(distribution):
    manifest = configure(distribution, skip_desktop=True)
    assert manifest["opencodex"]["codex_home"] == os.environ["CODEX_HOME"]


def test_missing_desktop_rejected_before_writing_config(distribution):
    with pytest.raises(ValueError, match="verified OpenAI.Codex"):
        configure(distribution)
    assert not (distribution[0] / "config.json").exists()


def test_existing_opencodex_and_native_tools_are_preserved(distribution):
    root, user, _ = distribution
    native = user / ".codex/config.toml"
    native.parent.mkdir()
    original = b'# unchanged\r\nmodel = "mine"\r\napproval_policy = "on-request"\r\n[mcp_servers.personal]\r\ncommand = "mine"\r\n'
    native.write_bytes(original)
    external = user / ".opencodex/config.json"
    write_json(external, {"providers": {"personal": {"secret": "fixture"}}, "defaultProvider": "personal"})
    before = external.read_bytes()
    manifest = configure(distribution, desktop_app_id="OpenAI.Codex_fixture!App")
    assert manifest["opencodex"]["mode"] == "existing"
    assert manifest["opencodex"]["home"] == str(external.parent)
    assert manifest["desktop"]["status"] == "installed"
    assert native.read_bytes() == original
    assert external.read_bytes() == before
    environment = json.loads((root / "environment.json").read_text(encoding="utf-8"))
    assert not any(k.startswith("CODEX_") or k in ("PATH", "CONTINUE_GLOBAL_DIR", "OPENCODEX_HOME") for k in environment)
    assert environment["W2A_USER_DATA_DIR"] == str(root / "browser-profile")


def test_repair_preserves_ports_mode_and_additional_bridge_settings(distribution, monkeypatch):
    root, user, _ = distribution
    first = configure(distribution, skip_desktop=True)
    server = json.loads((root / "config.json").read_text(encoding="utf-8"))
    server["api_keys"] = ["test-only"]
    write_json(root / "config.json", server)
    write_json(user / ".opencodex/config.json", {"different": True})
    monkeypatch.setattr(setup, "available_port", lambda *_a, **_k: pytest.fail("Repair must retain ports"))
    second = configure(distribution, skip_desktop=True)
    assert (first["api_port"], first["cdp_port"]) == (second["api_port"], second["cdp_port"])
    assert second["opencodex"]["mode"] == "managed"
    assert json.loads((root / "config.json").read_text(encoding="utf-8"))["api_keys"] == ["test-only"]


@pytest.mark.parametrize("target", [None, "continue", "foreign"])
def test_continue_and_foreign_roots_cannot_be_adopted(distribution, target):
    root, _, _ = distribution
    old = {"product": setup.PRODUCT, "root": str(root)}
    if target:
        old["installation_target"] = target
    write_json(root / "installation.json", old)
    before = (root / "installation.json").read_bytes()
    with pytest.raises(ValueError, match="separate"):
        configure(distribution, skip_desktop=True)
    assert (root / "installation.json").read_bytes() == before
    assert not (root / "config.json").exists()


def test_continue_installation_coexists_in_sibling_root(distribution):
    root, _, _ = distribution
    sibling = root.parent / "Web2API-Continue"
    write_json(sibling / "installation.json", {"product": setup.PRODUCT, "api_port": 8080, "cdp_port": 9222})
    before = (sibling / "installation.json").read_bytes()
    manifest = configure(distribution, skip_desktop=True)
    assert manifest["api_port"] != 8080
    assert manifest["cdp_port"] != 9222
    assert (sibling / "installation.json").read_bytes() == before


@pytest.mark.parametrize("kind", ["drive", "user", "source", "inside-source", "programs", "codex-home"])
def test_unsafe_roots_are_rejected(distribution, kind):
    root, user, _ = distribution
    path = {"drive": Path(root.anchor), "user": user, "source": SOURCE, "inside-source": SOURCE / "unsafe-install-test", "programs": user / "AppData/Local/Programs", "codex-home": user / ".codex"}[kind]
    with pytest.raises(ValueError):
        setup.validate_root(path, SOURCE)


def test_unrecognized_progress_and_wrong_root_markers_rejected(distribution):
    root, _, _ = distribution
    write_json(root / ".installation-in-progress", {"product": setup.PRODUCT, "installation_target": "continue", "root": str(root)})
    with pytest.raises(ValueError, match="progress marker"):
        setup.validate_root(root, SOURCE)
    write_json(root / "installation.json", {"product": setup.PRODUCT, "installation_target": "codex", "root": str(root.parent / "other")})
    with pytest.raises(ValueError, match="another root"):
        setup.validate_root(root, SOURCE)


def test_missing_source_and_external_browser_rejected(distribution):
    root, user, browser = distribution
    with pytest.raises(ValueError, match="Incomplete source"):
        setup.configure(root, user, browser, skip_desktop=True)
    foreign = user / "chrome.exe"
    foreign.touch()
    with pytest.raises(ValueError, match="outside"):
        setup.configure(root, SOURCE, foreign, skip_desktop=True)


def test_redirected_managed_path_is_rejected(distribution):
    root, user, _ = distribution
    try:
        (root / "state").symlink_to(user, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    with pytest.raises(ValueError, match="link or junction"):
        configure(distribution, skip_desktop=True)


@pytest.mark.skipif(sys.platform != "win32", reason="uv uses junctions on Windows")
@pytest.mark.parametrize("outside", [False, True])
def test_uv_python_alias_must_target_an_owned_patch_release(distribution, outside):
    root, user, _ = distribution
    python = root / "python"
    python.mkdir()
    target = (user if outside else python) / "cpython-3.14.3-windows-x86_64-none"
    target.mkdir()
    alias = python / "cpython-3.14-windows-x86_64-none"
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path {quote(alias)} -Target {quote(target)} | Out-Null"], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    if outside:
        with pytest.raises(ValueError, match="link or junction"):
            setup.validate_root(root, SOURCE)
    else:
        assert setup.validate_root(root, SOURCE) == {}


def test_managed_bootstrap_disables_all_automatic_native_injection(distribution):
    root, _, _ = distribution
    manifest = configure(distribution, skip_desktop=True)
    setup.bootstrap_managed(root, manifest)
    assert Path(manifest["opencodex"]["codex_home"]).is_dir()
    path = root / "opencodex/config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["hostname"] == "127.0.0.1"
    assert config["defaultProvider"] == "openai"
    assert config["openaiProviderTierVersion"] == 2
    assert set(config["clientIntegrations"].values()) == {False}
    assert config["claudeCode"] == {"enabled": False}
    for key in ("codexAutoStart", "codexShimAutoRestore", "syncResumeHistory", "syncCodexSubagentDefaults", "multiAgentGuidanceEnabled"):
        assert config[key] is False
    before = path.read_bytes()
    setup.bootstrap_managed(root, manifest)
    assert path.read_bytes() == before
    assert manifest["opencodex"]["start_arguments"] == ["start", "--port", str(config["port"])]


def test_existing_start_never_runs_a_command(distribution, monkeypatch):
    root, user, _ = distribution
    write_json(user / ".opencodex/config.json", {"existing": True})
    configure(distribution, skip_desktop=True)
    monkeypatch.setattr(setup.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Existing service must not start"))
    assert setup.start_opencodex(root) == {"mode": "existing", "started": False}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows managed process identity")
@pytest.mark.parametrize("layout", ["nested", "hoisted", "foreign"])
def test_managed_process_identity_accepts_owned_npm_layouts(distribution, monkeypatch, layout):
    root, _, _ = distribution
    plan = configure(distribution, skip_desktop=True)["opencodex"]
    package = Path(plan["package"])
    executable = {
        "nested": package / "node_modules/bun/bin/bun.exe",
        "hoisted": package.parents[1] / "bun/bin/bun.exe",
        "foreign": root.parent / "foreign/bun.exe",
    }[layout]
    process = {"ProcessId": 123, "CreationDate": "fixture", "ExecutablePath": str(executable), "CommandLine": f'"{executable}" "{package / "src/cli/index.ts"}" --ocx-internal-launch-proof=fixture start --port 10101'}
    monkeypatch.setattr(setup.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=json.dumps(process)))
    if layout == "foreign":
        with pytest.raises(ValueError, match="not an owned"):
            setup.managed_process(plan, 123)
    else:
        assert setup.managed_process(plan, 123)["ProcessId"] == 123


def route_fixture(distribution):
    root, _, _ = distribution
    manifest = configure(distribution, skip_desktop=True)
    setup.bootstrap_managed(root, manifest)
    plan = manifest["opencodex"]
    home = Path(plan["codex_home"])
    write_json(home / "opencodex-catalog.json", {"models": []})
    return root, plan, home / "config.toml"


def test_routing_merge_is_narrow_idempotent_and_reversible(distribution):
    root, plan, config = route_fixture(distribution)
    original = b'# personal comment\r\nmodel = "user-default"\r\napproval_policy = "on-request"\r\n\r\n[mcp_servers.mine]\r\ncommand = "personal"\r\n'
    config.write_bytes(original)
    setup.merge_codex_route(root, plan)
    installed = config.read_bytes()
    values = tomllib.loads(installed.decode())
    assert values["openai_base_url"] == f"http://127.0.0.1:{plan['port']}/v1"
    assert values["model"] == "user-default"
    assert values["approval_policy"] == "on-request"
    assert values["mcp_servers"]["mine"]["command"] == "personal"
    setup.merge_codex_route(root, plan)
    assert config.read_bytes() == installed
    with config.open("ab") as stream:
        stream.write(b'added_after_install = true\r\n')
    setup.restore_codex_route(root, plan)
    assert config.read_bytes() == original + b'added_after_install = true\r\n'
    assert not (root / "codex-route-state.json").exists()


@pytest.mark.parametrize("key", ["openai_base_url", "model_catalog_json"])
def test_foreign_routing_is_preserved_and_blocks_install(distribution, key):
    root, plan, config = route_fixture(distribution)
    original = f'{key} = "foreign"\n'.encode()
    config.write_bytes(original)
    with pytest.raises(ValueError, match="already has a route"):
        setup.merge_codex_route(root, plan)
    assert config.read_bytes() == original
    assert not (root / "codex-route-state.json").exists()


def test_user_edited_route_blocks_destructive_cleanup(distribution):
    root, plan, config = route_fixture(distribution)
    setup.merge_codex_route(root, plan)
    edited = config.read_text(encoding="utf-8").replace(f"http://127.0.0.1:{plan['port']}/v1", "http://127.0.0.1:9999/v1")
    config.write_text(edited, encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(ValueError, match="edited by its owner"):
        setup.restore_codex_route(root, plan)
    assert config.read_bytes() == before
    assert (root / "codex-route-state.json").exists()


def test_registration_delegates_without_sync_or_start_for_existing(distribution, monkeypatch):
    import codex_provider

    root, user, _ = distribution
    write_json(user / ".opencodex/config.json", {"existing": True})
    manifest = configure(distribution, skip_desktop=True)
    before = os.environ["CODEX_HOME"]
    observed = []

    def install(*args, **kwargs):
        observed.append((args, kwargs, os.environ["CODEX_HOME"]))
        return {"catalog_status": "synced"}

    monkeypatch.setattr(codex_provider, "install", install)
    monkeypatch.setattr(setup, "client_for", lambda _: SimpleNamespace(env={}, request=lambda *_: None))
    monkeypatch.setattr(setup, "start_opencodex", lambda *_: pytest.fail("Borrowed service must not start"))
    monkeypatch.setattr(setup.subprocess, "run", lambda *_a, **_k: pytest.fail("Existing branch must not call sync"))
    setup.register(root)
    assert observed[0][0][2] == manifest["api_port"]
    assert observed[0][2] == manifest["opencodex"]["codex_home"]
    assert os.environ["CODEX_HOME"] == before
    assert setup.check_installation(root)["registration"] == "installed"


def test_detach_existing_does_not_restore_or_stop_external_apps(distribution, monkeypatch):
    import codex_provider

    root, user, _ = distribution
    write_json(user / ".opencodex/config.json", {"existing": True})
    configure(distribution, skip_desktop=True)
    monkeypatch.setattr(codex_provider, "detach", lambda *_a, **_k: {"catalog_status": "synced"})
    monkeypatch.setattr(setup, "client_for", lambda _: SimpleNamespace(env={}, request=lambda *_: None))
    monkeypatch.setattr(setup, "restore_codex_route", lambda *_: pytest.fail("External Codex config is never changed"))
    monkeypatch.setattr(setup, "stop_managed", lambda *_: pytest.fail("External OpenCodex is never stopped"))
    setup.detach(root)
    assert setup.check_installation(root)["registration"] == "detached"


def test_managed_registration_reuses_verified_catalog_without_duplicate_sync(distribution, monkeypatch):
    import codex_provider

    root, plan, config = route_fixture(distribution)
    write_json(Path(plan["codex_home"]) / "opencodex-catalog.json", {"models": [{"slug": "chatgpt-web2api/auto", "display_name": "ChatGPT Web2API", "input_modalities": ["text", "image"], "supported_reasoning_levels": []}]})
    monkeypatch.setattr(codex_provider, "install", lambda *_a, **_k: {"catalog_status": "synced"})
    monkeypatch.setattr(setup, "client_for", lambda _: SimpleNamespace(env={}, request=lambda *_: None, scope={"codex_home": plan["codex_home"]}))
    monkeypatch.setattr(setup, "start_opencodex", lambda *_: None)
    monkeypatch.setattr(setup.subprocess, "run", lambda *_a, **_k: pytest.fail("The committed catalog needs no extra sync"))
    setup.register(root)
    assert tomllib.loads(config.read_text(encoding="utf-8"))["openai_base_url"] == f"http://127.0.0.1:{plan['port']}/v1"


def test_doctor_detects_config_drift(distribution):
    root, _, _ = distribution
    configure(distribution, skip_desktop=True)
    path = root / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["user_data_dir"] = "foreign-profile"
    write_json(path, config)
    with pytest.raises(ValueError, match="does not match"):
        setup.examine(root, offline=True)


def test_installer_uses_private_dependencies_and_consistent_progress():
    text = (SOURCE / "installer/Setup-Codex.ps1").read_text()
    expected = int(re.search(r"InstallStepCount=(\d+)", text)[1])
    assert len(re.findall(r"^\s*Start-InstallStep ", text, re.M)) == expected
    assert "integration\\codex-npm\\" in text
    assert "requirements-core.lock" in text
    for forbidden in ("requirements-computer", "computer-venv", "--install-extension", "NormalProfile.ps1", "npm install -g"):
        assert forbidden not in text
    assert "9PLM9XGG6VKS" in text and "Get-AppxPackage -Name OpenAI.Codex" in text
    assert "if ($SkipDesktop -and -not $NoLaunch)" in text


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 only")
def test_powershell_files_parse_without_execution():
    files = [SOURCE / "installer" / name for name in ("Setup-Codex.ps1", "Start-Codex.ps1", "Doctor-Codex.ps1")]
    quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in files)
    script = f"$ErrorActionPreference='Stop'; foreach ($f in @({quoted})) {{ $t=$null; $e=$null; [Management.Automation.Language.Parser]::ParseFile($f,[ref]$t,[ref]$e) | Out-Null; if ($e.Count) {{ throw ($e | Out-String) }} }}"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell 5.1 only")
@pytest.mark.parametrize("guard", ["skip-with-launch", "continue-root", "source-root", "bad-progress"])
def test_setup_refuses_invalid_inputs_before_any_install(distribution, guard):
    root, _, _ = distribution
    args = ["-InstallRoot", str(root), "-SkipDesktop"]
    if guard != "skip-with-launch":
        args.append("-NoLaunch")
    if guard == "continue-root":
        write_json(root / "installation.json", {"product": setup.PRODUCT, "root": str(root)})
    elif guard == "source-root":
        args[1] = str(SOURCE)
    elif guard == "bad-progress":
        write_json(root / ".installation-in-progress", {"product": "foreign"})
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SOURCE / "installer/Setup-Codex.ps1"), *args], capture_output=True, timeout=20)
    assert result.returncode != 0
    assert not (root / "logs/install.log").exists()
