@echo off
setlocal

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found.
    echo Please install Python 3.9 or later from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist venv (
    echo Setting up for the first time...
    python -m venv venv
    if errorlevel 1 ( echo Failed to create virtual environment. & pause & exit /b 1 )
    venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( echo Failed to install dependencies. & pause & exit /b 1 )
)

echo.
echo K7 LED Controller starting...
echo Opening http://localhost:5000 in your browser.
echo Close this window to stop the server.
echo.

start "" http://localhost:5000
venv\Scripts\python server.py

pause
