"""Exercise the actual Windows PowerShell 5.1 installer against local fixtures."""

import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(tmp_path, body, timeout=30):
    script = tmp_path / "progress test.ps1"
    transcript = tmp_path / "transcript.log"
    script.write_text(
        "$ErrorActionPreference='Stop'\n"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
        f". {ps_quote(ROOT / 'installer/Download.ps1')}\n"
        "$script:ProgressIntervalSeconds=0.1\n"
        "$script:HeartbeatSeconds=0.2\n"
        f"Start-Transcript -Path {ps_quote(transcript)} | Out-Null\n"
        "try {\n" + body + "\n} finally { Stop-Transcript | Out-Null }\n",
        encoding="utf-8-sig",
    )
    # Python does not normalize PowerShell 7's module path when spawning 5.1.
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        env=environment,
    )
    return result, transcript


@pytest.fixture
def archive():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as z:
        z.writestr("nested/app.exe", b"fixture" * 8192)
        z.writestr("nested/settings.txt", "settings")
    return content.getvalue()


@pytest.fixture
def server(archive):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append(self.path)
            if self.path == "/retry" and requests.count("/retry") == 1:
                self.send_error(503)
                return
            if self.path == "/headers":
                time.sleep(0.6)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/known")
                self.end_headers()
                return
            content = gzip.compress(archive) if self.path == "/gzip" else archive
            self.send_response(200)
            if self.path != "/unknown":
                self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            for offset in range(0, len(content), 4096):
                self.wfile.write(content[offset:offset + 4096])
                self.wfile.flush()
                if self.path != "/gzip":
                    time.sleep(0.04)

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", requests
    finally:
        http.shutdown()
        http.server_close()
        worker.join()


@pytest.mark.parametrize("route", ["known", "unknown", "gzip", "retry", "redirect", "headers"])
def test_download_progress_integrity_and_cache(tmp_path, server, archive, route):
    url, requests = server
    digest = hashlib.sha256(archive).hexdigest()
    body = f"""
$CacheDirectory={ps_quote(tmp_path)}
$dependencies=@{{downloads=@{{fixture=@{{url='{url}/{route}';file='fixture.zip';version='1';sha256='{digest}'}}}}}}
$first=Get-VerifiedDownload 'fixture'
$second=Get-VerifiedDownload 'fixture'
if ($first -ne $second) {{ throw 'Unexpected output on the success stream' }}
Expand-InstallArchive $first {ps_quote(tmp_path / 'stage with spaces')} 'Fixture'
Copy-InstallTree {ps_quote(tmp_path / 'stage with spaces')} {ps_quote(tmp_path / 'destination')}
"""
    result, transcript = run_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "fixture.zip").read_bytes() == archive
    assert (tmp_path / "destination/nested/settings.txt").read_text() == "settings"
    assert "SHA256 valide" in result.stdout
    assert "Cache valide, telechargement evite" in result.stdout
    assert "Extraction Fixture" in result.stdout
    assert "Copie : 2/2" in result.stdout
    assert "Mio/s" in result.stdout
    assert "SHA256 valide" in transcript.read_text(encoding="utf-8-sig")
    assert len(requests) == (2 if route in {"retry", "redirect"} else 1)
    if route == "unknown":
        assert "taille totale inconnue" in result.stdout
        assert "reste estime" not in result.stdout
    else:
        assert "100" in result.stdout
    if route == "retry":
        assert "Nouvelle tentative" in result.stdout
    if route == "headers":
        assert "attente des en-tetes HTTP" in result.stdout


def test_bad_hash_does_not_publish_cache(tmp_path, server):
    url, _ = server
    result, _ = run_ps(tmp_path, f"""
$CacheDirectory={ps_quote(tmp_path)}
$dependencies=@{{downloads=@{{fixture=@{{url='{url}/known';file='bad.zip';version='1';sha256='invalid'}}}}}}
Get-VerifiedDownload 'fixture'
""")
    assert result.returncode != 0
    assert "SHA256 incorrecte" in result.stderr
    assert not (tmp_path / "bad.zip").exists()


def test_unsafe_archive_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escaped.txt", "must not escape")
    result, _ = run_ps(tmp_path, f"Expand-InstallArchive {ps_quote(archive)} {ps_quote(tmp_path / 'stage')} 'Unsafe'")
    assert result.returncode != 0
    assert not (tmp_path / "escaped.txt").exists()


def test_live_output_heartbeat_quoting_and_failure(tmp_path):
    child = tmp_path / "child with spaces.py"
    child.write_text(
        "import sys, time, json\n"
        "print('EARLY_OUT', flush=True)\n"
        "time.sleep(0.65)\n"
        "for i in range(300):\n"
        " print('OUT'+str(i), flush=True)\n"
        " print('ERR'+str(i), file=sys.stderr, flush=True)\n"
        "print(json.dumps(sys.argv[1:]), flush=True)\n"
        "sys.exit(7)\n"
    )
    arguments = ["with spaces", 'embedded"quote', "slash\\", "", "literal&()$"]
    ps_arguments = ",".join(ps_quote(a) for a in [str(child), *arguments])
    result, transcript = run_ps(tmp_path, f"""
Start-InstallStep 'Fixture'
Invoke-Checked {ps_quote(sys.executable)} @({ps_arguments}) -Label 'Process fixture'
Complete-InstallStep
""")
    assert result.returncode != 0
    assert "EN COURS : Process fixture" in result.stdout
    assert "OUT299" in result.stdout and "ERR299" in result.stdout
    assert json.dumps(arguments) in result.stdout
    assert "Echec (7) : Process fixture" in result.stderr
    assert "OK [1/21]" not in result.stdout
    log = transcript.read_text(encoding="utf-8-sig")
    assert "EARLY_OUT" in log and "EN COURS" in log and "ERR299" in log


def test_batch_launcher_and_step_completion(tmp_path):
    batch = tmp_path / "launcher with spaces.cmd"
    batch.write_text("@echo off\necho BATCH_OK\nexit /b 0\n")
    result, _ = run_ps(tmp_path, f"""
Start-InstallStep 'Fixture'
Invoke-Checked {ps_quote(batch)} @('argument with spaces') -Label 'Batch'
Start-InstallStep 'Suite'
Complete-InstallStep
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BATCH_OK" in result.stdout
    assert "OK [1/21] Fixture" in result.stdout
    assert "ETAPE [2/21] Suite" in result.stdout


def test_installer_scripts_parse_in_powershell_51(tmp_path):
    result, _ = run_ps(tmp_path, f"""
foreach ($file in Get-ChildItem -LiteralPath {ps_quote(ROOT / 'installer')} -Filter '*.ps1') {{
    $parseErrors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$null,[ref]$parseErrors)
    if ($parseErrors) {{ throw ($parseErrors | Out-String) }}
}}
""")
    assert result.returncode == 0, result.stdout + result.stderr
