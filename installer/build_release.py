"""Build the source archive and one-file Windows installer from this Git checkout."""

from pathlib import Path
import argparse
import hashlib
import os
import subprocess
import tempfile
import zipfile


def build(root: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    files = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
        )
        .decode()
        .split("\0")
    )
    source = output / "ChatGPT-Web2API-Continue-0.4.0-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(set(files)):
            if not name or not (root / name).is_file():
                continue
            parts = Path(name).parts
            if any(
                p
                in {
                    ".git",
                    "node_modules",
                    "__pycache__",
                    ".venv",
                    "dist",
                    "build",
                    ".pytest_cache",
                }
                for p in parts
            ):
                continue
            if Path(name).suffix in {".pyc", ".exe", ".vsix"}:
                continue
            archive.write(root / name, name)
    with tempfile.TemporaryDirectory(prefix="web2api-build-") as temporary:
        code = Path(temporary) / "Bootstrap.cs"
        code.write_text(
            (root / "installer/Bootstrap.cs")
            .read_text()
            .replace("__PAYLOAD_SHA256__", hashlib.sha256(source.read_bytes()).hexdigest()),
            encoding="utf-8",
        )
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        target = output / "Web2API-Continue-Setup-0.4.0.exe"
        subprocess.run(
            [
                str(compiler),
                "/nologo",
                "/target:exe",
                "/platform:x64",
                "/optimize+",
                "/reference:System.IO.Compression.dll",
                "/reference:System.IO.Compression.FileSystem.dll",
                f"/resource:{source},payload.zip",
                f"/out:{target}",
                str(code),
            ],
            check=True,
        )
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in [source, target]
        ),
        encoding="ascii",
    )
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.output.resolve())
