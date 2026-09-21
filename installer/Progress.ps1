# Plain, timestamped lines remain readable in Windows Terminal and install.log.
$script:InstallClock=[Diagnostics.Stopwatch]::StartNew()
$script:InstallStep=0
$script:InstallStepCount=21
$script:InstallStepName='Preparation'
$script:StepClock=$null
$script:ProgressIntervalSeconds=2
$script:HeartbeatSeconds=5

function Format-Duration([double]$Seconds) {
    $span=[TimeSpan]::FromSeconds([Math]::Max(0,$Seconds))
    return ('{0:00}:{1:00}:{2:00}' -f [Math]::Floor($span.TotalHours),$span.Minutes,$span.Seconds)
}
function Write-InstallStatus([string]$Message) {
    Write-Host ('[{0}] {1}' -f (Format-Duration $script:InstallClock.Elapsed.TotalSeconds),$Message)
}
function Complete-InstallStep {
    if ($script:StepClock) {
        Write-InstallStatus ('OK [{0}/{1}] {2} - duree {3}' -f $script:InstallStep,$script:InstallStepCount,$script:InstallStepName,(Format-Duration $script:StepClock.Elapsed.TotalSeconds))
        $script:StepClock=$null
    }
}
function Start-InstallStep([string]$Name) {
    Complete-InstallStep
    $script:InstallStep++
    $script:InstallStepName=$Name
    $script:StepClock=[Diagnostics.Stopwatch]::StartNew()
    Write-Host ''
    Write-InstallStatus ('ETAPE [{0}/{1}] {2} - {3}% des etapes terminees' -f $script:InstallStep,$script:InstallStepCount,$Name,[Math]::Floor(100*($script:InstallStep-1)/$script:InstallStepCount))
}
function ConvertTo-NativeArgument([string]$Value) {
    # Windows CommandLineToArgvW quoting, including quotes and trailing slashes.
    $escaped=[regex]::Replace($Value,'(\\*)"','$1$1\"')
    return '"'+[regex]::Replace($escaped,'(\\+)$','$1$1')+'"'
}
function Invoke-Checked([string]$Executable,[string[]]$Arguments,[string]$Label='') {
    if (-not $Label) { $Label=[IO.Path]::GetFileName($Executable) }
    Write-InstallStatus ('Demarrage : '+$Label)
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Executable
    if ([IO.Path]::GetExtension($Executable) -in @('.cmd','.bat')) {
        $quoted=@($Executable)+@($Arguments) | ForEach-Object { "'"+$_.Replace("'","''")+"'" }
        $command="[Console]::OutputEncoding=[Text.UTF8Encoding]::new(`$false); & "+($quoted -join ' ')+"; exit `$LASTEXITCODE"
        $info.FileName=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $info.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    } else {
        $info.Arguments=(@($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    }
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.Encoding]::UTF8
    $info.StandardErrorEncoding=[Text.Encoding]::UTF8
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $lastOutput=0.0
    try {
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadLineAsync()
        $stderr=$process.StandardError.ReadLineAsync()
        while ($null -ne $stdout -or $null -ne $stderr -or -not $process.HasExited) {
            # Drain both pipes concurrently, including verbose stderr.
            foreach ($stream in @('stdout','stderr')) {
                $task=Get-Variable -Name $stream -ValueOnly
                for ($batch=0; $null -ne $task -and $task.IsCompleted -and $batch -lt 128; $batch++) {
                    $line=$task.GetAwaiter().GetResult()
                    if ($null -eq $line) { $task=$null; break }
                    if ($line.Length) { Write-InstallStatus ('  '+$line); $lastOutput=$timer.Elapsed.TotalSeconds }
                    if ($stream -eq 'stdout') { $task=$process.StandardOutput.ReadLineAsync() }
                    else { $task=$process.StandardError.ReadLineAsync() }
                }
                Set-Variable -Name $stream -Value $task
            }
            if ($timer.Elapsed.TotalSeconds-$lastOutput -ge $script:HeartbeatSeconds) {
                Write-InstallStatus ('EN COURS : {0} - duree {1}, en attente de nouvelles informations' -f $Label,(Format-Duration $timer.Elapsed.TotalSeconds))
                $lastOutput=$timer.Elapsed.TotalSeconds
            }
            Start-Sleep -Milliseconds 50
        }
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Echec ($($process.ExitCode)) : $Label" }
        Write-InstallStatus ('Termine : {0} - duree {1}' -f $Label,(Format-Duration $timer.Elapsed.TotalSeconds))
    } finally { $process.Dispose() }
}
function Write-TransferProgress([string]$Label,[long]$Done,[long]$Total,[double]$Seconds) {
    $speed=$Done/[Math]::Max($Seconds,0.001)
    $detail=('{0:N2} Mio recus - {1:N2} Mio/s' -f ($Done/1MB),($speed/1MB))
    if ($Total -gt 0) {
        $detail=('{0:N1}% - {1:N2}/{2:N2} Mio - {3:N2} Mio/s' -f (100*$Done/$Total),($Done/1MB),($Total/1MB),($speed/1MB))
        if ($speed -gt 0 -and $Done -lt $Total) { $detail+=' - reste estime '+(Format-Duration (($Total-$Done)/$speed)) }
    } else { $detail+=' - taille totale inconnue' }
    Write-InstallStatus ('{0} : {1} - duree {2}' -f $Label,$detail,(Format-Duration $Seconds))
}
function Copy-InstallTree([string]$Source,[string]$Destination) {
    Write-InstallStatus ('Copie : '+$Destination)
    [void][IO.Directory]::CreateDirectory($Destination)
    foreach ($directory in Get-ChildItem -LiteralPath $Source -Recurse -Directory -Force) {
        [void][IO.Directory]::CreateDirectory((Join-Path $Destination $directory.FullName.Substring($Source.TrimEnd('\').Length+1)))
    }
    $files=@(Get-ChildItem -LiteralPath $Source -Recurse -File -Force)
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $last=0.0; $done=0
    foreach ($file in $files) {
        $target=Join-Path $Destination $file.FullName.Substring($Source.TrimEnd('\').Length+1)
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy($file.FullName,$target,$true)
        $done++
        if ($timer.Elapsed.TotalSeconds-$last -ge $script:ProgressIntervalSeconds -or $done -eq $files.Count) {
            Write-InstallStatus ('Copie : {0}/{1} fichiers ({2:N1}%) - {3}' -f $done,$files.Count,(100*$done/$files.Count),$file.Name)
            $last=$timer.Elapsed.TotalSeconds
        }
    }
}
