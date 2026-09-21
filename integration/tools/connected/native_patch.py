"""Use the installed native Codex patch parser without a model turn."""

import asyncio
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from runtime_paths import codex_executable

HEADERS = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")


def executable():
    return codex_executable()


def validate_paths(patch, root):
    root = Path(root).resolve()
    if not patch.startswith("*** Begin Patch\n") or patch.rstrip()[-13:] != "*** End Patch":
        raise ValueError(
            "Expected a native Codex *** Begin Patch / *** End Patch block with LF newlines"
        )
    paths = []
    for line in patch.splitlines():
        for prefix in HEADERS:
            if not line.startswith(prefix):
                continue
            name = line[len(prefix) :]
            posix = PurePosixPath(name)
            if (
                not name
                or ":" in name
                or "\\" in name
                or "\x00" in name
                or posix.is_absolute()
                or ".." in posix.parts
            ):
                raise ValueError(
                    "Patch paths must be relative POSIX paths inside the opened workspace"
                )
            target = (root / name).resolve()
            if target == root or not target.is_relative_to(root):
                raise ValueError("Patch path resolves outside the opened workspace")
            paths.append(name)
    if not paths:
        raise ValueError("Patch has no file operations")
    return sorted(set(paths))


async def apply_native_patch(patch, root):
    patch = patch.replace("\r\n", "\n")
    paths = validate_paths(patch, root)
    exe = executable()
    # Windows CreateProcess imposes a 32767 UTF-16 character command-line limit.
    # The native entrypoint requires a patch argument, not stdin.
    if len(patch.encode("utf-16-le")) // 2 + len(str(exe)) + patch.count('"') + 100 > 30000:
        raise ValueError(
            "Patch exceeds the Windows command-line limit. Split it into smaller, self-contained patches."
        )
    process = await asyncio.create_subprocess_exec(
        str(exe),
        "--codex-run-as-apply-patch",
        patch,
        cwd=str(Path(root).resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=0x08000000,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return {
            "isError": True,
            "outcome": "uncertain",
            "message": "Patch timed out. Inspect file state before retrying.",
        }
    return {
        "exit_code": process.returncode,
        "isError": process.returncode != 0,
        "output": (stdout + stderr).decode("utf-8", errors="replace")[:20000],
        "paths": paths,
        "workspace": str(Path(root).resolve()),
        "native_codex_parser": True,
        "model_generation_used": False,
    }
