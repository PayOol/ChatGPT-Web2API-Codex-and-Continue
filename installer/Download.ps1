Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.IO.Compression.FileSystem
. (Join-Path $PSScriptRoot 'Progress.ps1')

function Receive-InstallDownload([string]$Url,[string]$Path,[string]$Label) {
    $client=New-Object Net.Http.HttpClient
    $client.Timeout=[TimeSpan]::FromSeconds(600)
    $cancel=[Threading.CancellationTokenSource]::new(600000)
    $request=$null; $response=$null; $inputStream=$null; $outputStream=$null
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $last=0.0; [long]$received=0; [long]$total=0
    try {
        Write-InstallStatus ('Connexion pour telecharger : '+$Label)
        $request=[Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Get,$Url)
        $task=$client.SendAsync($request,[Net.Http.HttpCompletionOption]::ResponseHeadersRead,$cancel.Token)
        while (-not $task.IsCompleted) {
            if ($timer.Elapsed.TotalSeconds-$last -ge $script:HeartbeatSeconds) {
                Write-InstallStatus ('Connexion en cours : '+$Label+' - attente des en-tetes HTTP')
                $last=$timer.Elapsed.TotalSeconds
            }
            # Wake immediately when data arrives; polling must not throttle TCP.
            [void]$task.Wait(100)
        }
        $response=$task.GetAwaiter().GetResult()
        [void]$response.EnsureSuccessStatusCode()
        if ($null -ne $response.Content.Headers.ContentLength) { $total=$response.Content.Headers.ContentLength }
        $inputStream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outputStream=[IO.File]::Create($Path)
        $buffer=New-Object byte[] 262144
        Write-TransferProgress $Label 0 $total 0
        while ($true) {
            $read=$inputStream.ReadAsync($buffer,0,$buffer.Length,$cancel.Token)
            while (-not $read.IsCompleted) {
                if ($cancel.IsCancellationRequested) { throw "Delai de telechargement depasse : $Label" }
                if ($timer.Elapsed.TotalSeconds-$last -ge $script:ProgressIntervalSeconds) {
                    Write-TransferProgress $Label $received $total $timer.Elapsed.TotalSeconds
                    $last=$timer.Elapsed.TotalSeconds
                }
                [void]$read.Wait(100)
            }
            $count=$read.GetAwaiter().GetResult()
            if ($count -eq 0) { break }
            $outputStream.Write($buffer,0,$count); $received+=$count
            if ($timer.Elapsed.TotalSeconds-$last -ge $script:ProgressIntervalSeconds) {
                Write-TransferProgress $Label $received $total $timer.Elapsed.TotalSeconds
                $last=$timer.Elapsed.TotalSeconds
            }
        }
        if ($total -gt 0 -and $received -ne $total) { throw "Telechargement incomplet : $Label ($received/$total octets)" }
        Write-TransferProgress $Label $received $total $timer.Elapsed.TotalSeconds
    } finally {
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
        if ($request) { $request.Dispose() }
        $cancel.Dispose(); $client.Dispose()
    }
}
function Get-VerifiedDownload([string]$Name) {
    $entry=$dependencies.downloads.$Name
    $file=Join-Path $CacheDirectory $entry.file
    if (Test-Path -LiteralPath $file) {
        Write-InstallStatus ('Verification SHA256 du cache : '+$Name)
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $entry.sha256) {
            Write-InstallStatus ('Cache valide, telechargement evite : '+$Name)
            return $file
        }
        Write-InstallStatus ('Cache invalide, nouveau telechargement : '+$Name)
    }
    $partial=$file+'.partial'
    for ($attempt=1;$attempt -le 3;$attempt++) {
        try {
            Write-InstallStatus ('Telechargement : {0} {1} - tentative {2}/3' -f $Name,$entry.version,$attempt)
            Receive-InstallDownload $entry.url $partial $Name
            break
        } catch {
            if ($attempt -eq 3) { throw }
            Write-InstallStatus ('Nouvelle tentative : '+$Name+' - '+$_.Exception.Message)
        }
    }
    # The Marketplace may wrap its VSIX in a gzip transport envelope.
    $probe=[IO.File]::OpenRead($partial)
    try { $gzip=($probe.ReadByte() -eq 31 -and $probe.ReadByte() -eq 139) } finally { $probe.Dispose() }
    if ($gzip) {
        Write-InstallStatus ('Decompression de l''enveloppe gzip : '+$Name)
        $inputStream=[IO.File]::OpenRead($partial)
        $decoder=[IO.Compression.GZipStream]::new($inputStream,[IO.Compression.CompressionMode]::Decompress)
        $outputStream=[IO.File]::Create($partial+'.decoded')
        try { $decoder.CopyTo($outputStream) } finally { $outputStream.Dispose();$decoder.Dispose();$inputStream.Dispose() }
        Move-Item -LiteralPath ($partial+'.decoded') -Destination $partial -Force
    }
    Write-InstallStatus ('Verification SHA256 : '+$Name)
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Empreinte SHA256 incorrecte : $Name. Fichier non utilise." }
    Move-Item -LiteralPath $partial -Destination $file -Force
    Write-InstallStatus ('SHA256 valide : '+$Name)
    return $file
}
function Expand-InstallArchive([string]$Archive,[string]$Destination,[string]$Label) {
    [void][IO.Directory]::CreateDirectory($Destination)
    $prefix=[IO.Path]::GetFullPath($Destination).TrimEnd('\')+'\'
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $last=0.0; [long]$done=0; $files=0
    try {
        [long]$total=($zip.Entries | Measure-Object -Property Length -Sum).Sum
        Write-InstallStatus ('Extraction : {0} - {1} entrees, {2:N2} Mio' -f $Label,$zip.Entries.Count,($total/1MB))
        foreach ($entry in $zip.Entries) {
            $target=[IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            if (-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Chemin d''archive invalide.' }
            if (-not $entry.Name) { [void][IO.Directory]::CreateDirectory($target) }
            else {
                [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$target)
            }
            $done+=$entry.Length; $files++
            if ($timer.Elapsed.TotalSeconds-$last -ge $script:ProgressIntervalSeconds -or $files -eq $zip.Entries.Count) {
                Write-InstallStatus ('Extraction {0} : {1:N1}% - {2}/{3} entrees - {4}' -f $Label,(100*$done/[Math]::Max(1,$total)),$files,$zip.Entries.Count,$entry.FullName)
                $last=$timer.Elapsed.TotalSeconds
            }
        }
    } finally { $zip.Dispose() }
}
function Expand-Verified([string]$Name,[string]$Destination,[string]$Executable,[switch]$Flatten) {
    $receipt=Join-Path $Destination '.download-sha256'
    if ((Test-Path -LiteralPath $receipt) -and (Get-Content -LiteralPath $receipt -Raw).Trim() -eq $dependencies.downloads.$Name.sha256 -and (Test-Path -LiteralPath (Join-Path $Destination $Executable))) {
        Write-InstallStatus ('Deja installe, conserve : '+$Name+' '+$dependencies.downloads.$Name.version)
        return
    }
    $archive=Get-VerifiedDownload $Name
    $stage=Join-Path $InstallRoot ('staging\'+$Name+'-'+[Guid]::NewGuid().ToString('N'))
    Expand-InstallArchive $archive $stage $Name
    $content=$stage
    if ($Flatten) { $content=(Get-ChildItem -LiteralPath $stage -Directory | Select-Object -First 1).FullName }
    Copy-InstallTree $content $Destination
    if (-not (Test-Path -LiteralPath (Join-Path $Destination $Executable))) { throw "Archive incomplete : $Name" }
    Set-Content -LiteralPath $receipt -Value $dependencies.downloads.$Name.sha256 -Encoding ASCII
    $resolvedStage=(Resolve-Path -LiteralPath $stage).Path
    if (-not $resolvedStage.StartsWith($InstallRoot+'\staging\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Dossier temporaire hors installation.' }
    Write-InstallStatus ('Nettoyage des fichiers temporaires : '+$Name)
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}
