@echo off
chcp 65001 >nul
setlocal
title ODE - настройка доступа из локальной сети
cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
    echo Запрашиваются права администратора для настройки Windows Firewall...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "ODE_PYTHON_EXE="
where py >nul 2>nul
if %errorlevel%==0 (
    for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)"`) do set "ODE_PYTHON_EXE=%%I"
) else (
    for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)"`) do set "ODE_PYTHON_EXE=%%I"
)

if not defined ODE_PYTHON_EXE (
    echo Python не найден. Сначала установите Python 3.10 или новее.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$name='ODE LAN 8765'; Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue ^| Remove-NetFirewallRule; New-NetFirewallRule -DisplayName $name -Description 'ODE: доступ только из локальных подсетей' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Program $env:ODE_PYTHON_EXE -RemoteAddress LocalSubnet -Profile Any ^| Out-Null"
if errorlevel 1 (
    echo Не удалось создать правило брандмауэра.
    pause
    exit /b 1
)

echo.
echo Правило "ODE LAN 8765" создано успешно.
echo Доступ разрешен только с адресов локальных подсетей.
echo Теперь запускайте start_lan_windows.bat.
pause
