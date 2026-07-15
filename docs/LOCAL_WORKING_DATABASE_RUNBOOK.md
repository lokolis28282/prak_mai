# Local Working Database Runbook

## Reference changes and proven test-data correction

Справочники изменяются только через `Администрирование ODE → Управление
справочниками`; ручной SQLite update запрещён. Перед любой production correction
создайте вне репозитория byte-copy и SQLite `.backup`, сохраните SHA256SUMS,
manifest, counts, HEAD, integrity/FK и проверьте обе копии read-only.

Для exact test record сначала докажите отсутствие migration/source provenance и
реальных связей. `scripts/remove_test_serial.py` намеренно привязан к reviewed
receipt 1050001/S/N `1`, проверяет SHA и backups и отказывается работать при
любом расхождении. Не адаптируйте его под LIKE или массовое удаление. После
correction повторите SHA/counts/distinct/leading-zero samples/integrity/FK.

Диагностика global search: проверить `/api/global-search`, затем facade/service,
`EXPLAIN QUERY PLAN` exact S/N и Inventory Number. Не выгружать 50 000 строк в
browser. Полная ручная проверка описана в
`MANUAL_TESTING_WAREHOUSE_STABILIZATION.md`.

Дата: 2026-07-14. Область действия: один локальный экземпляр ODE.

## Единственный рабочий контур

Из корня репозитория обычный запуск всегда использует один путь:

```bash
cd ~/Documents/prak_mai
python3 app.py
```

Рабочая БД: `data/warehouse.db`. В консоли должны появиться `WORKING
DATABASE`, её абсолютный путь, версия ODE, число карточек и integrity status.
Интерфейс доступен на `http://127.0.0.1:8765` и открывается на обычной главной
странице. Migration env/launchers для рабочей смены не нужны.

`migration_inputs/workspace/warehouse_full_candidate.db` — immutable build
artifact, из которого была получена рабочая БД. Pilot и остальные candidate DB
нужны только для воспроизводимости/review. Raw XLSX/TXT, generated candidate и
reports не исправляются вручную и не подменяют рабочий файл.

## Выполненная promotion

Фактическая запись операции:

- старая рабочая SHA-256:
  `49020e71e764d3a05ecd18d4baa406c1c359bf6470b7c60eca38d716665f17fb`;
- исходная candidate SHA-256:
  `dd97fe6cebf27c8bb894ac021b267dec4a9ad50ffa39b6bd5e412bb7547ddb53`;
- опубликованная `.next` SHA-256 после первого compatibility startup:
  `170729d1555c8eafd65bdc6caea53395b2ff04a82d200b8f7b25d615d9518a51`;
- post-startup SHA-256 до пользовательских операций:
  `aad540d26c89b79b0da9f7c2881b78e03717371a9bf627e157f5acc3c9278f57`;
- handoff SHA-256 после первого штатного `LOGIN` audit
  (`2026-07-14 20:19:30`):
  `4ede3a74b1efdc56fcc8a689e652cf8f7511c4293a45bd509e51db8101794c65`;
- внешний backup старой БД:
  `~/ODE_Backups/20260714T171002+0300/`;
- `SHA256SUMS` подтверждает byte-copy, SQLite `.backup` и manifest; обе DB
  копии имеют `integrity_check=ok`, пустой `foreign_key_check`, 23 старые
  receipt rows и одного активного admin.

Новые SHA отличаются от исходного candidate ожидаемо: normal startup до
publication выполнил существующую совместимую инициализацию плоских runtime
справочников. Обязательный финальный запуск выявил продвижение
`sqlite_sequence` повторными `INSERT OR IGNORE`; бизнес-строки не менялись, а
повторный startup исправлен как idempotent no-op. Startup сам по себе больше
не меняет SHA; обычные разрешённые операции и audit (`LOGIN`, приход, расход и
т. п.) закономерно создают новый рабочий SHA. Marker, operational rows,
security hashes/roles и migration provenance при startup не изменились.

1. До изменений записаны Git HEAD, путь runtime DB, SHA/размер/sidecars,
   `integrity_check`, `foreign_key_check`, пользователи и row counts старой и
   candidate DB.
2. Старая `data/warehouse.db` остановленного контура сохранена во внешнем
   `~/ODE_Backups/<timestamp>/` как точная byte-copy и независимый SQLite
   `.backup`. Для обеих копий проверены checksums, integrity/FK и counts;
   manifest содержит исходный HEAD и причину замены.
3. Candidate проверена по marker `FULL_WAREHOUSE_CANDIDATE`, schema,
   security hashes/roles, operational/reconciliation counts, отсутствию старых
   test S/N и sidecars. Обычный runtime/Fascade/UI smoke выполнен на временной
   byte-copy.
4. Candidate скопирована byte-for-byte в sibling
   `data/warehouse.db.next`. После повторных проверок и normal runtime smoke
   остановлены writers, снова проверены sidecars, затем выполнен атомарный
   `os.replace` из `.next` в `data/warehouse.db`.
5. Post-promotion checks и mutation/browser smoke выполняются на безопасной
   временной копии новой рабочей БД, не на финальном файле.

Исходный candidate не удаляется. Pilot DB не копируется. Raw Excel/TXT не
меняются.

## Backup перед будущим изменением

1. Остановить ODE и проверить отсутствие процессов, открывших рабочую БД на
   запись, а также `warehouse.db-wal`, `warehouse.db-shm` и
   `warehouse.db-journal`.
2. Создать каталог `~/ODE_Backups/<timestamp>/` вне Git.
3. Снять точную byte-copy остановленного файла и независимый snapshot через
   SQLite Backup API/CLI `.backup`.
4. Сохранить `SHA256SUMS` и manifest: время, HEAD, исходный путь, размер, SHA,
   integrity/FK, security/user count, ключевые row counts и причину.
5. Открыть обе копии read-only и независимо проверить SHA,
   `PRAGMA integrity_check`, `PRAGMA foreign_key_check` и counts.

Не удалять и не перезаписывать исходную БД, пока обе копии не подтверждены. Не
класть backup в репозиторий и не выполнять обычный `cp` поверх открытой
SQLite-БД.

## Проверка изменений

- Для unit/integration/browser smoke сначала сделать byte-copy рабочей БД во
  временный каталог и передать её через `--db`.
- Любые тесты прихода, расхода, пользователя, пароля или другого mutation
  выполнять только на этой копии.
- После теста проверить копию на integrity/FK, завершить сервер/Chrome и удалить
  временные sidecars. Финальную `data/warehouse.db` не использовать как fixture.
- Exact S/N проверять как минимум на leading-zero и long identifiers; отдельно
  проверять Equipment Card, receipt/issue history, opening state и баланс.

Gate выполненной promotion: Python/JavaScript syntax, module/frontend audits,
309 unit tests, ordinary headless smoke и отдельный admin migration-review
smoke. Оба browser smoke завершились с нулём console/window/unhandled/resource/
HTTP/API500 errors; исходный candidate сохранил SHA и не получил sidecars.

## Rollback рабочей БД

1. Остановить ODE. Не продолжать rollback при активном writer или sidecar.
2. Выбрать byte-copy либо SQLite snapshot из конкретного backup-каталога;
   сверить его с `SHA256SUMS` и manifest, затем проверить integrity/FK/users и
   ожидаемые counts.
3. Сохранить текущее проблемное состояние отдельно для расследования.
4. Поместить проверенную rollback-копию как sibling
   `data/warehouse.db.next`, ещё раз открыть read-only и проверить.
5. Выполнить атомарный `os.replace(data/warehouse.db.next,
   data/warehouse.db)` на том же файловом разделе.
6. Запустить `python3 app.py`, сверить консольный contour, авторизацию,
   карточки/баланс и отсутствие HTTP/browser errors.

Нельзя чинить принятую миграцию ad-hoc `DELETE`/`UPDATE` или копировать backup
поверх открытой БД.

## Candidate, test и будущий production server

Рабочая локальная БД — promoted descendant candidate, но артефакты имеют разные
lifecycle: candidate воспроизводится из immutable sources и остаётся
диагностическим доказательством; pilot ограничен review; `data/warehouse.db`
получает обычные Warehouse writes.

Будущий server deployment потребует отдельного runbook: versioned code/schema
migrations, server paths/permissions, maintenance window, secrets, backup
retention, concurrency и отдельный acceptance gate. Он сейчас не реализован.
Обычный code release не содержит test/local DB и никогда не копирует её на
production вместе с исходниками или ZIP.
