# MANUAL_TESTING_0_12_17_1

Ручная приемка ODE 0.12.17.1 RC2 выполняется только на disposable test DB.
Физическое удаление подтвержденных приходов/расходов в этой версии не
реализовано: проверяется только редактирование browser draft до `confirm`.

## Подготовка

1. Зафиксировать SHA и проверки рабочей БД:

   ```bash
   shasum -a 256 data/warehouse.db
   sqlite3 data/warehouse.db "PRAGMA integrity_check;"
   sqlite3 data/warehouse.db "PRAGMA foreign_key_check;"
   ```

2. Выполнить `python3 scripts/create_clean_test_db.py --dry-run`.
3. Создать отдельную demo DB и проверить её:

   ```bash
   TEST_DIR="$(mktemp -d)"
   TEST_DB="$TEST_DIR/ode_0_12_17_1_manual.db"
   python3 scripts/create_clean_test_db.py \
     --profile demo --output "$TEST_DB" --overwrite
   sqlite3 "$TEST_DB" "PRAGMA integrity_check;"
   sqlite3 "$TEST_DB" "PRAGMA foreign_key_check;"
   ```

4. Запустить test contour с `ODE_TEST_MODE=1` и этой DB. Баннер
   «ТЕСТОВЫЙ КОНТУР» должен быть виден на login и после входа.
5. Открыть DevTools Console/Network и очистить предыдущие сообщения.

## Главная, навигация и поиск

- После входа видны ровно четыре карточки: Склад, Отчеты, Мониторинг, Профиль.
- ODE из каждого модуля возвращает на Главную.
- У admin виден кликабельный вход в Администрирование; у engineer его нет.
- Monitoring показывает только placeholder «В разработке» и не содержит
  складских «Проблем»/«Событий».
- Лупа открывает modal, focus находится в search input.
- Поиск по существующему S/N показывает результат; ArrowDown/ArrowUp меняют
  focus, Enter открывает карточку оборудования.
- Escape/клик по backdrop закрывает modal и возвращает focus на лупу.
- Закрытый modal не должен снова показать результат от старого debounce/fetch.

## Scanner draft прихода

1. Открыть `Склад → Принять оборудование → Сканировать оборудование`,
   заполнить обязательные общие поля.
2. Добавить три уникальных тестовых S/N (`RC2-R-01/02/03`). Счетчик = 3.
3. Повторно отсканировать `RC2-R-02`: второй строки нет, существующая строка
   подсвечена, показано «Этот S/N уже находится в текущем списке», focus в
   scanner input.
4. Удалить среднюю строку одной кнопкой. Modal подтверждения не появляется;
   есть toast, счетчик = 2, S/N исчез из DOM и `ode_receipt_draft`.
5. Перезагрузить страницу и вернуться к активному draft: удаленный S/N не
   восстановился, две строки остались.
6. Снова добавить удаленный S/N — добавление разрешено. Выбрать его checkbox и
   выполнить «Удалить выбранные» с подтверждением.
7. Подтвердить приход. В `stock_receipts` должны появиться только
   `RC2-R-01/03`; `RC2-R-02` отсутствует, draft key удален, empty state виден.
8. Отдельно проверить «Очистить список»: confirmation обязателен, после accept
   DOM/state/localStorage пусты, после reload строки не возвращаются.

## Scanner draft расхода

1. Подготовить три доступных S/N во временной DB и записать исходный баланс.
2. Добавить все три в `Склад → Выдать оборудование → Сканировать оборудование`.
3. Проверить duplicate, single delete, reload/localStorage и повторное
   добавление по тем же правилам, что у прихода.
4. Удалить средний S/N и подтвердить два оставшихся.
5. В `stock_issues` и `stock_issue_allocations` появились только две операции;
   удаленный S/N остался в балансе и не получил audit/issue/allocation.
6. В новом draft удаленный S/N снова добавляется.
7. Неизвестный warning/problem S/N, удаленный до confirm, не должен создать
   unmatched `stock_issue`, audit или проблему.
8. Проверить «Удалить выбранные» и «Очистить список» с confirmation; после
   reload удаленные строки не возвращаются.

## Остальные сценарии

- Manual receipt/issue и CSV preview остаются отдельными потоками и не меняют
  scanner draft.
- В Balance ввести точный S/N: прежние строки сразу заменяются состоянием
  «Поиск по всей базе...», а после ответа остаётся строка именно искомого S/N;
  карточка открывается из этой строки.
- History, Reports, delivery acceptance, Profile и Administration открываются
  без ошибок.
- Проверить desktop и ширину 390 px: ODE, Профиль и лупа доступны, горизонтального
  overflow нет.

## Gate

Приемка проходит только если одновременно:

- `console.error = 0`, `window.onerror = 0`, `unhandledrejection = 0`;
- resource errors = 0, API HTTP 500 = 0;
- удаленная строка отсутствует в confirm payload и в созданных DB rows;
- удаление расхода не меняет баланс/аллокации удаленного S/N;
- `integrity_check = ok`, `foreign_key_check` пуст;
- SHA рабочей `data/warehouse.db` после проверки совпадает с исходным.
