# TEC THA Follow-Up Engine - Start All Services Locally
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$pgData = Join-Path (Split-Path $root -Parent) "pgdata"
$pgBin = "C:\Program Files\PostgreSQL\17\bin"

Write-Host ">>> Starting PostgreSQL on port 5433..." -ForegroundColor Cyan
if (Test-Path "$pgBin\postgres.exe") {
    Start-Process "$pgBin\postgres.exe" -ArgumentList "-D `"$pgData`"" -WindowStyle Hidden
}

Write-Host ">>> Starting Backend API (Port 8000)..." -ForegroundColor Cyan
Start-Process "powershell" -ArgumentList "-NoExit", "-Command", "cd `"$root\backend`"; python -m uvicorn app.main:app --port 8000"

Write-Host ">>> Starting Reminder Worker..." -ForegroundColor Cyan
Start-Process "powershell" -ArgumentList "-NoExit", "-Command", "cd `"$root\backend`"; python -m app.worker"

Write-Host ">>> Starting Frontend Web App (Port 3000)..." -ForegroundColor Cyan
Start-Process "powershell" -ArgumentList "-NoExit", "-Command", "cd `"$root\frontend`"; `$env:API_ORIGIN='http://localhost:8000'; npm run dev"

Write-Host "`nAll services have been started!" -ForegroundColor Green
Write-Host "Open: http://localhost:3000" -ForegroundColor Yellow

