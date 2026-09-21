$ErrorActionPreference='Stop'
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'installation.json') -Raw | ConvertFrom-Json
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
if ($manifest.product -ne 'Web2API-Continue' -or [IO.Path]::GetFullPath($manifest.root).TrimEnd('\') -ne $root) { throw 'Identite du dossier non verifiee.' }
$editors=@(Get-CimInstance Win32_Process -Filter "Name = 'Code.exe'")
if($editors.Count){throw 'Enregistrer les fichiers et fermer VS Code puis relancer.'}
& (Join-Path $root 'Stop.ps1') -CloseBrowser
& (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $root 'app\installer\normal_profile.py') --detach $root
if ($LASTEXITCODE -ne 0) { throw 'Retrait du profil normal interrompu. Les programmes sont conserves.' }
. (Join-Path $PSScriptRoot 'NormalProfile.ps1')
Backup-LegacyPortableProfile $root
$shell=New-Object -ComObject WScript.Shell
foreach($folder in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Startup'))) {
    $shortcutPath=Join-Path $folder 'Web2API Continue.lnk'
    if(Test-Path -LiteralPath $shortcutPath){
        $shortcut=$shell.CreateShortcut($shortcutPath)
        if($shortcut.Arguments.Contains((Join-Path $root 'Start.ps1'))){Remove-Item -LiteralPath $shortcutPath}
    }
}
# Delete only enumerated program directories, after resolving and checking each target.
# Personal browser state, conversations, media, configuration, logs and backups stay on disk.
foreach($name in @('apps','venv','computer-venv','python','browsers','tools','extensions','cache','staging')) {
    $target=Join-Path $root $name
    if(Test-Path -LiteralPath $target){
        $resolved=(Resolve-Path -LiteralPath $target).Path
        if(-not $resolved.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Chemin de suppression hors installation.'}
        if((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Lien de repertoire inattendu. Suppression refusee.'}
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
Write-Host 'Programmes et raccourcis retires. Les donnees personnelles et sauvegardes sont conservees dans :'
Write-Host $root
