# ============================================================
# WSL/Docker Disk Maintenance Script
# Run when C: drive is low on space, or schedule via Task Scheduler
# ============================================================

param([switch]$SkipDockerPrune)

$ErrorActionPreference = "Stop"
$log = @()
$log += "=== WSL Disk Maintenance — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="

# 1. Initial C: drive check
$cBefore = (Get-PSDrive C).Free
$log += "C: free before: $([math]::Round($cBefore/1GB,1)) GB"

# 2. If Docker is running, prune unused data
$dockerRunning = Get-Process -Name 'com.docker.backend' -ErrorAction SilentlyContinue
if ($dockerRunning -and !$SkipDockerPrune) {
    $log += "Docker prune..."
    docker system prune -af --volumes 2>&1 | ForEach-Object { $log += "  $_" }
}

# 3. Shutdown Docker + WSL
$log += "Stopping Docker..."
Get-Process -Name '*docker*' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

$log += "WSL shutdown..."
wsl --shutdown
Start-Sleep -Seconds 5

# 4. Compact all VHDX files
$vhdxFiles = @(
    "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx",
    "$env:LOCALAPPDATA\Docker\wsl\main\ext4.vhdx"
)

# Also find Ubuntu VHDX
$ubuntuPattern = "$env:LOCALAPPDATA\Packages\*\LocalState\ext4.vhdx"
Get-ChildItem -Path $ubuntuPattern -ErrorAction SilentlyContinue | ForEach-Object {
    $vhdxFiles += $_.FullName
}

foreach ($vhdx in $vhdxFiles) {
    if (-not (Test-Path $vhdx)) { continue }
    $before = (Get-Item $vhdx).Length
    if ($before -lt 100MB) { continue }  # skip tiny files
    
    $log += "Compacting: $(Split-Path $vhdx -Leaf) ($([math]::Round($before/1GB,1)) GB)"
    $script = @"
select vdisk file="$vhdx"
compact vdisk
"@
    $script | diskpart | Out-Null
    $after = (Get-Item $vhdx).Length
    $reclaimed = $before - $after
    if ($reclaimed -gt 100MB) {
        $log += "  -> $([math]::Round($after/1GB,1)) GB (reclaimed $([math]::Round($reclaimed/1GB,1)) GB)"
    } else {
        $log += "  -> already compact"
    }
}

# 5. Final check
$cAfter = (Get-PSDrive C).Free
$saved = $cAfter - $cBefore
$log += "C: free after: $([math]::Round($cAfter/1GB,1)) GB (freed $([math]::Round($saved/1GB,1)) GB)"
$log += "=== Done ==="

# Write log
$logDir = "$PSScriptRoot\..\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir "wsl-compact-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
$log | Out-File $logFile
Write-Output $log
