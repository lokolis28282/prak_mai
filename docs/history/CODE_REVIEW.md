# CODE_REVIEW

Дата проверки: 2026-07-10

## Findings

P2: `inventory/webapp.py` смешивает HTML/CSS/JS/API в одном файле и собирает UI через цепочки `.replace(...)`.

Риск: малое изменение строки может отключить вставку секции, обработчика или id. Проверенный build сейчас работает, но сопровождение хрупкое.

Рекомендация: после релиза вынести HTML/JS в шаблоны или хотя бы разбить строки по независимым константам без текстовых replace-цепочек.

P3: QA-команда `pytest` недоступна в текущем окружении.

Риск: инженер может считать регресс не пройденным из-за отсутствующей зависимости, хотя `unittest` проходит.

Рекомендация: добавить `pytest` в `requirements-dev.txt` или документировать `python3 -m unittest -v tests.test_warehouse` как канонический регресс.

P3: `tests/test_warehouse.py` во время `unittest` печатает `ResourceWarning: unclosed database` в одном нагрузочном тесте.

Риск: не блокирует выполнение, но загрязняет QA-вывод и может скрывать реальные предупреждения.

Рекомендация: закрыть соединения в соответствующем тестовом участке.

## Positive Checks

Python compile: OK.

SQLite integrity: OK.

Service regression: 80 `unittest` OK.

Headless UI smoke: OK.

Admin UI smoke on temporary DB: OK.

Release ZIP content: OK.
