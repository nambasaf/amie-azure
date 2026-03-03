# PowerShell script to start all Functions locally
# Run from project root: .\start-functions.ps1

Write-Host "Starting Azure Functions..." -ForegroundColor Green

# Start Ingestion Function
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend/ingestion-agent; func start" -WindowStyle Normal

# Wait a bit
Start-Sleep -Seconds 2

# Start NAA Function on different port
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend/naa-amie-azure-clean; func start --port 7072" -WindowStyle Normal

# Wait a bit
Start-Sleep -Seconds 2

# Start IDCA Function on different port
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend/idca_func; func start --port 7073" -WindowStyle Normal

Write-Host "All Functions starting in separate windows..." -ForegroundColor Yellow
Write-Host "Ingestion: http://localhost:7071" -ForegroundColor Cyan
Write-Host "NAA: http://localhost:7072" -ForegroundColor Cyan
Write-Host "IDCA: http://localhost:7073" -ForegroundColor Cyan




