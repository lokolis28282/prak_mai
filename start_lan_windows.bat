@echo off
chcp 65001 >nul
setlocal
title ODE - доступ из локальной сети
cd /d "%~dp0"

set "ODE_PORT=8765"
echo.
echo ODE будет доступна с других компьютеров в локальной сети.
echo Адреса для подключения:
powershell -NoProfile -Command "$port='%ODE_PORT%'; [Net.Dns]::GetHostAddresses([Net.Dns]::GetHostName()) ^| Where-Object { $_.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and $_.IPAddressToString -notmatch '^(127\.|169\.254\.)' } ^| ForEach-Object { Write-Host ('  http://' + $_.IPAddressToString + ':' + $port) }"
echo.
echo Для завершения работы вернитесь в это окно и нажмите Ctrl+C.
echo.

start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%ODE_PORT%'"

set "PY="
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python не найден. Установите Python 3.10 или новее.
        pause
        exit /b 1
    )
    set "PY=python"
)
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Для ODE требуется Python 3.10 или новее.
    pause
    exit /b 1
)
%PY% app.py web --host 0.0.0.0 --port %ODE_PORT% --no-browser

if errorlevel 1 (
    echo.
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
)
