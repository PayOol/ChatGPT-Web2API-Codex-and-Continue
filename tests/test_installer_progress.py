"""Exercise the actual Windows PowerShell 5.1 installer against local fixtures."""

import gzip
import hashlib
import io
import json
import os
import shutil
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


def run_reuse_ps(tmp_path, body, timeout=30):
    script = tmp_path / "reuse test.ps1"
    script.write_text(
        "$ErrorActionPreference='Stop'\n"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"
        f". {ps_quote(ROOT / 'installer/Progress.ps1')}\n"
        f". {ps_quote(ROOT / 'installer/Reuse.ps1')}\n"
        + body,
        encoding="utf-8-sig",
    )
    environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script)], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, env=environment,
    )


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


def test_verified_archive_is_reused_from_sibling_without_network(tmp_path, archive):
    own = tmp_path / "Web2API-Continue"
    sibling = tmp_path / "Web2API-Codex"
    own.mkdir()
    (sibling / "cache").mkdir(parents=True)
    cached = sibling / "cache/fixture.zip"
    cached.write_bytes(archive)
    digest = hashlib.sha256(archive).hexdigest()
    body = f"""
$InstallRoot={ps_quote(own)}
$CacheDirectory={ps_quote(own / 'cache')}
New-Item -ItemType Directory -Path $CacheDirectory | Out-Null
$script:SiblingInstallRoot={ps_quote(sibling)}
$dependencies=@{{downloads=@{{fixture=@{{url='http://127.0.0.1:1/must-not-run';file='fixture.zip';version='1';sha256='{digest}'}}}}}}
$file=Get-VerifiedDownload 'fixture'
if ($file -ne {ps_quote(cached)}) {{ throw 'Sibling archive was not selected' }}
"""
    result, _ = run_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "de l'autre cible" in result.stdout
    assert "telechargement evite" in result.stdout


def test_sibling_installation_requires_exact_owned_manifest(tmp_path):
    current = tmp_path / "Web2API-Continue"
    sibling = tmp_path / "Web2API-Codex"
    current.mkdir()
    sibling.mkdir()
    valid = {"product": "Web2API-Continue", "installation_target": "codex", "root": str(sibling)}
    (sibling / "installation.json").write_text(json.dumps(valid))
    isolated_local = tmp_path / "isolated-local"
    body = f"""
$env:LOCALAPPDATA={ps_quote(isolated_local)}
$found=Get-CompatibleSiblingInstallation {ps_quote(current)} 'continue'
if ($found -ne {ps_quote(sibling)}) {{ throw 'Valid sibling was not found' }}
"""
    result = run_reuse_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    valid["root"] = str(tmp_path / "foreign")
    (sibling / "installation.json").write_text(json.dumps(valid))
    result = run_reuse_ps(tmp_path, f"$env:LOCALAPPDATA={ps_quote(isolated_local)}\nif ($null -ne (Get-CompatibleSiblingInstallation {ps_quote(current)} 'continue')) {{ throw 'Foreign marker accepted' }}")
    assert result.returncode == 0, result.stdout + result.stderr


def test_python_requirements_are_skipped_only_after_live_verification(tmp_path):
    requirements = tmp_path / "requirements.lock"
    requirements.write_text("pip==" + subprocess.check_output(
        [sys.executable, "-c", "import importlib.metadata as m;print(m.version('pip'))"], text=True
    ).strip() + "\n")
    result = run_reuse_ps(tmp_path, f"if (-not (Test-PythonRequirements {ps_quote(sys.executable)} {ps_quote(requirements)})) {{ throw 'Installed package rejected' }}")
    assert result.returncode == 0, result.stdout + result.stderr
    requirements.write_text("pip==0.0.invalid\n")
    result = run_reuse_ps(tmp_path, f"if (Test-PythonRequirements {ps_quote(sys.executable)} {ps_quote(requirements)}) {{ throw 'Version drift accepted' }}")
    assert result.returncode == 0, result.stdout + result.stderr


def test_python_requirement_install_step_adopts_then_skips_verified_environment(tmp_path):
    requirements = tmp_path / "requirements.lock"
    requirements.write_text("pip==" + subprocess.check_output(
        [sys.executable, "-c", "import importlib.metadata as m;print(m.version('pip'))"], text=True
    ).strip() + "\n")
    environment = tmp_path / "venv"
    scripts = environment / "Scripts"
    scripts.mkdir(parents=True)
    python = scripts / "python.cmd"
    python.write_text(f'@echo off\n"{sys.executable}" %*\n')
    receipt = environment / ".web2api-test-requirements-sha256"
    body = f"""
Install-PythonRequirements 'missing-uv.exe' {ps_quote(python)} {ps_quote(requirements)} '.web2api-test-requirements-sha256' 'Fixture Python'
Install-PythonRequirements 'missing-uv.exe' {ps_quote(python)} {ps_quote(requirements)} '.web2api-test-requirements-sha256' 'Fixture Python'
"""
    result = run_reuse_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "existantes verifiees et adoptees" in result.stdout
    assert "deja conformes, installation ignoree" in result.stdout
    assert receipt.read_text().strip() == hashlib.sha256(requirements.read_bytes()).hexdigest()


def test_npm_install_is_skipped_only_for_complete_matching_lock(tmp_path):
    prefix = tmp_path / "npm"
    (prefix / "node_modules/pkg").mkdir(parents=True)
    wanted = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/pkg": {"version": "1.2.3", "integrity": "sha512-fixture"}}}
    actual = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/pkg": {"version": "1.2.3", "integrity": "sha512-fixture"}}}
    (prefix / "package-lock.json").write_text(json.dumps(wanted))
    (prefix / "node_modules/.package-lock.json").write_text(json.dumps(actual))
    required = prefix / "node_modules/pkg/index.js"
    required.write_text("ok")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    body = f"if (-not (Test-NpmInstall {ps_quote(node)} {ps_quote(prefix)} @('node_modules\\pkg\\index.js'))) {{ throw 'Matching lock rejected' }}"
    result = run_reuse_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    actual["packages"]["node_modules/pkg"]["version"] = "9.9.9"
    (prefix / "node_modules/.package-lock.json").write_text(json.dumps(actual))
    result = run_reuse_ps(tmp_path, f"if (Test-NpmInstall {ps_quote(node)} {ps_quote(prefix)} @('node_modules\\pkg\\index.js')) {{ throw 'Drift accepted' }}")
    assert result.returncode == 0, result.stdout + result.stderr


def test_npm_install_step_adopts_then_skips_matching_lock(tmp_path):
    prefix = tmp_path / "npm"
    (prefix / "node_modules/pkg").mkdir(parents=True)
    lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/pkg": {"version": "1.2.3"}}}
    (prefix / "package-lock.json").write_text(json.dumps(lock))
    (prefix / "node_modules/.package-lock.json").write_text(json.dumps(lock))
    (prefix / "node_modules/pkg/index.js").write_text("ok")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    body = f"""
Install-NpmDependencies {ps_quote(node)} 'missing-npm.js' {ps_quote(prefix)} @('node_modules\\pkg\\index.js') 'Fixture npm'
Install-NpmDependencies {ps_quote(node)} 'missing-npm.js' {ps_quote(prefix)} @('node_modules\\pkg\\index.js') 'Fixture npm'
"""
    result = run_reuse_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "existantes verifiees et adoptees" in result.stdout
    assert "deja conformes, installation ignoree" in result.stdout
    receipt = prefix / ".web2api-npm-lock-sha256"
    assert receipt.read_text().strip() == hashlib.sha256((prefix / "package-lock.json").read_bytes()).hexdigest()


def test_compatible_playwright_browser_is_copied_only_for_same_descriptor(tmp_path):
    package = tmp_path / "current-package"
    sibling_package = tmp_path / "sibling-package"
    browsers = tmp_path / "current-browsers"
    sibling_browsers = tmp_path / "sibling-browsers"
    for folder in (package, sibling_package):
        (folder / "node_modules/playwright-core").mkdir(parents=True)
        (folder / "node_modules/playwright-core/browsers.json").write_text('{"browsers":[{"name":"chromium","revision":"7"}]}')
    chrome = sibling_browsers / "chromium-7/chrome-win/chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"browser")
    body = f"""
if (-not (Copy-CompatiblePlaywrightBrowsers {ps_quote(package)} {ps_quote(browsers)} {ps_quote(sibling_package)} {ps_quote(sibling_browsers)})) {{ throw 'Compatible browser rejected' }}
if (-not (Test-Path -LiteralPath {ps_quote(browsers / 'chromium-7/chrome-win/chrome.exe')})) {{ throw 'Browser was not copied' }}
"""
    result = run_reuse_ps(tmp_path, body)
    assert result.returncode == 0, result.stdout + result.stderr
    shutil.rmtree(browsers)
    (sibling_package / "node_modules/playwright-core/browsers.json").write_text('{"browsers":[{"name":"chromium","revision":"8"}]}')
    result = run_reuse_ps(tmp_path, f"if (Copy-CompatiblePlaywrightBrowsers {ps_quote(package)} {ps_quote(browsers)} {ps_quote(sibling_package)} {ps_quote(sibling_browsers)}) {{ throw 'Mismatched browser accepted' }}")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not browsers.exists()


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
