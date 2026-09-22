param([string]$InstallRoot="$env:LOCALAPPDATA\Programs\Web2API-Codex",[string]$CacheDirectory='',
    [switch]$NoLaunch,[switch]$NoShortcuts,[switch]$SkipDesktop)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
if ($SkipDesktop -and -not $NoLaunch) { throw '-SkipDesktop exige -NoLaunch (CI/test explicite).' }
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Cette version exige Windows x64.' }
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$InstallRoot=[IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$source=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')

function Assert-NoRedirect([string]$Path) {
    $item=[IO.Path]::GetFullPath($Path)
    while ($item) {
        if (Test-Path -LiteralPath $item) {
            if ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw ('Chemin redirige interdit : '+$item) }
        }
        $item=Split-Path -Path $item -Parent
    }
}
Assert-NoRedirect $InstallRoot
$protected=@([IO.Path]::GetPathRoot($InstallRoot),$env:USERPROFILE,$env:LOCALAPPDATA,$env:APPDATA,$env:ProgramFiles,${env:ProgramFiles(x86)},$env:SystemRoot,$env:CODEX_HOME,$env:OPENCODEX_HOME)
$protected+=@((Join-Path $env:LOCALAPPDATA 'Programs'),(Join-Path $env:USERPROFILE '.codex'),(Join-Path $env:USERPROFILE '.opencodex'),(Join-Path $env:USERPROFILE '.continue'),(Join-Path $env:USERPROFILE '.vscode'))
foreach ($path in $protected) {
    if ($path) {
        $full=[IO.Path]::GetFullPath($path).TrimEnd('\')
        if ($full -eq $InstallRoot -or $full.StartsWith($InstallRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Choisir un sous-dossier dedie, pas une racine utilisateur ou systeme.' }
    }
}
$app=Join-Path $InstallRoot 'app'
if ($source -ne $app -and ($source -eq $InstallRoot -or $source.StartsWith($InstallRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or $InstallRoot.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase))) { throw 'La source et la destination ne doivent pas se recouvrir.' }
foreach ($relative in @('pyproject.toml','src\chatgpt_web2api\__init__.py','installer\configure_codex.py','integration\codex-npm\package-lock.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $relative) -PathType Leaf)) { throw ('Source incomplete : '+$relative) }
}
$marker=Join-Path $InstallRoot 'installation.json'
$progressMarker=Join-Path $InstallRoot '.installation-in-progress'
function Assert-CodexMarker([string]$Path) {
    Assert-NoRedirect $Path
    $record=Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($record.product -ne 'Web2API-Continue' -or $record.installation_target -ne 'codex' -or -not $record.root -or [IO.Path]::GetFullPath($record.root).TrimEnd('\') -ne $InstallRoot) { throw 'Dossier appartenant a une autre installation. Choisir un dossier distinct.' }
}
if (Test-Path -LiteralPath $marker) { Assert-CodexMarker $marker }
elseif (Test-Path -LiteralPath $progressMarker) { Assert-CodexMarker $progressMarker }
elseif ((Test-Path -LiteralPath $InstallRoot) -and (Get-ChildItem -LiteralPath $InstallRoot -Force | Select-Object -First 1)) { throw 'Dossier existant non reconnu. Choisir un dossier vide.' }
if (Test-Path -LiteralPath $InstallRoot) {
    # Refuse junctions before any copy, extraction, logging or cleanup.
    foreach ($redirected in @(Get-ChildItem -LiteralPath $InstallRoot -Force -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) {
        $pythonRoot=Join-Path $InstallRoot 'python'
        $target=if ($redirected.Target) { [IO.Path]::GetFullPath([string]@($redirected.Target)[0]) } else { '' }
        if ($redirected.Parent.FullName -eq $pythonRoot -and $redirected.Name -like 'cpython-*' -and $target -and (Split-Path $target -Parent) -eq $pythonRoot -and (Test-Path -LiteralPath $target -PathType Container)) {
            Assert-NoRedirect $target
            continue # uv's minor-version alias targets its owned patch release.
        }
        throw ('Chemin redirige interdit : '+$redirected.FullName)
    }
}
$digest=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($InstallRoot.ToLowerInvariant()))
$mutex=[Threading.Mutex]::new($false,('Local\Web2API-Setup-'+[BitConverter]::ToString($digest).Replace('-','')))
if (-not $mutex.WaitOne(0)) { $mutex.Dispose(); throw 'Une installation est deja en cours pour ce dossier.' }
$transcript=$false
try {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'logs') -Force | Out-Null
    Start-Transcript -Path (Join-Path $InstallRoot 'logs\install.log') -Append | Out-Null
    $transcript=$true
    @{product='Web2API-Continue';installation_target='codex';root=$InstallRoot} | ConvertTo-Json | Set-Content -LiteralPath $progressMarker -Encoding UTF8
    $dependencies=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies.json') -Raw | ConvertFrom-Json
    $explicitCache=-not [string]::IsNullOrWhiteSpace($CacheDirectory)
    if (-not $CacheDirectory) { $CacheDirectory=Join-Path $InstallRoot 'cache' }
    $CacheDirectory=[IO.Path]::GetFullPath($CacheDirectory)
    Assert-NoRedirect $CacheDirectory
    New-Item -ItemType Directory -Path $CacheDirectory -Force | Out-Null
    . (Join-Path $PSScriptRoot 'Download.ps1')
    . (Join-Path $PSScriptRoot 'Reuse.ps1')
    $script:SiblingInstallRoot=Get-CompatibleSiblingInstallation $InstallRoot 'codex'
    $script:InstallStepCount=17
    Write-InstallStatus ('Installation Codex : '+$InstallRoot)
    Write-InstallStatus ('Progression globale : '+$script:InstallStepCount+' etapes ; journal logs\install.log')
    if ($script:SiblingInstallRoot) { Write-InstallStatus ('Installation Continue compatible detectee : '+$script:SiblingInstallRoot) }
    else { Write-InstallStatus 'Aucune installation Continue compatible a reutiliser.' }
    Start-InstallStep 'Preparation et controle de l''installation Codex'
    if (Test-Path -LiteralPath (Join-Path $InstallRoot 'Stop.ps1')) { & (Join-Path $InstallRoot 'Stop.ps1') }
    if (Test-Path -LiteralPath $marker) {
        Invoke-Checked (Join-Path $InstallRoot 'venv\Scripts\python.exe') @((Join-Path $InstallRoot 'app\installer\configure_codex.py'),'--root',$InstallRoot,'--stop-opencodex') -Label 'Arret du proxy gere de cette installation uniquement'
    }
    Start-InstallStep ('Gestionnaire Python uv '+$dependencies.downloads.uv.version)
    Expand-Verified 'uv' (Join-Path $InstallRoot 'apps\uv') 'uv.exe'
    Start-InstallStep ('Node.js '+$dependencies.downloads.node.version)
    Expand-Verified 'node' (Join-Path $InstallRoot 'apps\node') 'node.exe' -Flatten
    Start-InstallStep ('Git '+$dependencies.downloads.git.version)
    Expand-Verified 'git' (Join-Path $InstallRoot 'apps\git') 'cmd\git.exe'
    Start-InstallStep ('Recherche ripgrep '+$dependencies.downloads.rg.version)
    Expand-Verified 'rg' (Join-Path $InstallRoot 'apps\rg') 'rg.exe' -Flatten
    Start-InstallStep ('Python '+$dependencies.python+' et environnement de la passerelle')
    $uv=Join-Path $InstallRoot 'apps\uv\uv.exe'
    $node=Join-Path $InstallRoot 'apps\node\node.exe'
    $npm=Join-Path $InstallRoot 'apps\node\node_modules\npm\bin\npm-cli.js'
    $python=Join-Path $InstallRoot 'venv\Scripts\python.exe'
    $env:PATH=(Join-Path $InstallRoot 'apps\node')+';'+(Join-Path $InstallRoot 'apps\git\cmd')+';'+$env:PATH
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $InstallRoot 'python'
    $env:UV_PYTHON_BIN_DIR=Join-Path $InstallRoot 'apps\python-bin'
    $env:UV_NO_MODIFY_PATH='1'
    $env:UV_CACHE_DIR=Get-ReusableUvCache (Join-Path $CacheDirectory 'uv') $script:SiblingInstallRoot $explicitCache
    $env:PYTHONUTF8='1'
    $env:PYTHONUNBUFFERED='1'
    if (-not (Test-Path -LiteralPath $python)) { Invoke-Checked $uv @('venv','--managed-python','--python',$dependencies.python,(Join-Path $InstallRoot 'venv')) -Label 'Creation Python : venv' }
    Start-InstallStep 'Copie du code et des ressources'
    New-Item -ItemType Directory -Path $app -Force | Out-Null
    if ($source -ne $app) {
        foreach ($name in @('src','integration','installer','docs','pyproject.toml','README.md','LICENSE','THIRD_PARTY_NOTICES.md')) {
            $item=Join-Path $source $name
            if (Test-Path -LiteralPath $item -PathType Container) { Copy-InstallTree $item (Join-Path $app $name) }
            else { Copy-Item -LiteralPath $item -Destination $app -Force }
        }
    }
    Start-InstallStep 'Bibliotheques Python de la passerelle'
    Install-PythonRequirements $uv $python (Join-Path $app 'installer\requirements-core.lock') '.web2api-requirements-core-sha256' 'Installation des bibliotheques Python'
    Start-InstallStep 'Installation de ChatGPT Web2API'
    Invoke-Checked $uv @('pip','install','--python',$python,'--no-deps','--no-build-isolation','--reinstall-package','chatgpt-web2api',$app) -Label 'Installation du paquet ChatGPT Web2API'
    Start-InstallStep 'Paquets isoles OpenCodex, Codex et Playwright'
    $npmRoot=Join-Path $InstallRoot 'apps\npm'
    New-Item -ItemType Directory -Path $npmRoot -Force | Out-Null
    foreach ($name in @('package.json','package-lock.json')) { Copy-Item -LiteralPath (Join-Path $app ('integration\codex-npm\'+$name)) -Destination $npmRoot -Force }
    Install-NpmDependencies $node $npm $npmRoot @('node_modules\playwright\cli.js','node_modules\@openai\codex\bin\codex.js','node_modules\@bitkyc08\opencodex\package.json') 'Installation npm privee de la distribution Codex'
    Start-InstallStep 'Navigateur Chromium dedie'
    $browserRoot=Join-Path $InstallRoot 'browsers'
    $siblingBrowserPackage=if ($script:SiblingInstallRoot) { Join-Path $script:SiblingInstallRoot 'tools\browser' } else { '' }
    $siblingBrowsers=if ($script:SiblingInstallRoot) { Join-Path $script:SiblingInstallRoot 'browsers' } else { '' }
    $browser=Install-PlaywrightChromium $node (Join-Path $npmRoot 'node_modules\playwright\cli.js') $npmRoot $browserRoot $siblingBrowserPackage $siblingBrowsers 'Verification et installation de Chromium'
    Start-InstallStep 'Application de bureau Codex'
    $desktopId=''
    if ($SkipDesktop) { Write-InstallStatus 'Application de bureau NON verifiee/installee : -SkipDesktop -NoLaunch explicites.' }
    else {
        $desktop=Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $desktop) {
            $winget=Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $winget) { throw 'winget absent. Installer App Installer, puis relancer pour installer Codex depuis Microsoft Store.' }
            Invoke-Checked $winget.Source @('install','--id','9PLM9XGG6VKS','-s','msstore','--accept-package-agreements','--accept-source-agreements') -Label 'Installation officielle de Codex depuis Microsoft Store'
            $desktop=Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $desktop) { throw 'OpenAI.Codex absent apres installation Microsoft Store.' }
        $application=(Get-AppxPackageManifest $desktop).Package.Applications.Application | Where-Object { $_.EntryPoint -eq 'Windows.FullTrustApplication' -and $_.Executable -match '(^|[/\\])(Codex|ChatGPT)\.exe$' } | Select-Object -First 1
        if (-not $application) { throw 'Point de lancement OpenAI.Codex introuvable.' }
        $desktopId=$desktop.PackageFamilyName+'!'+$application.Id
        Write-InstallStatus ('Application Codex verifiee : '+$desktopId)
    }
    Start-InstallStep 'Configuration de la passerelle et integration OpenCodex'
    $configure=Join-Path $app 'installer\configure_codex.py'
    $configureArgs=@($configure,'--root',$InstallRoot,'--source',$app,'--browser',$browser.FullName)
    if ($SkipDesktop) { $configureArgs+='--skip-desktop' } else { $configureArgs+=@('--desktop-app-id',$desktopId) }
    Invoke-Checked $python $configureArgs -Label 'Configuration Codex et navigateur isole'
    Invoke-Checked $python @($configure,'--root',$InstallRoot,'--register') -Label 'Enregistrement du modele via OpenCodex'
    Start-InstallStep 'Installation des lanceurs et de la maintenance'
    foreach ($name in @('Environment.ps1','Start.cmd','Stop.ps1','Doctor.cmd','Repair.cmd','Uninstall.ps1','Uninstall.cmd','Service-Codex.ps1','ServiceTask-Codex.ps1')) { Copy-Item -LiteralPath (Join-Path $app ('installer\'+$name)) -Destination $InstallRoot -Force }
    Copy-Item -LiteralPath (Join-Path $app 'installer\Start-Codex.ps1') -Destination (Join-Path $InstallRoot 'Start.ps1') -Force
    Copy-Item -LiteralPath (Join-Path $app 'installer\Doctor-Codex.ps1') -Destination (Join-Path $InstallRoot 'Doctor.ps1') -Force
    Start-InstallStep 'Verification finale de l''installation'
    Invoke-Checked $python @($configure,'--root',$InstallRoot,'--check') -Label 'Diagnostic hors ligne de la distribution Codex'
    Start-InstallStep 'Raccourcis et demarrage automatique'
    if (-not $NoShortcuts) {
        $serviceTaskHelper=Join-Path $InstallRoot 'ServiceTask-Codex.ps1'
        & $serviceTaskHelper -Action Install
        $shell=New-Object -ComObject WScript.Shell
        $desktop=[Environment]::GetFolderPath('Desktop')
        $shortcut=$shell.CreateShortcut((Join-Path $desktop 'Web2API Codex.lnk'))
        $shortcut.TargetPath=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $InstallRoot 'Start.ps1')+'"'
        if ($SkipDesktop) { $shortcut.Arguments+=' -SkipDesktop' }
        $shortcut.WorkingDirectory=$InstallRoot
        $shortcut.WindowStyle=7
        $shortcut.Save()
        $legacyStartup=Join-Path ([Environment]::GetFolderPath('Startup')) 'Web2API Codex.lnk'
        if(Test-Path -LiteralPath $legacyStartup){
            $legacy=$shell.CreateShortcut($legacyStartup)
            if($legacy.Arguments.Contains((Join-Path $InstallRoot 'Start.ps1'))){Remove-Item -LiteralPath $legacyStartup -Force}
        }
    } elseif(Test-Path -LiteralPath (Join-Path $InstallRoot 'service-task.json') -PathType Leaf) {
        # Preserve an already-owned supervisor during a maintenance run that
        # merely asks not to create new shortcuts. Stop.ps1 placed this marker
        # while files were updated; the next logon must be allowed to start it.
        Remove-Item -LiteralPath (Join-Path $InstallRoot 'state\service-stop.requested') -Force -ErrorAction SilentlyContinue
    }
    Start-InstallStep 'Premier lancement'
    if (-not $NoLaunch) { & (Join-Path $InstallRoot 'Start.ps1') }
    else { Write-InstallStatus 'Lancement de la passerelle et du bureau ignore : -NoLaunch.' }
    Complete-InstallStep
    if ($script:InstallStep -ne $script:InstallStepCount) { throw 'Comptage des etapes incoherent.' }
    Remove-Item -LiteralPath $progressMarker -Force
    Write-InstallStatus ('INSTALLATION TERMINEE - '+$script:InstallStepCount+'/'+$script:InstallStepCount+' etapes (100%)')
} catch {
    Write-Host ('INSTALLATION INTERROMPUE : '+$_.Exception.Message) -ForegroundColor Red
    Write-Host ('Relancer le meme installateur. Journal : '+$InstallRoot+'\logs\install.log')
    throw
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    $mutex.ReleaseMutex(); $mutex.Dispose()
}
