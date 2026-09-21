"""Distribution checks: patch transactions, isolation, repair and port ownership."""

import importlib.util
import json
import socket
import sys
from pathlib import Path

import pytest
import yaml

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "installer"))
spec = importlib.util.spec_from_file_location(
    "distribution_configure", SOURCE / "installer/configure.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def extension_fixture(root):
    extension = root / "continue.continue-2.0.0"
    extension.mkdir(parents=True)
    (extension / "package.json").write_text('{"version":"2.0.0"}')
    targets = {}
    for name in [
        "continue-full-access-changes.json",
        "continue-auto-compaction-changes.json",
        "continue-long-wait-changes.json",
        "continue-managed-profile-changes.json",
    ]:
        for change in json.loads((SOURCE / "integration/continue" / name).read_text(encoding="utf-8")):
            targets.setdefault(change["file"], []).append(change["before"])
    for name, chunks in targets.items():
        path = extension / Path(name.replace("\\", "/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(chunks), encoding="utf-8")
    return extension


def test_patch_is_idempotent_and_preserves_backup(tmp_path):
    extension = extension_fixture(tmp_path)
    first = setup.apply_continue_patches(extension, SOURCE, tmp_path / "backups")
    second = setup.apply_continue_patches(extension, SOURCE, tmp_path / "backups")
    assert first == second
    assert len(list((tmp_path / "backups").iterdir())) == 2


def test_unknown_bundle_is_rejected_before_any_write(tmp_path):
    extension = extension_fixture(tmp_path)
    (extension / "gui/assets/index.js").write_text("unsupported version")
    original = (extension / "out/extension.js").read_bytes()
    with pytest.raises(RuntimeError, match="Unsupported Continue bundle"):
        setup.apply_continue_patches(extension, SOURCE, tmp_path / "backups")
    assert (extension / "out/extension.js").read_bytes() == original
    assert not (tmp_path / "backups").exists()


def test_repair_preserves_ports_user_models_and_normal_settings(tmp_path, monkeypatch):
    root = tmp_path / "installation with spaces"
    root.mkdir()
    user = tmp_path / "utilisateur-é"
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("APPDATA", str(user / "AppData/Roaming"))
    extension = extension_fixture(user / ".vscode/extensions")
    editor = tmp_path / "VS Code/Code.exe"
    editor.parent.mkdir()
    editor.touch()
    settings = user / "AppData/Roaming/Code/User/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('// personal comment\n{"editor.fontSize": 19,}\n')
    before_settings = settings.read_bytes()
    codex = root / "apps/npm/node_modules/@openai/codex/vendor/x86_64/codex.exe"
    codex.parent.mkdir(parents=True)
    codex.touch()
    browser = root / "browsers/chrome.exe"
    browser.parent.mkdir()
    browser.touch()
    external = tmp_path / "normal-profile"
    external.mkdir()
    (external / "config.yaml").write_text("personal marker")
    monkeypatch.setenv("CONTINUE_GLOBAL_DIR", str(external))
    first = setup.configure(root, SOURCE, extension, browser, editor)
    path = user / ".continue/config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["models"].append({"name": "Personal model", "provider": "openai", "model": "test"})
    path.write_text(yaml.safe_dump(config))
    second = setup.configure(root, SOURCE, extension, browser, editor)
    assert first["api_port"] == second["api_port"]
    assert first["cdp_port"] == second["cdp_port"]
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert settings.read_bytes() == before_settings
    assert second["editor"] == str(editor)
    assert second["profile_mode"] == "normal"
    assert len(config["models"]) == 2
    assert config["models"][0]["requestOptions"]["timeout"] == 0
    assert len(config["mcpServers"]) == 5
    assert (external / "config.yaml").read_text(encoding="utf-8") == "personal marker"
    assert (root / "BIENVENUE.md").is_file()
    assert config["mcpServers"][0]["env"]["CONTINUE_GLOBAL_DIR"] == str(user / ".continue")
    from chatgpt_web2api.config import Config

    actual = Config.load(str(root / "config.json"))
    assert actual.server.port == first["api_port"]
    assert actual.server.request_timeout == 0
    assert actual.chatgpt.detector_hard_timeout_seconds == 0
    assert actual.chatgpt.detector_default_first_content_timeout_seconds == 0
    assert actual.server.request_timeout == 0
    assert actual.chatgpt.detector_hard_timeout_seconds == 0
    assert actual.chatgpt.detector_default_first_content_timeout_seconds == 0
    assert actual.chrome.user_data_dir == str(root / "browser-profile")

    config["models"].append({"name": "Added after install", "provider": "openai", "model": "test"})
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    setup.normal_profile.detach(root)
    restored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [m["name"] for m in restored["models"]] == ["Personal model", "Added after install"]
    assert restored["mcpServers"] == []
    assert not (extension / "out/web2api-installation.json").exists()
    assert settings.read_bytes() == before_settings


def test_external_extension_is_never_patched(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    extension = extension_fixture(tmp_path / "foreign")
    with pytest.raises(ValueError, match="normal user extension"):
        setup.configure(tmp_path / "owned", SOURCE, extension, tmp_path / "chrome.exe", tmp_path / "Code.exe")


def test_occupied_port_is_preserved_for_its_owner():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        if port > 65400:
            pytest.skip("Ephemeral port too close to range limit")
        chosen = setup.available_port(port)
        assert chosen != port
        assert occupied.getsockname()[1] == port
