param([switch]$CloseBrowser)
$ErrorActionPreference='Stop'
$manifestPath=Join-Path $PSScriptRoot 'installation.json'
$manifest=if(Test-Path -LiteralPath $manifestPath -PathType Leaf){Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json}else{$null}
$serviceTaskHelper=Join-Path $PSScriptRoot 'ServiceTask-Codex.ps1'
$serviceTaskState=Join-Path $PSScriptRoot 'service-task.json'
if($manifest -and $manifest.installation_target -eq 'codex' -and (Test-Path -LiteralPath $serviceTaskHelper -PathType Leaf) -and (Test-Path -LiteralPath $serviceTaskState -PathType Leaf)){
    & $serviceTaskHelper -Action Stop
}
$configFile=Join-Path $PSScriptRoot 'config.json'
$owned=@(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -like '*-m chatgpt_web2api*' -and $_.CommandLine.Contains($configFile)
})
foreach($service in $owned) {
    # Recheck identity immediately before stopping; never stop a process by name alone.
    $current=Get-CimInstance Win32_Process -Filter "ProcessId = $($service.ProcessId)"
    if ($current -and $current.CreationDate -eq $service.CreationDate -and $current.CommandLine.Contains($configFile)) {
        Stop-Process -Id $service.ProcessId -ErrorAction Stop
        Wait-Process -Id $service.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
    }
}
if ($CloseBrowser) {
    if(-not $manifest){$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json}
    $profile=Join-Path $PSScriptRoot 'browser-profile'
    $browsers=@(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
        $_.ExecutablePath -eq $manifest.browser -and $_.CommandLine.Contains($profile) -and $_.CommandLine -notlike '*--type=*'
    })
    foreach ($browser in $browsers) {
        $current=Get-CimInstance Win32_Process -Filter "ProcessId = $($browser.ProcessId)"
        if ($current -and $current.CreationDate -eq $browser.CreationDate -and $current.ExecutablePath -eq $manifest.browser -and $current.CommandLine.Contains($profile)) {
            & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $browser.ProcessId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $browser.ProcessId -ErrorAction SilentlyContinue)) { throw 'Le navigateur dedie reste actif.' }
        }
    }
}
