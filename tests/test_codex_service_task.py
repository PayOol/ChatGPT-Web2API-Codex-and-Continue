"""Windows Task Scheduler ownership contract for the Codex bridge supervisor."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler only")
def test_service_task_is_owned_idempotent_and_removable(tmp_path):
    root = tmp_path / "Web2API Codex supervised"
    root.mkdir()
    for name in ("Service-Codex.ps1", "ServiceTask-Codex.ps1"):
        shutil.copy2(SOURCE / "installer" / name, root / name)
    (root / "installation.json").write_text(
        json.dumps(
            {
                "product": "Web2API-Continue",
                "version": "test",
                "installation_target": "codex",
                "root": str(root),
            }
        ),
        encoding="utf-8",
    )
    helper = root / "ServiceTask-Codex.ps1"

    def run(action, *, check=True):
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-Action",
                action,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=check,
        )

    try:
        run("Install")
        installed = json.loads(run("Status").stdout)
        assert installed["owned"] is True and installed["state"] == "Ready"
        assert installed["task_name"].startswith("Web2API-Codex-")
        run("Stop")
        assert (root / "state" / "service-stop.requested").read_text().strip() == "stop"
        run("Install")
        assert json.loads(run("Status").stdout)["task_name"] == installed["task_name"]
        assert not (root / "state" / "service-stop.requested").exists()
        run("Remove")
        removed = json.loads(run("Status").stdout)
        assert removed["owned"] is False and removed["state"] == "Missing"
        assert not (root / "service-task.json").exists()
    finally:
        if (root / "service-task.json").exists():
            run("Remove", check=False)
