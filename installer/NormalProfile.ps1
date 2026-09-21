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
    # Windows PowerShell 5.1 keeps a JSON top-level array as one pipeline
    # object. Piping ConvertFrom-Json directly to Where-Object therefore
    # selects the whole Object[] and turns relativeLocation into Object[].
    # A foreach statement enumerates the parsed array reliably on 5.1.
    $entries=Get-Content -LiteralPath $index -Raw | ConvertFrom-Json
    foreach ($entry in $entries) {
        if ($null -eq $entry -or $null -eq $entry.identifier) { continue }
        if ($entry.identifier.id -ne 'continue.continue' -or $entry.version -ne '2.0.0') { continue }
        $relative=$entry.relativeLocation
        if ($relative -isnot [string] -or [string]::IsNullOrWhiteSpace($relative) -or $relative -match '[/\\]' -or $relative -in @('.','..')) { continue }
        $candidate=Join-Path $Extensions $relative
        $package=Join-Path $candidate 'package.json'
        if (-not (Test-Path -LiteralPath $package -PathType Leaf)) { continue }
        try { $metadata=Get-Content -LiteralPath $package -Raw | ConvertFrom-Json } catch { continue }
        if ($metadata.version -eq '2.0.0') { return Get-Item -LiteralPath $candidate }
    }
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
