@echo off
setlocal
chcp 65001 >nul
title ODE - МИГРАЦИОННЫЙ ПИЛОТ
cd /d "%~dp0"

set "PILOT_DB=migration_inputs\workspace\warehouse_pilot_candidate.db"
if not exist "%PILOT_DB%" (
    echo Pilot DB не найдена: %PILOT_DB%
    echo Сначала соберите candidate отдельной migration CLI. Launcher ничего не создаёт.
    pause
    exit /b 1
)

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

echo МИГРАЦИОННЫЙ ПИЛОТ
echo Фактический путь DB: %CD%\%PILOT_DB%
echo Проверяю marker, integrity, foreign keys и SQLite sidecars...
set ODE_MIGRATION_PILOT=1
%PY% -c "import inventory.core.application; from inventory.warehouse.migration_pilot_review import validate_migration_pilot_database; validate_migration_pilot_database(r'%PILOT_DB%')"
if errorlevel 1 (
    echo Pilot DB не прошла safety guard.
    pause
    exit /b 1
)

echo Запуск ODE в pilot-only read-only UI...
%PY% app.py web --db "%PILOT_DB%"
if errorlevel 1 (
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
    exit /b 1
)
endlocal
