"""Portable editor profiles must survive direct launches and uninstall."""
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


def test_portable_migration_preserves_user_data_on_uninstall(tmp_path):
    root = tmp_path / "managed with spaces"
    for relative in ["vscode-data", "extensions", "vscode-shared-data"]:
        (root / relative).mkdir(parents=True)
        (root / relative / "old.txt").write_text(relative)
    script = tmp_path / "portable.ps1"
    script.write_text(f"""
$ErrorActionPreference='Stop'
. {q(ROOT / 'installer/Portable.ps1')}
Set-PortableEditor {q(root)}
Set-PortableEditor {q(root)}
Set-Content -LiteralPath {q(root / 'apps/vscode/data/user-data/personal.txt')} -Value 'keep'
Set-Content -LiteralPath {q(root / 'apps/vscode/data/shared-data/personal.txt')} -Value 'shared'
Save-PortableEditorData {q(root)}
""")
    p = run_ps(script)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / "vscode-data/personal.txt").read_text().strip() == "keep"
    assert (root / "vscode-shared-data/personal.txt").read_text().strip() == "shared"
    assert not (root / "apps/vscode/data/user-data").exists()
    assert (root / "vscode-data/old.txt").read_text() == "vscode-data"
    assert (root / "apps/vscode/data/extensions/old.txt").read_text() == "extensions"
    assert (root / "vscode-shared-data/old.txt").read_text() == "vscode-shared-data"
    # Reinstall restores the saved profile into the same portable location.
    script.write_text(f". {q(ROOT / 'installer/Portable.ps1')}\nSet-PortableEditor {q(root)}")
    assert run_ps(script).returncode == 0
    assert (root / "apps/vscode/data/user-data/personal.txt").read_text().strip() == "keep"


def test_portable_refuses_to_merge_two_profiles(tmp_path):
    root = tmp_path / "managed"
    folder = root / "apps/vscode/data/user-data"
    folder.mkdir(parents=True)
    marker = folder / "personal.txt"
    marker.write_text("keep")
    (root / "vscode-data").mkdir()
    script = tmp_path / "portable.ps1"
    script.write_text(f"""
$ErrorActionPreference='Stop'
. {q(ROOT / 'installer/Portable.ps1')}
Set-PortableEditor {q(root)}
""")
    p = run_ps(script)
    assert p.returncode != 0
    assert marker.read_text() == "keep"


def test_managed_resolver_works_without_launcher_in_portable_directory(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = tmp_path / "managed"
    extension = root / "apps/vscode/data/extensions/continue.continue-2.0.0"
    output = extension / "out"
    output.mkdir(parents=True)
    (root / "installation.json").write_text(json.dumps({
        "product": "Web2API-Continue", "root": str(root), "extension": str(extension)
    }))
    (root / "environment.json").write_text(json.dumps({"W2A_API_BASE": "http://127.0.0.1:8080/v1"}))
    script = tmp_path / "portable.ps1"
    script.write_text(f". {q(ROOT / 'installer/Portable.ps1')}\nSet-PortableEditor {q(root)}")
    p = run_ps(script)
    assert p.returncode == 0, p.stdout + p.stderr
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
    linked_output = root / "apps/vscode/data/extensions/continue.continue-2.0.0/out"
    p = subprocess.run([node, str(js), str(ROOT / "integration/continue/web2api-managed-environment.cjs"),
                        str(linked_output)], capture_output=True, text=True, check=True)
    result = json.loads(p.stdout)
    assert Path(result["result"]) == root / "continue"
    assert result["env"] == result["result"]
    assert result["api"] == "http://127.0.0.1:8080/v1"
    assert result["firstPath"] == result["secondPath"]
    assert Path(result["firstPath"].split(os.pathsep)[0]) == root / "apps/node"
    script.write_text(f". {q(ROOT / 'installer/Portable.ps1')}\nSave-PortableEditorData {q(root)}")
    assert run_ps(script).returncode == 0


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
