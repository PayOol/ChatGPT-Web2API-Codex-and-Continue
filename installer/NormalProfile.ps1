$ErrorActionPreference='Stop'

function Find-NormalEditor {
    $candidates=@(
        (Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\Code.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft VS Code\Code.exe')
    )
    foreach ($candidate in $candidates) {
        if ((Test-Path -LiteralPath $candidate) -and -not (Test-Path -LiteralPath (Join-Path (Split-Path $candidate) 'data'))) {
            return $candidate
        }
    }
    return $null
}

function Find-NormalContinue([string]$Extensions) {
    $index=Join-Path $Extensions 'extensions.json'
    if (-not (Test-Path -LiteralPath $index)) { return $null }
    $entry=Get-Content -LiteralPath $index -Raw | ConvertFrom-Json | Where-Object { $_.identifier.id -eq 'continue.continue' -and $_.version -eq '2.0.0' } | Select-Object -First 1
    if (-not $entry -or -not $entry.relativeLocation -or $entry.relativeLocation -match '[/\\]') { return $null }
    $candidate=Join-Path $Extensions $entry.relativeLocation
    if (Test-Path -LiteralPath (Join-Path $candidate 'package.json')) { return Get-Item -LiteralPath $candidate }
    return $null
}

function Backup-LegacyPortableProfile([string]$Root) {
    $Root=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    $source=Join-Path $Root 'apps\vscode\data'
    if (-not (Test-Path -LiteralPath $source)) { return }
    $destination=Join-Path $Root ('backups\portable-profile-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8))
    foreach ($target in @($source,$destination)) {
        if (-not [IO.Path]::GetFullPath($target).StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Archivage hors installation refuse.' }
        if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Lien inattendu dans le profil.' }
    }
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $destination
    Write-Host ('Ancien profil portable conserve : '+$destination)
}
