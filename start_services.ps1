
# AMIE Service Startup Script (Cloud Backend Mode)
# This script starts the frontend which connects to your deployed Azure Functions.

Write-Host "Starting AMIE Frontend..." -ForegroundColor Cyan
Write-Host ""

# NOTE: Local backend services are disabled because your frontend is 
# configured to talk to the production Azure Functions.
# To run backends locally, uncomment the lines below.

<#
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
#>

# Start Frontend (Vite)
Write-Host "Starting Frontend on port 5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\frontend'; npm run dev"

Write-Host ""
Write-Host "Frontend process initialized!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Frontend URL:  http://localhost:5173" -ForegroundColor White
Write-Host "Backend URLs: (Using Azure Production)" -ForegroundColor Yellow
Write-Host "  - Ingestion:  https://amie-ingestion-fn-hyd0hkd0hzfmawep.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - IDCA:      https://idca-func-hbergrcufpbmh2e5.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - NAA:       https://naa-amie-dkdfggcbaghzdebr.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host "  - AA:        https://aa-func-habphsfdg5ejgtcy.westus2-01.azurewebsites.net/" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to exit this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
