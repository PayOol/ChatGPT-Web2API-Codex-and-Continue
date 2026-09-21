function Invoke-Checked([string]$Executable,[string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Echec ($LASTEXITCODE) : $Executable" }
}
function Get-VerifiedDownload([string]$Name) {
    $entry=$dependencies.downloads.$Name
    $file=Join-Path $CacheDirectory $entry.file
    if ((Test-Path -LiteralPath $file) -and (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $entry.sha256) { return $file }
    $partial=$file+'.partial'
    for ($attempt=1;$attempt -le 3;$attempt++) {
        try { Invoke-WebRequest -Uri $entry.url -OutFile $partial -UseBasicParsing -TimeoutSec 600; break }
        catch { if ($attempt -eq 3) { throw }; Write-Host "Nouvelle tentative de telechargement : $Name" }
    }
    # The Marketplace may return a gzip transport envelope around the VSIX.
    # Normalize that envelope before verifying the pinned archive digest.
    $probe=[IO.File]::OpenRead($partial)
    try { $gzip=($probe.ReadByte() -eq 31 -and $probe.ReadByte() -eq 139) } finally { $probe.Dispose() }
    if ($gzip) {
        $inputStream=[IO.File]::OpenRead($partial)
        $decoder=[IO.Compression.GZipStream]::new($inputStream,[IO.Compression.CompressionMode]::Decompress)
        $outputStream=[IO.File]::Create($partial+'.decoded')
        try { $decoder.CopyTo($outputStream) } finally { $outputStream.Dispose();$decoder.Dispose();$inputStream.Dispose() }
        Move-Item -LiteralPath ($partial+'.decoded') -Destination $partial -Force
    }
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Empreinte SHA256 incorrecte : $Name. Fichier non utilise." }
    Move-Item -LiteralPath $partial -Destination $file -Force
    return $file
}
function Expand-Verified([string]$Name,[string]$Destination,[string]$Executable,[switch]$Flatten) {
    $receipt=Join-Path $Destination '.download-sha256'
    if ((Test-Path -LiteralPath $receipt) -and (Get-Content -LiteralPath $receipt -Raw).Trim() -eq $dependencies.downloads.$Name.sha256 -and (Test-Path -LiteralPath (Join-Path $Destination $Executable))) { return }
    Write-Host "Installation : $Name $($dependencies.downloads.$Name.version)"
    $archive=Get-VerifiedDownload $Name
    $stage=Join-Path $InstallRoot ('staging\'+$Name+'-'+[Guid]::NewGuid().ToString('N'))
    [IO.Compression.ZipFile]::ExtractToDirectory($archive,$stage)
    $content=$stage
    if ($Flatten) { $content=(Get-ChildItem -LiteralPath $stage -Directory | Select-Object -First 1).FullName }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $content -Force | Copy-Item -Destination $Destination -Recurse -Force
    if (-not (Test-Path -LiteralPath (Join-Path $Destination $Executable))) { throw "Archive incomplete : $Name" }
    Set-Content -LiteralPath $receipt -Value $dependencies.downloads.$Name.sha256 -Encoding ASCII
    $resolvedStage=(Resolve-Path -LiteralPath $stage).Path
    if (-not $resolvedStage.StartsWith($InstallRoot+'\staging\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Dossier temporaire hors installation.' }
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}
