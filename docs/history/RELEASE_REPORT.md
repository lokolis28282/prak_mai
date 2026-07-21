# RELEASE_REPORT

Дата проверки: 2026-07-10

## Статус

Release-кандидат проверен на текущей macOS-среде. Критических блокеров в проверенных сценариях не найдено.

## Артефакт

`release/ODE_windows_test.zip`

Содержимое: 14 runtime-файлов под корнем `ODE/`.

Проверено отсутствие мусора в списке package files: `.git`, tests, backups, screenshots, exports не попадают в ZIP.

## Проверки запуска

`start_windows.bat` запускает `app.py` без аргументов. По логике `app.py` это открывает GUI (`inventory.webapp.main`).

`python3 release/ODE_windows_test/app.py --help` проверил доступность packaged Python entrypoint.

`release/ODE_windows_test/data/warehouse.db`: `PRAGMA integrity_check` = `ok`.

## Что не проверено физически

Реальный запуск на Windows не выполнен, потому что текущая среда macOS. Для промышленной передачи нужен финальный запуск ZIP на Windows-хосте: распаковать, запустить `start_windows.bat`, выполнить инженерный вход и smoke-сценарий.

## Итог

По доступным проверкам ZIP пригоден к передаче на Windows smoke. Финальный Windows sign-off остается обязательным перед промышленной эксплуатацией.
