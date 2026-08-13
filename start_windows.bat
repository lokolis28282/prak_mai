@echo off
chcp 65001 >nul
title ODE - Отдел дежурных инженеров
cd /d "%~dp0"
echo Запуск ODE...
set "PY="
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python не найден. Установите Python 3.10 или новее и повторите запуск.
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
%PY% app.py
if errorlevel 1 (
    echo.
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
)
