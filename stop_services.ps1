# AMIE Service Stop Script
# This script stops all running services

Write-Host "Stopping AMIE Services..." -ForegroundColor Cyan
Write-Host ""

# Stop Azurite
Write-Host "[1/2] Stopping Azurite..." -ForegroundColor Yellow
$azuriteProcesses = Get-Process | Where-Object { $_.ProcessName -like "*azurite*" }
if ($azuriteProcesses) {
    $azuriteProcesses | Stop-Process -Force
    Write-Host "       Azurite stopped" -ForegroundColor Green
}
else {
    Write-Host "       Azurite was not running" -ForegroundColor Gray
}

# Stop Azure Functions (func processes)
Write-Host "[2/2] Stopping Azure Functions..." -ForegroundColor Yellow
$funcProcesses = Get-Process | Where-Object { $_.ProcessName -eq "func" }
if ($funcProcesses) {
    $funcProcesses | Stop-Process -Force
    Write-Host "       Azure Functions stopped" -ForegroundColor Green
}
else {
    Write-Host "       No Azure Functions were running" -ForegroundColor Gray
}

# Stop Node/Vite processes (frontend)
$nodeProcesses = Get-Process | Where-Object { $_.ProcessName -eq "node" } | Where-Object { $_.MainWindowTitle -like "*vite*" -or $_.CommandLine -like "*vite*" }
if ($nodeProcesses) {
    Write-Host "       Stopping Frontend (Vite)..." -ForegroundColor Yellow
    $nodeProcesses | Stop-Process -Force
    Write-Host "       Frontend stopped" -ForegroundColor Green
}

Write-Host ""
Write-Host "All services stopped!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
