@echo off
title School Fee Register
cd /d "%~dp0"
where py >nul 2>nul && (py -3 server.py %* & goto end)
where python >nul 2>nul && (python server.py %* & goto end)
echo.
echo   Python is not installed on this computer.
echo   1. Go to https://www.python.org/downloads/ and download Python.
echo   2. While installing, TICK the box "Add python.exe to PATH".
echo   3. Then double-click this file again.
echo.
:end
pause
