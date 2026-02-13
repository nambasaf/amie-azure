
# AMIE Service Startup Script
# This script starts all backend services and the frontend in separate terminal windows

Write-Host "Starting AMIE Services..." -ForegroundColor Cyan
Write-Host ""

# Start Ingestion Agent (Port 7071)
Write-Host "[1/5] Starting Ingestion Agent on port 7071..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\ingestion-agent'; func start --port 7071 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start IDCA Function (Port 7072)
Write-Host "[2/5] Starting IDCA on port 7072..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\idca_func'; func start --port 7072 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start NAA Function (Port 7073)
Write-Host "[3/5] Starting NAA on port 7073..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\naa-amie-azure-clean'; func start --port 7073 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start AA Function (Port 7074)
Write-Host "[4/5] Starting AA on port 7074..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\aa'; func start --port 7074 --cors http://localhost:5173"

Start-Sleep -Seconds 2

# Start Frontend (Vite)
Write-Host "[5/5] Starting Frontend on port 5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; npm run dev"

Write-Host ""
Write-Host "All services started!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service URLs:" -ForegroundColor Yellow
Write-Host "  - Ingestion:  https://amie-ingestion-fn-hyd0hkd0hzfmawep.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - IDCA:      https://idca-func-hbergrcufpbmh2e5.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - NAA:       https://naa-amie-dkdfggcbaghzdebr.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - AA:        https://aa-func-habphsfdg5ejgtcy.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - Frontend:  http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to exit this window (services will continue running)..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
