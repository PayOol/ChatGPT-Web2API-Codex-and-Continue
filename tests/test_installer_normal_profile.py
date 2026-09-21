"""Normal profile binding and archival of the previous portable profile."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")


def run_ps(script):
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(script)], capture_output=True, text=True,
                          errors="replace", env=env, timeout=30)


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def test_launcher_removes_foreign_editor_flags(tmp_path):
    shutil.copy2(ROOT / "installer/Environment.ps1", tmp_path / "Environment.ps1")
    (tmp_path / "environment.json").write_text("{}")
    (tmp_path / "installation.json").write_text("{}")
    script = tmp_path / "run.ps1"
    script.write_text(f"""
$env:ELECTRON_RUN_AS_NODE='1'
$env:VSCODE_PORTABLE='foreign'
$env:VSCODE_IPC_HOOK_CLI='foreign'
. {q(tmp_path / 'Environment.ps1')}
foreach ($key in @('ELECTRON_RUN_AS_NODE','VSCODE_PORTABLE','VSCODE_IPC_HOOK_CLI')) {{
    if (Test-Path ('Env:\\'+$key)) {{ throw "Flag still present: $key" }}
}}
""")
    p = run_ps(script)
    assert p.returncode == 0, p.stdout + p.stderr


def test_only_active_normal_continue_extension_is_selected(tmp_path):
    extensions = tmp_path / "extensions"
    current = extensions / "continue.continue-2.0.0-win32-x64"
    stale = extensions / "continue.continue-2.0.0"
    for folder in (current, stale):
        folder.mkdir(parents=True)
        (folder / "package.json").write_text('{"version":"2.0.0"}')
    (extensions / "extensions.json").write_text(json.dumps([
        {"identifier": {"id": "continue.continue"}, "version": "2.0.0", "relativeLocation": current.name}
    ]))
    script = tmp_path / "run.ps1"
    script.write_text(f". {q(ROOT / 'installer/NormalProfile.ps1')}\n(Find-NormalContinue {q(extensions)}).FullName")
    p = run_ps(script)
    assert p.returncode == 0, p.stdout + p.stderr
    assert Path(p.stdout.strip()) == current


def test_old_portable_profile_is_archived_without_replacing_normal_profile(tmp_path):
    root = tmp_path / "managed with spaces"
    folder = root / "apps/vscode/data/user-data"
    folder.mkdir(parents=True)
    (folder / "personal.txt").write_text("keep")
    script = tmp_path / "archive.ps1"
    script.write_text(f". {q(ROOT / 'installer/NormalProfile.ps1')}\nBackup-LegacyPortableProfile {q(root)}\nBackup-LegacyPortableProfile {q(root)}")
    p = run_ps(script)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (root / "apps/vscode/data").exists()
    backups = list((root / "backups").glob("portable-profile-*"))
    assert len(backups) == 1
    assert (backups[0] / "user-data/personal.txt").read_text() == "keep"


def test_normal_resolver_works_without_launcher(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = tmp_path / "managed"
    root.mkdir()
    continue_dir = tmp_path / "user/.continue"
    extension = tmp_path / "user/.vscode/extensions/continue.continue-2.0.0"
    output = extension / "out"
    output.mkdir(parents=True)
    (root / "installation.json").write_text(json.dumps({
        "product": "Web2API-Continue", "root": str(root), "extension": str(extension), "continue_dir": str(continue_dir)
    }))
    (root / "environment.json").write_text(json.dumps({"W2A_API_BASE": "http://127.0.0.1:8080/v1"}))
    (output / "web2api-installation.json").write_text(json.dumps({"root": str(root)}))
    js = tmp_path / "check.cjs"
    js.write_text("""
const {load} = require(process.argv[2]);
process.env.CONTINUE_GLOBAL_DIR = "wrong-profile";
const result = load(process.argv[3]);
const firstPath = process.env.PATH;
load(process.argv[3]);
console.log(JSON.stringify({result, env:process.env.CONTINUE_GLOBAL_DIR, api:process.env.W2A_API_BASE,
  firstPath, secondPath:process.env.PATH}));
""")
    p = subprocess.run([node, str(js), str(ROOT / "integration/continue/web2api-managed-environment.cjs"),
                        str(output)], capture_output=True, text=True, check=True)
    result = json.loads(p.stdout)
    assert Path(result["result"]) == continue_dir
    assert result["env"] == result["result"]
    assert result["api"] == "http://127.0.0.1:8080/v1"
    assert result["firstPath"] == result["secondPath"]
    assert Path(result["firstPath"].split(os.pathsep)[0]) == root / "apps/node"


def test_managed_resolver_does_not_change_foreign_extension(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    output = tmp_path / "personal/out"
    output.mkdir(parents=True)
    (tmp_path / "installation.json").write_text(json.dumps({
        "product": "Web2API-Continue", "root": str(tmp_path), "extension": str(tmp_path / "managed")
    }))
    script = tmp_path / "check.cjs"
    script.write_text("""
const {load} = require(process.argv[2]);
process.env.CONTINUE_GLOBAL_DIR = "personal-profile";
const result = load(process.argv[3]);
console.log(JSON.stringify({result, env:process.env.CONTINUE_GLOBAL_DIR}));
""")
    p = subprocess.run([node, str(script), str(ROOT / "integration/continue/web2api-managed-environment.cjs"),
                        str(output)], capture_output=True, text=True, check=True)
    assert json.loads(p.stdout) == {"result": None, "env": "personal-profile"}
