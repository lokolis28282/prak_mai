# Ручная проверка ODE 0.18.1

Дата: 2026-07-27.

## Контур

Проверка выполнялась на disposable byte-copy трёх SQLite-файлов. Рабочие
`data/warehouse.db`, `data/warehouse_solar.db` и `data/vacations.db` не
использовались для тестовых приходов, расходов, отпусков или backup-действий.

## Общий проход

- вход инженера и администратора, выход и возврат на форму входа;
- главная страница и карточки Warehouse, Vacations, Reports, Monitoring,
  Knowledge и Profile;
- глобальная навигация без `null`, `undefined`, traceback и
  `#interfaceError`;
- CSS и JavaScript загружены с `?v=0.18.1`;
- консоль, `window.error`, unhandled promise rejection, resource errors,
  HTTP 500 и API 500: ошибок нет.

## Warehouse

- переключение IXcellerate/Solar меняет только выбранный складской facade;
- баланс, обзор, приход, расход, инвентаризация, поставки, справочники и
  история открываются в обоих складах;
- пустой Solar показывает рабочие пустые состояния;
- переключатель склада отсутствует вне Warehouse;
- словарь действий использует «Приход / принять» и «Расход / списать»;
- навигация не вызывает `Cannot set properties of null`.

## Vacations

- календарь, список отпусков, сотрудники/графики и конфликты открываются как
  самостоятельный модуль;
- в пустой БД через UI создан синтетический сотрудник с начальным назначением;
- конфликтная заявка подтверждена с inline-комментарием;
- повторное ФИО возвращает HTTP 409 и понятное сообщение, без SQLite-текста и
  HTTP 500;
- складской переключатель на экранах Vacations отсутствует.

Все мутации выполнены только в disposable `vacations.db`.

## Administration backup

- администратор видит ровно три runtime-базы: IXcellerate, Solar и Vacations;
- для каждой строки показаны путь, размер, время изменения, health и последняя
  копия;
- длинные Windows-пути читаемо переносятся внутри широкой прокручиваемой
  таблицы; соседние карточки хранилища и restore-status не сжимаются;
- кнопка создаёт snapshot только для явно выбранного `database_id`;
- копия создаётся SQLite Backup API во внешнем каталоге и получает manifest с
  SHA-256 и результатами integrity/FK/schema-проверки;
- инженер и viewer не могут читать status/list или создавать копии;
- каталог внутри Git, symlink и hardlink блокируются;
- restore-кнопки и upload-контрола нет; интерфейс честно сообщает, что
  восстановление недоступно до реализации полного безопасного протокола.

Создание Vacations snapshot физически проверено кнопкой в disposable
браузерном контуре; остальные профили и проверки отказов подтверждены
автоматическими тестами на временных БД. Рабочий Administration открывался
только для read-only визуальной проверки.

## Автоматическое подтверждение

- полный `unittest discover`: 628 тестов, `OK (skipped=15)`;
- `scripts/smoke_ui.py`: все продуктовые разделы, browser/API errors — 0;
- Python compile и синтаксис всех 47 JavaScript-файлов: OK;
- module-boundary, frontend-contract и repository-data audits: OK;
- clean-test DB dry-run: OK;
- deterministic graph: 245 узлов / 502 связи, `--check` OK;
- `git diff --check`: OK.

Пятнадцать ожидаемых Windows-skip относятся к недоступным платформенным
операциям или отсутствующим ignored migration/pilot-артефактам. Новых
неожиданных skip нет.

## Сохранность данных

До и после browser/gate-проходов SHA-256 каждой из трёх рабочих БД совпал.
Для всех файлов `PRAGMA integrity_check=ok`,
`PRAGMA foreign_key_check` вернул 0 строк, SQLite sidecars отсутствуют.
