# ODE 0.21.1 — физическая приёмка Windows

Дата checklist: 2026-08-13. Статус: **PENDING — физический double-click на
целевом Windows-ноутбуке ещё не выполнен**.

Этот документ не заменяет автоматический gate. Он фиксирует последнюю
обязательную проверку переносимого release candidate на реальном рабочем
ноутбуке. Итог можно изменить на PASS только после заполнения всех полей и
сохранения evidence; отсутствие evidence означает PENDING.

Сначала выберите ровно один track:

- **PUBLIC SOURCE** — `ODE_0.21.1_windows_source.zip`, без DB и локальных
  Monitoring rules: выполнить разделы 1, 2, 3, затем при разрешённом переносе
  данных раздел 4;
- **PRIVATE TRANSFER** —
  `ODE_0.21.1_FULL_PRIVATE_WORK_LAPTOP_TRANSFER.zip`, уже содержащий три
  snapshot DB и локальные Monitoring rules: выполнить 1, 2P и 3P; не выполнять
  «чистый запуск без данных» и не копировать DB второй раз.

Разделы 5–7 общие для обоих track. Смешивать файлы public/private или двух
разных сборок запрещено.

## Отозванный пакет 0.21.0

Архивы ODE 0.21.0 нельзя использовать для повторного переноса. Симптомы
отозванного/неполного пакета:

- `'3' is not recognized as an internal or external command`;
- `'cho' is not recognized as an internal or external command`;
- `'DE' is not recognized as an internal or external command`;
- `ModuleNotFoundError: No module named 'baseline_rehearsal'`.

При любом из этих симптомов остановить запуск. Не исправлять BAT/Python
вручную, не смешивать файлы 0.21.0 и 0.21.1, не открывать, не переименовывать и
не заменять `warehouse.db`, `warehouse_solar.db` или `vacations.db`. Старую
папку оставить как read-only evidence до подтверждения нового запуска.

## Паспорт проверки

| Поле | Значение |
|---|---|
| Исполнитель | PENDING |
| Дата и время | PENDING |
| Ноутбук / инвентарный идентификатор | PENDING |
| Windows edition/build | PENDING |
| Python (`py -3 --version`) | PENDING |
| Track / имя ZIP | PENDING: PUBLIC SOURCE или PRIVATE TRANSFER + точное имя |
| Ожидаемый SHA-256 | PENDING: взять из файла рядом с финальным артефактом |
| Фактический SHA-256 | PENDING |
| Путь новой установки | PENDING; отдельная новая папка |
| Commit/tag кандидата | PENDING |

## 1. До распаковки

- [ ] ODE и все процессы `python.exe`/`py.exe`, связанные с прежней копией,
  остановлены.
- [ ] ZIP и файл внешнего SHA-256 получены из одного утверждённого release
  набора.
- [ ] SHA-256 ZIP совпал; имя версии внутри пакета — 0.21.1.
- [ ] Выбрана новая пустая папка, не вложенная в старую установку и не
  синхронизируемая сетевым/облачным клиентом.
- [ ] Старые рабочие БД не находятся внутри папки, которую планируется удалить
  или перезаписать.
- [ ] Для каждого рабочего файла записаны path, size, SHA-256,
  `PRAGMA integrity_check` и `PRAGMA foreign_key_check`; сделаны внешний
  byte-copy и проверенный SQLite backup.

## 2. PUBLIC SOURCE: состав распакованного source package

Этот раздел выполняется только для PUBLIC SOURCE.

- [ ] `start_windows.bat` открывается как Windows batch и не содержит BOM.
- [ ] Все `.bat` используют CRLF; строка `@echo off` отображается целиком.
- [ ] Присутствуют `app.py`, `inventory/`, `static/`, `baseline_rehearsal/`,
  `ode/`, `scripts/`, `docs/architecture/ddl/` и `docs/`.
- [ ] Присутствуют `verify_schema.sql`, `verify_domain_invariants.sql` и
  `docs/architecture/ddl/V001__...V008__...`.
- [ ] Присутствуют `ODE_USER_GUIDE.html`, `ODE_PRESENTATION.html`,
  `README_WINDOWS.md` и `RELEASE_REPORT_ODE_0_21_1.md`.
- [ ] В source package нет `data/*.db`, backup, exports, raw migration data,
  локальных Monitoring JSON, паролей или секретов.

## 2P. PRIVATE TRANSFER: состав закрытого пакета

Этот раздел выполняется вместо раздела 2 только по разрешённому закрытому
каналу. Значения checksum/hostname/ФИО не переносить в публичный evidence.

- [ ] В корне есть `TRANSFER_MANIFEST.md` и его checksum совпадают с каждым
  приватным payload-файлом.
- [ ] Присутствуют ровно три runtime DB ожидаемых ролей:
  `data/warehouse.db`, `data/warehouse_solar.db`, `data/vacations.db`.
- [ ] Для каждой DB до запуска: `integrity_check=ok`, `foreign_key_check`
  пуст, required tables соответствуют роли; рядом нет `-wal`, `-shm`,
  `-journal`.
- [ ] Присутствует только утверждённый набор локальных Monitoring JSON; файлы
  не выводятся в публичный log/screenshot и не копируются в GitHub.
- [ ] Кодовая часть содержит тот же 0.21.1 runtime closure и CRLF/no-BOM BAT,
  что public source candidate; архив 0.21.0 не примешан.

## 3. PUBLIC SOURCE: чистый double-click запуск без рабочих данных

Этот раздел выполняется только для PUBLIC SOURCE. Созданные при bootstrap
пустые локальные DB являются временным clean-install evidence, а не рабочими
данными; остановите ODE до разрешённого подключения рабочих файлов.

- [ ] Двойной щелчок по `start_windows.bat` не выводит ошибки `'3'`, `'cho'`
  или `'DE' is not recognized`.
- [ ] Python не выводит `ModuleNotFoundError: baseline_rehearsal` и другие
  import errors.
- [ ] В консоли видны версия 0.21.1, ожидаемые пути runtime и адрес
  `http://127.0.0.1:8765`.
- [ ] Браузер открывается; login screen отображается без сломанной разметки.
- [ ] Обычный вход инженера работает; admin-вход требует credential и не
  включается переключателем внутри уже созданной сессии.
- [ ] Выход завершает сессию; повторный защищённый запрос без cookie отклонён.

## 3P. PRIVATE TRANSFER: double-click с уже включёнными snapshot DB

Этот раздел выполняется вместо раздела 3. До запуска DB не перемещать и не
заменять; зафиксировать их SHA/counts/audit count.

- [ ] Двойной щелчок по `start_windows.bat` не выводит BAT/import errors и
  печатает три ожидаемых runtime path.
- [ ] Login screen и обычный вход инженера по ФИО работают; это действие не
  создаёт `LOGIN` audit.
- [ ] Контур не помечен как тестовый; IXcellerate/Solar/Vacations соответствуют
  manifest и не перепутаны ролями.
- [ ] До credentialed admin-входа SHA и business/audit counts трёх DB совпали
  с состоянием до запуска.

## 4. PUBLIC SOURCE: безопасное подключение рабочих данных

Для PRIVATE TRANSFER этот раздел пропускается: snapshots уже включены и
проверены в 2P/3P. В PUBLIC SOURCE рабочие данные переносить только после
успешного чистого запуска. Не заменять
их тестовой или candidate DB. Операция выполняется при остановленных writers
по утверждённому runbook `docs/LOCAL_WORKING_DATABASE_RUNBOOK.md`.

- [ ] Подключены три разные БД: IXcellerate `warehouse.db`, Solar
  `warehouse_solar.db`, Vacations `vacations.db`.
- [ ] Ни один путь не является symlink/hardlink другого runtime-файла.
- [ ] После копирования SHA-256 каждого файла совпал с исходным byte-copy либо
  расхождение объяснено и подтверждено approved SQLite Backup API procedure.
- [ ] `integrity_check=ok`, `foreign_key_check` пуст для всех трёх БД;
  `-wal`, `-shm`, `-journal` sidecars отсутствуют до запуска.
- [ ] Обычный `start_windows.bat` показывает рабочий, а не тестовый контур.

## 5. Контролируемый read-mostly пользовательский проход

Обычный вход инженера по ФИО не пишет `LOGIN`. Успешный credentialed admin-вход
в normal runtime намеренно добавляет одну запись `LOGIN` в primary
`data/warehouse.db`, поэтому его byte SHA изменится. Перед admin-входом
зафиксируйте audit count; после него допускается только этот объяснённый delta.
Solar/Vacations и Warehouse/Reports/Knowledge business counts меняться не
должны. В review mode login audit отключён, но review mode не используется для
этой приёмки.

- [ ] Главная открывает Warehouse, Reports, Monitoring, Knowledge, Vacations
  и Administration по правам текущей роли.
- [ ] В Warehouse явно переключаются IXcellerate и Solar; поиск/баланс каждого
  склада показывает только его данные.
- [ ] Поиск существующего S/N открывает карточку и Timeline; evidence состава
  не выдаётся за физический slot/current-state без соответствующей операции.
- [ ] Reports открывает УВР, сменные/недельные отчёты и существующую историю.
- [ ] Monitoring выполняет локальный manual routing; live DCIM запускается
  только отдельным явным действием и не нужен для этого gate.
- [ ] Knowledge открывает доступные статьи; private attachments соблюдают роль.
- [ ] Vacations показывает календарь обеих площадок из отдельной Vacations DB.
- [ ] После отдельного credentialed admin-входа Administration показывает
  health трёх runtime-БД; restore отсутствует и остаётся fail-closed.
- [ ] В primary audit добавлена ровно ожидаемая запись `LOGIN`; иных business
  или audit mutations в read-mostly проходе нет.

## 6. Контролируемая запись на disposable данных

Не выполнять этот раздел на рабочих БД. Использовать только
`start_test_windows.bat` и явно видимый баннер **ТЕСТОВЫЙ КОНТУР**.

- [ ] Test launcher создаёт три новые disposable DB и не принимает пути
  production IXcellerate/Solar/Vacations.
- [ ] Preview прихода, расхода, поставки и Inventory Number ничего не пишет до
  Confirm.
- [ ] Confirm тестовой операции атомарен; повторный S/N/списание отклоняются.
- [ ] После остановки теста SHA-256 трёх рабочих DB совпадает со значением до
  теста.

## 7. Завершение и evidence

- [ ] ODE остановлен через `Ctrl+C`; порт 8765 освобождён.
- [ ] После прохода повторены SHA-256, integrity/FK и sidecar checks трёх
  runtime-БД: Solar/Vacations byte-identical; delta IXcellerate отсутствует
  либо полностью объяснён единственным credentialed `LOGIN` audit.
- [ ] Сохранены: PowerShell SHA-256 ZIP, версия Windows/Python, полный console
  log, снимок login/main, результаты модульного прохода и DB before/after.
- [ ] Ни один screenshot/log не содержит password, hash, session cookie,
  серийные номера или ФИО, не разрешённые для передачи.

## Итоговый verdict

**PENDING**

Для PASS заполнить:

- исполнитель и timestamp: PENDING;
- SHA-256 проверенного ZIP: PENDING;
- результат double-click: PENDING;
- результат clean source/package/import check: PENDING;
- результат read-only модульного прохода: PENDING;
- runtime DB before/after SHA + integrity/FK: PENDING;
- ссылка/путь к безопасному evidence: PENDING;
- открытые замечания: PENDING.

Если хотя бы один обязательный пункт не пройден, verdict — FAIL/BLOCKED с
точным симптомом; release candidate не обозначается как рабочий rollout.
