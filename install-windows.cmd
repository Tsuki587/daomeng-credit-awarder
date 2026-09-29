@echo off
setlocal
python -m venv "%~dp0.venv"
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
exit /b %errorlevel%
