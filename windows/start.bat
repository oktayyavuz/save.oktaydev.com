@echo off
rem Run the app in the foreground (for testing). Use install.ps1 for a service.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run windows\install.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py
pause
