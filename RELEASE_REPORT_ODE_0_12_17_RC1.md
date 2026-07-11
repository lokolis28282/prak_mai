# ODE 0.12.17 RC1 Release Report

Дата сборки: 2026-07-11
Статус: Release Candidate для контролируемого single-node пилота

## Артефакты

- совместимый архив: `release/ODE_windows_test.zip`;
- versioned архив: `release/ODE_0.12.17_RC1.zip`;
- распакованная проверочная папка: `release/ODE_0.12.17_RC1/`;
- SHA-256 обоих архивов:
  `27cd04b36e09cd64f402e232f8d759be914ce961215a475ad712f97ac40a9501`;
- `VERSION`: `ODE 0.12.17 RC1`.

Оба ZIP byte-identical. `unzip -t` завершен без ошибок. Внутри находятся
runtime Python, static assets, рабочая БД, Windows/macOS launch scripts,
пользовательские инструкции, техническая документация и семь Stage review
документов. Tests, scripts, caches, backup и локальные exports в архив не входят.

## Проверки

- 185 unit/contract/API tests: `OK`;
- `ResourceWarning` преобразованы в ошибки: `OK`;
- module boundary audit: `OK`;
- frontend DOM contract audit: `OK`;
- JavaScript syntax: `OK`;
- headless Chrome E2E: `OK`;
- `console.error`, `window.onerror`, `unhandledrejection`: 0;
- resource errors, HTTP 4xx/5xx в штатном E2E: 0;
- mobile shell 390x844: ODE/profile/search видимы, page overflow отсутствует;
- SQLite `integrity_check`: `ok`;
- SQLite `foreign_key_check`: ошибок нет;
- `git diff --check`: `OK`.

## Поддерживаемый контур

- один процесс ODE;
- один SQLite-файл на локальном диске;
- loopback/local workstation;
- контролируемая пилотная нагрузка до 100 000 складских записей;
- обязательный backup до переноса и массовой загрузки.

## Gate до production 1.0

- Windows hardware acceptance с реальным сканером и Excel;
- смешанный load test 50 инженеров;
- SLO и дальнейшая оптимизация миллионного bootstrap (`7,482 с` сейчас);
- внешний backup/restore drill и утвержденные RPO/RTO;
- безопасная первичная настройка admin вместо известного bootstrap password;
- корректирующие/возвратные операции либо утвержденный временный регламент;
- security acceptance выбранного сетевого deployment.

Архив готов к передаче на целевой Windows-компьютер для приемки. Он не должен
публиковаться напрямую в корпоративную сеть или объявляться production 1.0 без
перечисленных gate.
