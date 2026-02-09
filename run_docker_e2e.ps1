#!/usr/bin/env pwsh

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Running TextRP Chatbot with E2EE in Docker" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check if Docker is running
try {
    docker version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker not running"
    }
} catch {
    Write-Host "ERROR: Docker is not running!" -ForegroundColor Red
    Write-Host "Please start Docker Desktop and try again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nBuilding Docker image with E2EE support..." -ForegroundColor Green
docker-compose build

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Docker build failed!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "`nVerifying E2EE installation..." -ForegroundColor Green
docker-compose run --rm verify-e2ee

Write-Host "`nStarting the chatbot..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the container`n" -ForegroundColor Yellow

docker-compose up textrp-chatbot

Write-Host "`nContainer stopped." -ForegroundColor Cyan
Read-Host "Press Enter to exit"
