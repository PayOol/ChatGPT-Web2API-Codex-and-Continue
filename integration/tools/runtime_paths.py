"""Resolve executables without assuming a username or global npm path."""

import os
import shutil
from pathlib import Path


def node_executable():
    candidate = os.environ.get("W2A_NODE") or shutil.which("node")
    if not candidate or not Path(candidate).is_file():
        raise RuntimeError("Node.js missing. Run Repair.cmd from the Web2API installation.")
    return candidate


def codex_executable():
    explicit = os.environ.get("W2A_CODEX_BINARY")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    roots = []
    if os.environ.get("W2A_INSTALL_ROOT"):
        roots.append(Path(os.environ["W2A_INSTALL_ROOT"]) / "apps/npm/node_modules/@openai")
    roots.append(
        Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
        / "npm/node_modules/@openai"
    )
    for root in roots:
        for candidate in sorted(root.rglob("codex.exe" if os.name == "nt" else "codex")):
            if candidate.is_file() and ("x86_64" in str(candidate) or os.name != "nt"):
                return candidate
    direct = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if direct:
        return Path(direct)
    raise RuntimeError("Codex executable missing. Run Repair.cmd to install the pinned version.")
