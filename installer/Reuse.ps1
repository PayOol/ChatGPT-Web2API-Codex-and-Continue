$ErrorActionPreference='Stop'

function Get-CompatibleSiblingInstallation([string]$Root,[ValidateSet('codex','continue')][string]$CurrentTarget) {
    $rootFull=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $otherTarget=if ($CurrentTarget -eq 'codex') { 'continue' } else { 'codex' }
    $otherFolder=if ($otherTarget -eq 'codex') { 'Web2API-Codex' } else { 'Web2API-Continue' }
    $candidates=@(
        (Join-Path (Split-Path $rootFull -Parent) $otherFolder),
        (Join-Path $env:LOCALAPPDATA ('Programs\'+$otherFolder))
    )
    foreach ($candidateValue in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidateValue)) { continue }
        $candidate=[IO.Path]::GetFullPath($candidateValue).TrimEnd('\')
        if ($candidate -eq $rootFull -or -not (Test-Path -LiteralPath $candidate -PathType Container)) { continue }
        if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        $marker=Join-Path $candidate 'installation.json'
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { continue }
        try { $manifest=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json } catch { continue }
        if ($manifest.product -ne 'Web2API-Continue' -or $manifest.installation_target -ne $otherTarget -or -not $manifest.root) { continue }
        try { $recorded=[IO.Path]::GetFullPath([string]$manifest.root).TrimEnd('\') } catch { continue }
        if ($recorded -eq $candidate) { return $candidate }
    }
    return $null
}

function Get-ReusableUvCache([string]$OwnCache,[string]$SiblingRoot,[bool]$ExplicitCache) {
    $own=[IO.Path]::GetFullPath($OwnCache)
    if ($ExplicitCache -or [string]::IsNullOrWhiteSpace($SiblingRoot)) { return $own }
    $candidate=Join-Path $SiblingRoot 'cache\uv'
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { return $own }
    if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $own }
    Write-InstallStatus ('Cache Python commun verifie et reutilise : '+$candidate)
    return $candidate
}

function Test-PythonRequirements([string]$Python,[string]$Requirements) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or -not (Test-Path -LiteralPath $Requirements -PathType Leaf)) { return $false }
    $checker=@'
import importlib.metadata as metadata
import pathlib
import re
import sys

def normalize(value):
    return re.sub(r"[-_.]+", "-", value).lower()

expected = {}
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
    if match:
        expected[normalize(match.group(1))] = match.group(2)
if not expected:
    raise SystemExit(2)
installed = {}
for distribution in metadata.distributions():
    name = distribution.metadata.get("Name")
    if name:
        installed[normalize(name)] = distribution.version
raise SystemExit(0 if all(installed.get(name) == version for name, version in expected.items()) else 1)
'@
    $temporary=[IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(),'.py')
    $previousPreference=$ErrorActionPreference
    try {
        Set-Content -LiteralPath $temporary -Value $checker -Encoding UTF8
        $ErrorActionPreference='Continue'
        & $Python $temporary $Requirements 2>$null | Out-Null
        $exitCode=$LASTEXITCODE
    } finally {
        $ErrorActionPreference=$previousPreference
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    return $exitCode -eq 0
}

function Install-PythonRequirements([string]$Uv,[string]$Python,[string]$Requirements,[string]$ReceiptName,[string]$Label) {
    $digest=(Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash.ToLowerInvariant()
    $environment=Split-Path (Split-Path $Python -Parent) -Parent
    $receipt=Join-Path $environment $ReceiptName
    if (Test-PythonRequirements $Python $Requirements) {
        $known=(Test-Path -LiteralPath $receipt -PathType Leaf) -and ((Get-Content -LiteralPath $receipt -Raw).Trim() -eq $digest)
        if ($known) { Write-InstallStatus ('Dependances Python deja conformes, installation ignoree : '+$Label) }
        else { Write-InstallStatus ('Dependances Python existantes verifiees et adoptees : '+$Label) }
        Set-Content -LiteralPath $receipt -Value $digest -Encoding ASCII
        return
    }
    Invoke-Checked $Uv @('pip','install','--python',$Python,'--require-hashes','-r',$Requirements) -Label $Label
    if (-not (Test-PythonRequirements $Python $Requirements)) { throw ('Verification des dependances Python impossible apres installation : '+$Label) }
    Set-Content -LiteralPath $receipt -Value $digest -Encoding ASCII
}

function Test-NpmInstall([string]$Node,[string]$Prefix,[string[]]$RequiredFiles) {
    $wanted=Join-Path $Prefix 'package-lock.json'
    $actual=Join-Path $Prefix 'node_modules\.package-lock.json'
    if (-not (Test-Path -LiteralPath $Node -PathType Leaf) -or -not (Test-Path -LiteralPath $wanted -PathType Leaf) -or -not (Test-Path -LiteralPath $actual -PathType Leaf)) { return $false }
    foreach ($relative in $RequiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Prefix $relative) -PathType Leaf)) { return $false }
    }
    $checker=@'
const fs = require("fs");
const wanted = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const actual = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const allows = (list, value) => !Array.isArray(list) ||
  (!list.includes("!" + value) && (list.every(item => item.startsWith("!")) || list.includes(value)));
const expected = Object.entries(wanted.packages || {}).filter(([name, value]) =>
  name && allows(value.os, "win32") && allows(value.cpu, "x64"));
const installed = Object.entries(actual.packages || {}).filter(([name]) => name);
if (expected.length !== installed.length) process.exit(1);
for (const [name, value] of expected) {
  const found = actual.packages[name];
  if (!found || found.version !== value.version ||
      (value.integrity && found.integrity !== value.integrity)) process.exit(1);
}
'@
    $temporary=[IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(),'.cjs')
    $previousPreference=$ErrorActionPreference
    try {
        Set-Content -LiteralPath $temporary -Value $checker -Encoding UTF8
        $ErrorActionPreference='Continue'
        & $Node $temporary $wanted $actual 2>$null | Out-Null
        $exitCode=$LASTEXITCODE
    } finally {
        $ErrorActionPreference=$previousPreference
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
    return $exitCode -eq 0
}

function Install-NpmDependencies([string]$Node,[string]$Npm,[string]$Prefix,[string[]]$RequiredFiles,[string]$Label) {
    $lock=Join-Path $Prefix 'package-lock.json'
    $digest=(Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt=Join-Path $Prefix '.web2api-npm-lock-sha256'
    if (Test-NpmInstall $Node $Prefix $RequiredFiles) {
        $known=(Test-Path -LiteralPath $receipt -PathType Leaf) -and ((Get-Content -LiteralPath $receipt -Raw).Trim() -eq $digest)
        if ($known) { Write-InstallStatus ('Dependances npm deja conformes, installation ignoree : '+$Label) }
        else { Write-InstallStatus ('Dependances npm existantes verifiees et adoptees : '+$Label) }
        Set-Content -LiteralPath $receipt -Value $digest -Encoding ASCII
        return
    }
    Invoke-Checked $Node @($Npm,'ci','--prefix',$Prefix,'--no-audit','--no-fund','--loglevel=info') -Label $Label
    if (-not (Test-NpmInstall $Node $Prefix $RequiredFiles)) { throw ('Verification des dependances npm impossible apres installation : '+$Label) }
    Set-Content -LiteralPath $receipt -Value $digest -Encoding ASCII
}

function Copy-CompatiblePlaywrightBrowsers([string]$PackageRoot,[string]$BrowsersRoot,[string]$SiblingPackageRoot,[string]$SiblingBrowsersRoot) {
    if ([string]::IsNullOrWhiteSpace($SiblingPackageRoot) -or [string]::IsNullOrWhiteSpace($SiblingBrowsersRoot)) { return $false }
    $descriptor=Join-Path $PackageRoot 'node_modules\playwright-core\browsers.json'
    $siblingDescriptor=Join-Path $SiblingPackageRoot 'node_modules\playwright-core\browsers.json'
    if (-not (Test-Path -LiteralPath $descriptor -PathType Leaf) -or -not (Test-Path -LiteralPath $siblingDescriptor -PathType Leaf) -or -not (Test-Path -LiteralPath $SiblingBrowsersRoot -PathType Container)) { return $false }
    if ((Get-Item -LiteralPath $SiblingBrowsersRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
    if ((Get-FileHash -LiteralPath $descriptor -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $siblingDescriptor -Algorithm SHA256).Hash) { return $false }
    $siblingBrowser=Get-ChildItem -LiteralPath $SiblingBrowsersRoot -Filter chrome.exe -File -Recurse | Where-Object { $_.FullName -notlike '*headless*' } | Select-Object -First 1
    if (-not $siblingBrowser) { return $false }
    Write-InstallStatus ('Chromium Playwright compatible trouve dans l''autre cible : '+$SiblingBrowsersRoot)
    New-Item -ItemType Directory -Path $BrowsersRoot -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $SiblingBrowsersRoot -Force) {
        if ($item.Name -eq '.links') { continue }
        if ($item.PSIsContainer) { Copy-InstallTree $item.FullName (Join-Path $BrowsersRoot $item.Name) }
        else { Copy-Item -LiteralPath $item.FullName -Destination $BrowsersRoot -Force }
    }
    Write-InstallStatus 'Chromium commun copie localement ; les deux installations restent desinstallables separement.'
    return $true
}

function Install-PlaywrightChromium([string]$Node,[string]$Cli,[string]$PackageRoot,[string]$BrowsersRoot,[string]$SiblingPackageRoot,[string]$SiblingBrowsersRoot,[string]$Label) {
    $descriptor=Join-Path $PackageRoot 'node_modules\playwright-core\browsers.json'
    if (-not (Test-Path -LiteralPath $descriptor -PathType Leaf)) { throw 'Descripteur Playwright absent.' }
    $digest=(Get-FileHash -LiteralPath $descriptor -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt=Join-Path $BrowsersRoot '.web2api-playwright-sha256'
    $browser=Get-ChildItem -LiteralPath $BrowsersRoot -Filter chrome.exe -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike '*headless*' } | Select-Object -First 1
    if ($browser -and (Test-Path -LiteralPath $receipt -PathType Leaf) -and ((Get-Content -LiteralPath $receipt -Raw).Trim() -eq $digest)) {
        Write-InstallStatus 'Navigateur Chromium deja conforme, installation ignoree.'
        return $browser
    }
    if (-not $browser) {
        [void](Copy-CompatiblePlaywrightBrowsers $PackageRoot $BrowsersRoot $SiblingPackageRoot $SiblingBrowsersRoot)
    }
    $env:PLAYWRIGHT_BROWSERS_PATH=$BrowsersRoot
    Invoke-Checked $Node @($Cli,'install','chromium') -Label $Label
    $browser=Get-ChildItem -LiteralPath $BrowsersRoot -Filter chrome.exe -File -Recurse | Where-Object { $_.FullName -notlike '*headless*' } | Select-Object -First 1
    if (-not $browser) { throw 'Navigateur Chromium absent.' }
    Set-Content -LiteralPath $receipt -Value $digest -Encoding ASCII
    return $browser
}
