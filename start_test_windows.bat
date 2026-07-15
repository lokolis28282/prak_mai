@echo off
setlocal
chcp 65001 >nul
title ODE - ТЕСТОВЫЙ КОНТУР
cd /d "%~dp0"

rem Запуск ODE ТОЛЬКО на одноразовой тестовой базе data\warehouse_test_clean.db.
rem Рабочая база data\warehouse.db открывается только на чтение для snapshot и
rem не изменяется. Перед каждым запуском тестовая база пересоздается заново из
rem рабочей (create_clean_test_db.py очищает только операционные данные и
rem сохраняет пользователей и справочники).

where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py -3
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python не найден. Установите Python 3.10 или новее и повторите запуск.
        pause
        endlocal
        exit /b 1
    )
    set PY=python
)

echo Пересоздаю чистую тестовую базу (profile=demo)...
%PY% scripts\create_clean_test_db.py --profile demo --overwrite
if errorlevel 1 (
    echo.
    echo Не удалось подготовить тестовую базу. Текст ошибки указан выше.
    pause
    endlocal
    exit /b 1
)

set ODE_TEST_MODE=1
echo Запуск ODE на тестовом контуре...
%PY% app.py web --db data\warehouse_test_clean.db --warehouse-contour demo
if errorlevel 1 (
    echo.
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
    endlocal
    exit /b 1
)

endlocal
