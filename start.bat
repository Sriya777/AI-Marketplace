@echo off
REM Double-click to start everything (MongoDB if installed, Hardhat chain, contract, backend, frontend).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
echo.
pause
