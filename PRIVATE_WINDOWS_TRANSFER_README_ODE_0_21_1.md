# Приватный перенос ODE 0.21.1 RC на рабочий ноутбук

Дата: 2026-08-13
Статус: release candidate; физическая Windows-приёмка **PENDING**

Этот документ относится только к закрытому архиву
`ODE_0.21.1_FULL_PRIVATE_WORK_LAPTOP_TRANSFER.zip`. В отличие от публичного
source-пакета, закрытый архив содержит локальные рабочие БД и правила
Monitoring, поэтому его нельзя публиковать в GitHub, отправлять в общий чат или
класть в общедоступное облако.

## Безопасный перенос

1. Сверьте SHA-256 ZIP с соседним файлом `.zip.sha256`.
2. Полностью распакуйте архив в новую папку, например
   `C:\ODE_0.21.1_FULL_PRIVATE_WORK_LAPTOP_TRANSFER`.
3. Не объединяйте её с распакованной папкой 0.21.0 и не запускайте программу
   прямо из ZIP.
4. Убедитесь, что установлен Python 3.10 или новее.
5. Запустите `start_windows.bat` двойным щелчком.
6. В checklist
   [`docs/MANUAL_TESTING_0_21_1_WINDOWS.md`](docs/MANUAL_TESTING_0_21_1_WINDOWS.md)
   выберите track **PRIVATE TRANSFER**: выполните разделы 1, 2P, 3P и 5–7.
   Разделы 2–4 для PUBLIC SOURCE пропустите — DB уже находятся в закрытом
   payload, повторно копировать или «чисто инициализировать» их нельзя.

Ошибки `'3'`, `'cho'`, `'DE' is not recognized` и
`ModuleNotFoundError: baseline_rehearsal` относятся к отозванным сборкам
0.21.0. Не ремонтируйте старую папку вручную и не копируйте из неё Python/BAT
поверх 0.21.1.

## Состав закрытого контура

- проверенный код ODE 0.21.1 с полным runtime closure;
- `data/warehouse.db` — IXcellerate;
- `data/warehouse_solar.db` — Solar;
- `data/vacations.db` — общий план отпусков;
- локальные ignored JSON-правила Monitoring;
- `TRANSFER_MANIFEST.md` с контрольными суммами приватного payload.

БД помещаются в архив только через согласованные SQLite Backup API snapshots.
Исходные runtime-файлы до и после сборки должны иметь одинаковые SHA-256,
`integrity_check=ok`, пустой `foreign_key_check` и не иметь sidecar-файлов.
Snapshot-файлы внутри закрытого архива сверяются с `TRANSFER_MANIFEST.md` и не
обязаны иметь byte-identical SHA с main-файлом источника: SQLite Backup API
создаёт логически согласованный самостоятельный файл.

Для первого read-only осмотра используйте обычный вход инженера по ФИО.
Credentialed admin-вход пишет одну ожидаемую запись `LOGIN` в primary audit и
меняет SHA `warehouse.db`; такой шаг выполняйте только после фиксации исходного
SHA/audit count и отражайте delta в evidence.

Публичная инструкция запуска находится в
[`README_WINDOWS.md`](README_WINDOWS.md). До физического Windows sign-off этот
архив является кандидатом для приёмки, а не утверждённым rollout.
