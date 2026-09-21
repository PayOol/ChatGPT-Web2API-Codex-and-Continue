$ErrorActionPreference='Stop'

function Move-PortableDirectory([string]$Root,[string]$Source,[string]$Destination) {
    $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    foreach ($target in @($Source,$Destination)) {
        $absolute=[IO.Path]::GetFullPath($target)
        if (-not $absolute.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Migration hors installation refusee.' }
        if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Lien inattendu : $target" }
    }
    if (Test-Path -LiteralPath $Source) {
        if (Test-Path -LiteralPath $Destination) { throw "Deux profils existent : $Source et $Destination. Aucun profil ecrase." }
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Destination)) -Force | Out-Null
        Move-Item -LiteralPath $Source -Destination $Destination
    } else { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
}

function Set-PortableEditor([string]$Root) {
    $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $portable=Join-Path $Root 'apps\vscode\data'
    foreach ($pair in @(@('vscode-data','user-data'),@('extensions','extensions'),@('vscode-shared-data','shared-data'))) {
        Move-PortableDirectory $Root (Join-Path $Root $pair[0]) (Join-Path $portable $pair[1])
    }
}

function Save-PortableEditorData([string]$Root) {
    $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $portable=Join-Path $Root 'apps\vscode\data'
    # Move personal profiles out of apps before uninstalling program directories.
    foreach ($pair in @(@('user-data','vscode-data'),@('shared-data','vscode-shared-data'))) {
        Move-PortableDirectory $Root (Join-Path $portable $pair[0]) (Join-Path $Root $pair[1])
    }
}
