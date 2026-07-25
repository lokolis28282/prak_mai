@echo off
setlocal
chcp 65001 >nul
title ODE - ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА
cd /d "%~dp0"

set "FULL_DB=migration_inputs\workspace\warehouse_full_candidate.db"
if not exist "%FULL_DB%" (
    echo Full candidate DB не найдена: %FULL_DB%
    echo Сначала выполните явную offline-сборку. Launcher ничего не создаёт и не пересобирает.
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

echo ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА
echo Фактический путь DB: %CD%\%FULL_DB%
echo Проверяю FULL_WAREHOUSE_CANDIDATE, integrity, foreign keys, mode и SQLite sidecars...
set ODE_FULL_MIGRATION_CANDIDATE=1
%PY% -c "import inventory.core.application; from inventory.warehouse.migration_full_review import validate_full_migration_database; validate_full_migration_database(r'%FULL_DB%')"
if errorlevel 1 (
    echo Full candidate DB не прошла safety guard.
    pause
    exit /b 1
)

echo Запуск ODE в full-candidate read-only review...
echo Адрес будет напечатан ниже. Для остановки нажмите Ctrl+C в этом окне.
%PY% app.py web --db "%FULL_DB%"
if errorlevel 1 (
    echo ODE завершилась с ошибкой. Текст ошибки указан выше.
    pause
    exit /b 1
)
endlocal
