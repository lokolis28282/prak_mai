#!/bin/sh
# Запуск ODE ТОЛЬКО на одноразовой тестовой базе data/warehouse_test_clean.db.
# Рабочая база data/warehouse.db открывается только на чтение для snapshot и
# не изменяется. Перед каждым запуском тестовая база пересоздается заново из
# рабочей (create_clean_test_db.py очищает только операционные данные и
# сохраняет пользователей и справочники).
cd "$(dirname "$0")" || exit 1

echo "Пересоздаю чистую тестовую базу (profile=demo)..."
python3 scripts/create_clean_test_db.py --profile demo --overwrite || exit 1

echo "Запуск ODE на тестовом контуре..."
ODE_TEST_MODE=1 python3 app.py web --db data/warehouse_test_clean.db --warehouse-contour demo
