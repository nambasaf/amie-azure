
# AMIE Service Startup Script (Local End-to-End Mode)
# This script starts the frontend and the local Azure Function apps.

Write-Host "Starting AMIE Frontend..." -ForegroundColor Cyan
Write-Host ""

# Start Ingestion Agent (Port 7071)
Write-Host "[1/5] Starting Ingestion Agent on port 7071..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\ingestion-agent'; func start --port 7071 --cors http://localhost:5173"

# Start IDCA Function (Port 7072)
Write-Host "[2/5] Starting IDCA on port 7072..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\idca_func'; func start --port 7072 --cors http://localhost:5173"

# Start NAA Function (Port 7073)
Write-Host "[3/5] Starting NAA on port 7073..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\naa-amie-azure-clean'; func start --port 7073 --cors http://localhost:5173"

# Start AA Function (Port 7074)
Write-Host "[4/5] Starting AA on port 7074..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\backend\aa'; func start --port 7074 --cors http://localhost:5173"

# Start Frontend (Vite)
Write-Host "Starting Frontend on port 5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev"

Write-Host ""
Write-Host "Frontend process initialized!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Frontend URL:  http://localhost:5173" -ForegroundColor White
Write-Host "Backend URLs: (Running Locally)" -ForegroundColor Yellow
Write-Host "  - Ingestion:  http://localhost:7071/" -ForegroundColor White
Write-Host "  - IDCA:       http://localhost:7072/" -ForegroundColor White
Write-Host "  - NAA:        http://localhost:7073/" -ForegroundColor White
Write-Host "  - AA:         http://localhost:7074/" -ForegroundColor White
Write-Host "  - A2A:        http://localhost:7075/" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to exit this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
