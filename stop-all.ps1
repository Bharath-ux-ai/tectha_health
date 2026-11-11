# TEC THA Follow-Up Engine - Stop All Local Services
Write-Host ">>> Stopping services..." -ForegroundColor Cyan

Get-Process -Name "node", "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" stop -D (Join-Path (Split-Path $PSScriptRoot -Parent) "pgdata") -m fast

Write-Host "All services stopped." -ForegroundColor Green

