"""Run the installed editor's extension tests, without the managed launcher."""

import argparse
import os
import subprocess
from pathlib import Path


def main(root: Path):
    # Deliberately strip everything that the launcher normally supplies.
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("W2A_", "CONTINUE_", "VSCODE_"))
        and key.upper() not in {"ELECTRON_RUN_AS_NODE", "PLAYWRIGHT_BROWSERS_PATH"}
    }
    env.update(NODE_ENV="test", WEB2API_EDITOR_TEST_ROOT=str(root.resolve()))
    fixture = Path(__file__).parent / "editor-runtime"
    subprocess.run([
        str(root / "apps/vscode/Code.exe"),
        "--skip-welcome", "--skip-release-notes", "--new-window",
        f"--extensionDevelopmentPath={fixture}",
        f"--extensionTestsPath={fixture / 'test.cjs'}",
    ], env=env, check=True, timeout=240)
    print((root / "logs/editor-runtime.json").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    main(parser.parse_args().root)
