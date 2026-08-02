@echo off
setlocal
chcp 65001 >nul
title ODE - ТЕСТОВЫЙ КОНТУР
cd /d "%~dp0"

rem Запуск ODE ТОЛЬКО на трёх одноразовых тестовых БД Warehouse/Solar/Vacations.
rem Рабочие Warehouse DB открываются только на чтение для snapshot; рабочая
rem Vacations DB не читается. Перед каждым запуском targets пересоздаются заново.

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
%PY% scripts\create_clean_test_db.py --source data\warehouse_solar.db --output data\warehouse_solar_test_clean.db --profile empty --overwrite
if errorlevel 1 (
    echo.
    echo Не удалось подготовить тестовую Solar DB. Текст ошибки указан выше.
    pause
    endlocal
    exit /b 1
)
%PY% scripts\create_clean_vacations_test_db.py --overwrite
if errorlevel 1 (
    echo.
    echo Не удалось подготовить тестовую Vacations DB. Текст ошибки указан выше.
    pause
    endlocal
    exit /b 1
)

set ODE_TEST_MODE=1
echo Запуск ODE на тестовом контуре...
%PY% app.py web --db data\warehouse_test_clean.db --solar-db data\warehouse_solar_test_clean.db --vacations-db data\vacations_test_clean.db --warehouse-contour demo
if errorlevel 1 (
    echo.
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
    endlocal
    exit /b 1
)

endlocal
