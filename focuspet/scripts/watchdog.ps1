# 看门狗：心跳超过 StaleMinutes 没更新就重启余光（设计方案 15.5）。
# 由计划任务每 5 分钟调一次：崩溃是必然的，自动恢复比追求不崩更现实。
param(
    [int]$StaleMinutes = 10,
    [string]$Python = "",
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = "Stop"
$heartbeat = Join-Path $ProjectRoot "focuspet\data\heartbeat.txt"

if (Test-Path $heartbeat) {
    $age = (Get-Date) - (Get-Item $heartbeat).LastWriteTime
    if ($age.TotalMinutes -lt $StaleMinutes) {
        exit 0          # 还活着，什么也不做
    }
}

if (-not $Python) {
    $Python = $env:FOCUSPET_PYTHON
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-EventLog -LogName Application -Source "FocusPet" -EventId 9001 `
        -EntryType Warning -Message "看门狗找不到 python，无法重启"
    exit 1
}

Start-Process -FilePath $Python -ArgumentList "-m", "focuspet" `
    -WorkingDirectory $ProjectRoot -WindowStyle Hidden
Write-EventLog -LogName Application -Source "FocusPet" -EventId 9002 `
    -EntryType Warning -Message "余光心跳超时，已重启"
