#!/bin/sh
# Safe, non-rebuilding launcher for the Stage 0.13.3A.5 disposable pilot DB.
cd "$(dirname "$0")" || exit 1

PILOT_DB="migration_inputs/workspace/warehouse_pilot_candidate.db"
if [ ! -f "$PILOT_DB" ]; then
    echo "Pilot DB не найдена: $PILOT_DB"
    echo "Сначала соберите candidate отдельной migration CLI. Launcher ничего не создаёт."
    exit 1
fi

echo "МИГРАЦИОННЫЙ ПИЛОТ"
echo "Фактический путь DB: $(pwd)/$PILOT_DB"
echo "Проверяю marker, integrity, foreign keys и SQLite sidecars..."
ODE_MIGRATION_PILOT=1 python3 -c "import inventory.core.application; from inventory.warehouse.migration_pilot_review import validate_migration_pilot_database; validate_migration_pilot_database('$PILOT_DB')" || exit 1

echo "Запуск ODE в pilot-only read-only UI..."
ODE_MIGRATION_PILOT=1 python3 app.py web --db "$PILOT_DB"
