param([string]$InstallRoot = "$env:LOCALAPPDATA\Programs\Web2API-Continue", [string]$CacheDirectory = '', [switch]$NoLaunch, [switch]$NoShortcuts)
$ErrorActionPreference = 'Stop'
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Cette version exige Windows x64.' }
$InstallRoot=[IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot).TrimEnd('\') -or $InstallRoot -eq $env:USERPROFILE) { throw 'Choisir un sous-dossier dedie.' }
$source=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$marker=Join-Path $InstallRoot 'installation.json'
$progressMarker=Join-Path $InstallRoot '.installation-in-progress'
if ((Test-Path -LiteralPath $InstallRoot) -and (Get-ChildItem -LiteralPath $InstallRoot -Force | Select-Object -First 1) -and -not (Test-Path -LiteralPath $marker) -and -not (Test-Path -LiteralPath $progressMarker)) { throw 'Dossier existant non reconnu. Choisir un dossier vide.' }
if ((Test-Path -LiteralPath $marker) -and (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).product -ne 'Web2API-Continue') { throw 'Ce dossier appartient a un autre produit.' }
$digest=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($InstallRoot.ToLowerInvariant()))
$mutex=[Threading.Mutex]::new($false,('Local\Web2API-Setup-'+[BitConverter]::ToString($digest).Replace('-','')))
if (-not $mutex.WaitOne(0)) { throw 'Une installation est deja en cours pour ce dossier.' }
$transcript=$false
try {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'logs') -Force | Out-Null
    Start-Transcript -Path (Join-Path $InstallRoot 'logs\install.log') -Append | Out-Null
    $transcript=$true
    Set-Content -LiteralPath $progressMarker -Value 'Web2API-Continue' -Encoding ASCII
    $dependencies=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies.json') -Raw | ConvertFrom-Json
    if (-not $CacheDirectory) { $CacheDirectory=Join-Path $InstallRoot 'cache' }
    $CacheDirectory=[IO.Path]::GetFullPath($CacheDirectory)
    New-Item -ItemType Directory -Path $CacheDirectory -Force | Out-Null
    . (Join-Path $PSScriptRoot 'Download.ps1')
    $editors=@(Get-CimInstance Win32_Process -Filter "Name = 'Code.exe'" | Where-Object { $_.ExecutablePath -eq (Join-Path $InstallRoot 'apps\vscode\Code.exe') })
    if ($editors.Count) { throw 'Fermer le VS Code de cette installation avant de reparer.' }
    if (Test-Path -LiteralPath (Join-Path $InstallRoot 'Stop.ps1')) { & (Join-Path $InstallRoot 'Stop.ps1') }
    Expand-Verified 'uv' (Join-Path $InstallRoot 'apps\uv') 'uv.exe'
    Expand-Verified 'node' (Join-Path $InstallRoot 'apps\node') 'node.exe' -Flatten
    Expand-Verified 'git' (Join-Path $InstallRoot 'apps\git') 'cmd\git.exe'
    Expand-Verified 'rg' (Join-Path $InstallRoot 'apps\rg') 'rg.exe' -Flatten
    Expand-Verified 'vscode' (Join-Path $InstallRoot 'apps\vscode') 'Code.exe'
    $uv=Join-Path $InstallRoot 'apps\uv\uv.exe'
    $node=Join-Path $InstallRoot 'apps\node\node.exe'
    $npm=Join-Path $InstallRoot 'apps\node\node_modules\npm\bin\npm-cli.js'
    $env:PATH=(Join-Path $InstallRoot 'apps\node')+';'+(Join-Path $InstallRoot 'apps\git\cmd')+';'+$env:PATH
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $InstallRoot 'python'
    $env:UV_PYTHON_BIN_DIR=Join-Path $InstallRoot 'apps\python-bin'
    $env:UV_NO_MODIFY_PATH='1'
    $env:UV_CACHE_DIR=Join-Path $CacheDirectory 'uv'
    $env:PYTHONUTF8='1'
    foreach ($name in @('venv','computer-venv')) {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot "$name\Scripts\python.exe"))) { Invoke-Checked $uv @('venv','--managed-python','--python',$dependencies.python,(Join-Path $InstallRoot $name)) }
    }
    $app=Join-Path $InstallRoot 'app'
    New-Item -ItemType Directory -Path $app -Force | Out-Null
    if ($source -ne $app) {
        foreach ($name in @('src','integration','installer','docs','pyproject.toml','README.md','LICENSE','THIRD_PARTY_NOTICES.md')) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination $app -Recurse -Force }
    }
    $python=Join-Path $InstallRoot 'venv\Scripts\python.exe'
    $computerPython=Join-Path $InstallRoot 'computer-venv\Scripts\python.exe'
    Invoke-Checked $uv @('pip','install','--python',$python,'--require-hashes','-r',(Join-Path $app 'installer\requirements-core.lock'))
    Invoke-Checked $uv @('pip','install','--python',$python,'--no-deps','--no-build-isolation','--reinstall-package','chatgpt-web2api',$app)
    Invoke-Checked $uv @('pip','install','--python',$computerPython,'--require-hashes','-r',(Join-Path $app 'installer\requirements-computer.lock'))
    $tools=Join-Path $InstallRoot 'tools'
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $app 'integration\tools') -Force | Copy-Item -Destination $tools -Recurse -Force
    Invoke-Checked $node @($npm,'ci','--prefix',(Join-Path $tools 'browser'),'--no-audit','--no-fund')
    $npmRoot=Join-Path $InstallRoot 'apps\npm'
    New-Item -ItemType Directory -Path $npmRoot -Force | Out-Null
    Copy-Item -Path (Join-Path $app 'integration\npm\package*.json') -Destination $npmRoot -Force
    Invoke-Checked $node @($npm,'ci','--prefix',$npmRoot,'--no-audit','--no-fund')
    $env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $InstallRoot 'browsers'
    Invoke-Checked $node @((Join-Path $tools 'browser\node_modules\playwright\cli.js'),'install','chromium')
    $browser=Get-ChildItem -LiteralPath $env:PLAYWRIGHT_BROWSERS_PATH -Filter chrome.exe -Recurse | Where-Object { $_.FullName -notlike '*headless*' } | Select-Object -First 1
    if (-not $browser) { throw 'Navigateur Chromium absent.' }
    $extensions=Join-Path $InstallRoot 'extensions'
    $extension=Get-ChildItem -LiteralPath $extensions -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -in @('continue.continue-2.0.0-win32-x64','continue.continue-2.0.0') } | Select-Object -First 1
    if (-not $extension) {
        $vsix=Get-VerifiedDownload 'continue'
        Invoke-Checked (Join-Path $InstallRoot 'apps\vscode\bin\code.cmd') @('--user-data-dir',(Join-Path $InstallRoot 'vscode-data'),'--extensions-dir',$extensions,'--install-extension',$vsix,'--force')
        $extension=Get-ChildItem -LiteralPath $extensions -Directory | Where-Object { $_.Name -in @('continue.continue-2.0.0-win32-x64','continue.continue-2.0.0') } | Select-Object -First 1
    }
    if (-not $extension) { throw 'Extension Continue 2.0.0 absente.' }
    Invoke-Checked $python @((Join-Path $app 'installer\configure.py'),'--root',$InstallRoot,'--source',$app,'--extension',$extension.FullName,'--browser',$browser.FullName)
    foreach ($name in @('Environment.ps1','Start.ps1','Start.cmd','Stop.ps1','Doctor.ps1','Doctor.cmd','Repair.cmd','Connect-Codex.cmd','Uninstall.ps1','Uninstall.cmd')) { Copy-Item -LiteralPath (Join-Path $app ('installer\'+$name)) -Destination $InstallRoot -Force }
    Invoke-Checked $python @((Join-Path $app 'installer\doctor.py'),'--root',$InstallRoot,'--offline')
    if (-not $NoShortcuts) {
        $shell=New-Object -ComObject WScript.Shell
        foreach ($folder in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Startup'))) {
            $shortcut=$shell.CreateShortcut((Join-Path $folder 'Web2API Continue.lnk'))
            $shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $InstallRoot 'Start.ps1')+'"'
            if ($folder -eq [Environment]::GetFolderPath('Startup')) { $shortcut.Arguments+=' -ServiceOnly' }
            $shortcut.WorkingDirectory=$InstallRoot
            $shortcut.IconLocation=(Join-Path $InstallRoot 'apps\vscode\Code.exe')+',0'
            $shortcut.WindowStyle=7
            $shortcut.Save()
        }
    }
    Remove-Item -LiteralPath $progressMarker -Force
    Write-Host "Installation terminee : $InstallRoot"
    Write-Host 'Le premier lancement ouvre ChatGPT : connectez votre propre compte dans ce navigateur.'
    if (-not $NoLaunch) { & (Join-Path $InstallRoot 'Start.ps1') }
} catch {
    Write-Host ('INSTALLATION INTERROMPUE : '+$_.Exception.Message) -ForegroundColor Red
    Write-Host "Relancer le meme installateur pour reprendre. Journal : $InstallRoot\logs\install.log"
    throw
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    $mutex.ReleaseMutex(); $mutex.Dispose()
}
