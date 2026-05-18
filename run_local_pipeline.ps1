Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " AMIE Local Test Pipeline (Ingestion -> IDCA -> NAA -> AA)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Starting services locally so you can test the new Azure Document Intelligence changes." -ForegroundColor Gray
Write-Host ""

# Sync .env to local.settings.json to assure credentials like Azure Document Intelligence are passed to the locally running Azure Functions
Write-Host "Syncing .env variables to Function Apps..." -ForegroundColor Yellow
$venvActivate = "$PSScriptRoot\.venv\Scripts\Activate.ps1"
$venvPython = "$PSScriptRoot\.venv\Scripts\python.exe"
& $venvPython sync_env.py

# 1. Start Ingestion Agent
Write-Host "[1/5] Starting Ingestion Agent (Port 7071) ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.ui.RawUI.WindowTitle='Ingestion Agent'; & '$venvActivate'; cd '$PSScriptRoot\backend\ingestion-agent'; func start --port 7071 --cors http://localhost:5173"

# Sleep briefly to stagger the startup outputs
Start-Sleep -Seconds 3

# 2. Start IDCA Function
Write-Host "[2/5] Starting IDCA Function (Port 7072) ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.ui.RawUI.WindowTitle='IDCA Function'; & '$venvActivate'; `$env:NAA_BASE='http://localhost:7073'; `$env:AA_BASE='http://localhost:7074'; cd '$PSScriptRoot\backend\idca_func'; func start --port 7072 --cors http://localhost:5173"

Start-Sleep -Seconds 3

# 3. Start NAA Function
Write-Host "[3/5] Starting NAA Function (Port 7073) ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.ui.RawUI.WindowTitle='NAA Function'; & '$venvActivate'; `$env:AA_BASE='http://localhost:7074'; cd '$PSScriptRoot\backend\naa-amie-azure-clean'; func start --port 7073 --cors http://localhost:5173"

Start-Sleep -Seconds 3

# 4. Start AA Function
Write-Host "[4/5] Starting AA Function (Port 7074) ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.ui.RawUI.WindowTitle='AA Function'; & '$venvActivate'; cd '$PSScriptRoot\backend\aa'; func start --port 7074 --cors http://localhost:5173"

Start-Sleep -Seconds 3

# 5. Start Frontend
Write-Host "[5/5] Starting React Frontend (Port 5173) ..." -ForegroundColor Green
# We're writing an ephemeral .env.local file to force the frontend to connect to local Ingestion instead of Azure Production
$envLocalPath = "$PSScriptRoot\frontend\.env.local"
Set-Content -Path $envLocalPath -Value "VITE_API_BASE_URL=http://localhost:7071" -Force
Write-Host " -> Set VITE_API_BASE_URL to http://localhost:7071 in frontend/.env.local so uploads hit your local backend!" -ForegroundColor Yellow

Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$host.ui.RawUI.WindowTitle='Frontend'; cd '$PSScriptRoot\frontend'; npm run dev"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " All services have been launched in separate windows!" -ForegroundColor Green
Write-Host " Wait ~10 seconds for the functions to fully boot up." -ForegroundColor Gray
Write-Host " Open http://localhost:5173 to test your upload pipeline." -ForegroundColor White
Write-Host " Flow: Ingestion (7071) -> IDCA (7072) -> NAA (7073) -> AA (7074)" -ForegroundColor Blue
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit this script..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
