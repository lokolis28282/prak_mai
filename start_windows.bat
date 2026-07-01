@echo off
chcp 65001 >nul
title ODE - Отдел дежурных инженеров
cd /d "%~dp0"
echo Запуск ODE...
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python не найден. Установите Python 3.10 или новее и повторите запуск.
        pause
        exit /b 1
    )
    python app.py
)
if errorlevel 1 (
    echo.
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
)
