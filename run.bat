@echo off
title Report Console - Starting Server
cd /d "%~dp0"

if exist venv\Scripts\activate.bat goto ACTIVATE

echo Creating virtual environment (venv)...
python -m venv venv
if errorlevel 1 goto ERROR

:ACTIVATE
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Checking and installing dependencies...
pip install -r requirements.txt

echo.
echo ========================================================
echo Starting Report Console Web Service...
echo Access the application at: http://127.0.0.1:3006
echo Press Ctrl+C to stop the server.
echo ========================================================
echo.

python main.py
goto END

:ERROR
echo.
echo [ERROR] Failed to set up virtual environment. Please make sure Python is installed and added to PATH.
pause

:END
