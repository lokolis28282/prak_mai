#!/bin/sh
# Marker-guarded, non-rebuilding launcher for the full warehouse candidate.
cd "$(dirname "$0")" || exit 1

FULL_DB="migration_inputs/workspace/warehouse_full_candidate.db"
if [ ! -f "$FULL_DB" ]; then
    echo "Full candidate DB не найдена: $FULL_DB"
    echo "Сначала выполните явную offline-сборку. Launcher ничего не создаёт и не пересобирает."
    exit 1
fi

echo "ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА"
echo "Фактический путь DB: $(pwd)/$FULL_DB"
echo "Проверяю FULL_WAREHOUSE_CANDIDATE, integrity, foreign keys, mode и SQLite sidecars..."
ODE_FULL_MIGRATION_CANDIDATE=1 python3 -c "import inventory.core.application; from inventory.warehouse.migration_full_review import validate_full_migration_database; validate_full_migration_database('$FULL_DB')" || exit 1

echo "Запуск ODE в full-candidate read-only review..."
echo "Адрес будет напечатан ниже. Для остановки нажмите Ctrl+C в этом окне."
ODE_FULL_MIGRATION_CANDIDATE=1 python3 app.py web --db "$FULL_DB"
