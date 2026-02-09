@echo off
echo ========================================
echo Running TextRP Chatbot with E2EE in Docker
echo ========================================

REM Check if Docker is running
docker version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Docker is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)

echo.
echo Building Docker image with E2EE support...
docker-compose build

if %ERRORLEVEL% neq 0 (
    echo ERROR: Docker build failed!
    pause
    exit /b 1
)

echo.
echo Verifying E2EE installation...
docker-compose run --rm verify-e2ee

echo.
echo Starting the chatbot...
echo Press Ctrl+C to stop the container
echo.
docker-compose up textrp-chatbot

pause
