# AMIE Service Startup Script
# This script starts all backend services and the frontend in separate terminal windows

Write-Host "Starting AMIE Services..." -ForegroundColor Cyan
Write-Host ""

# Check if Azurite is already running
$azuriteRunning = Get-NetTCPConnection -LocalPort 10000 -ErrorAction SilentlyContinue
if (-not $azuriteRunning) {
    Write-Host "[0/6] Starting Azurite (Azure Storage Emulator)..." -ForegroundColor Green
    $azuriteDir = Join-Path $PSScriptRoot ".azurite"
    if (-not (Test-Path $azuriteDir)) {
        New-Item -ItemType Directory -Path $azuriteDir -Force | Out-Null
    }
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; azurite --silent --location .azurite --debug .azurite\debug.log" -WindowStyle Minimized
    Start-Sleep -Seconds 3
    Write-Host "       Azurite started on ports 10000 (blob), 10001 (queue), 10002 (table)" -ForegroundColor Gray
}
else {
    Write-Host "[0/6] Azurite is already running" -ForegroundColor Yellow
}

# Start Ingestion Agent (Port 7073)
Write-Host "[1/6] Starting Ingestion Agent on port 7073..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; .venv\Scripts\Activate.ps1; cd backend\ingestion-agent; func start --port 7073 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start IDCA Function (Port 7072)
Write-Host "[2/6] Starting IDCA on port 7072..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; .venv\Scripts\Activate.ps1; cd backend\idca_func; func start --port 7072 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start NAA Function (Port 7074)
Write-Host "[3/6] Starting NAA on port 7074..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; .venv\Scripts\Activate.ps1; cd backend\naa-amie-azure-clean; func start --port 7074 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start AA Function (Port 7070)
Write-Host "[4/6] Starting AA on port 7070..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; .venv\Scripts\Activate.ps1; cd backend\aa; func start --port 7070 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start Frontend (Vite)
Write-Host "[5/6] Starting Frontend on port 5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; npm run dev"

Write-Host ""
Write-Host "All services started!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service URLs:" -ForegroundColor Yellow
Write-Host "  - Ingestion: http://localhost:7073/api" -ForegroundColor White
Write-Host "  - IDCA:      http://localhost:7072/api" -ForegroundColor White
Write-Host "  - NAA:       http://localhost:7074/api" -ForegroundColor White
Write-Host "  - AA:        http://localhost:7070/api" -ForegroundColor White
Write-Host "  - Frontend:  http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to exit this window (services will continue running)..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
