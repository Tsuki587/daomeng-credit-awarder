@echo off
setlocal
"%~dp0.venv\Scripts\python.exe" "%~dp0DM.py" %*
exit /b %errorlevel%
