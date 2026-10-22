@echo off
setlocal enabledelayedexpansion
title Incident Report Console
cd /d "%~dp0"

echo ========================================================
echo       Incident Report Console & Telegram Bot
echo ========================================================
echo.

:: 1. Check Python installation
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in your system PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    echo and ensure "Add Python to PATH" is checked during setup.
    echo.
    pause
    exit /b 1
)

:: 2. Set up environment file (.env)
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] .env file not found. Creating from .env.example...
        copy ".env.example" ".env" >nul
        echo [OK] Default .env created successfully.
    ) else (
        echo [INFO] Generating default .env file...
        (
            echo # Quick Incident Reporter Configuration
            echo PORT=3006
            echo HOST=0.0.0.0
            echo ADMIN_PASSWORD=admin123
            echo SECRET_KEY=incident_secret_key_change_in_production_982347293487293
            echo TELEGRAM_BOT_TOKEN=7639751548:AAFMxcn66CIAi6Fy3NIDiZzBgqTCuG_tbRY
            echo TELEGRAM_CHAT_ID=-1002756155863
            echo TELEGRAM_GROUP_ID=@ihtv_report_group
            echo MAX_DISPATCH_RETRIES=3
            echo DISPATCH_TIMEOUT_SECONDS=10
        ) > ".env"
        echo [OK] Default .env created successfully.
    )
) else (
    echo [OK] .env configuration found.
)

:: 3. Setup and activate virtual environment
if not exist "venv\Scripts\activate.bat" (
    echo.
    echo [INFO] Virtual environment not found. Creating venv...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: 4. Install / Verify dependencies
echo.
echo [INFO] Checking and installing dependencies...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies!
    pause
    exit /b 1
)
echo [OK] Dependencies are up to date.

:: 5. Launch the Application
echo.
echo ========================================================
echo  Server is starting...
echo  - Employee Portal: http://localhost:3006
echo  - Admin Panel:     http://localhost:3006/admin
echo  - Telegram Bot:    Active in background
echo.
echo  Press Ctrl+C to stop the server.
echo ========================================================
echo.

:: Optionally launch default browser after a short delay
start "" http://localhost:3006

python main.py

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Server stopped with code %errorlevel%.
    pause
)
