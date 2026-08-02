#!/bin/sh
# Запуск ODE ТОЛЬКО на трёх одноразовых тестовых БД Warehouse/Solar/Vacations.
# Рабочие Warehouse DB открываются только на чтение для snapshot; рабочая
# Vacations DB не читается. Перед каждым запуском targets пересоздаются заново.
cd "$(dirname "$0")" || exit 1

echo "Пересоздаю чистую тестовую базу (profile=demo)..."
python3 scripts/create_clean_test_db.py --profile demo --overwrite || exit 1
python3 scripts/create_clean_test_db.py --source data/warehouse_solar.db --output data/warehouse_solar_test_clean.db --profile empty --overwrite || exit 1
python3 scripts/create_clean_vacations_test_db.py --overwrite || exit 1

echo "Запуск ODE на тестовом контуре..."
ODE_TEST_MODE=1 python3 app.py web --db data/warehouse_test_clean.db --solar-db data/warehouse_solar_test_clean.db --vacations-db data/vacations_test_clean.db --warehouse-contour demo
