# История версий ODE 0.21.1

Актуализировано: 2026-08-13. Это понятная карта развития продукта и патчей.
Она дополняет полный [`CHANGELOG.md`](../../CHANGELOG.md), но не переписывает
исторические release reports и не создаёт задним числом несуществовавшие Git-
коммиты или теги.

## Линия продукта

| Версия | Основной результат | Git/evidence |
|---|---|---|
| Stage 1–4.3 / ODE 0.12–0.12.15 | Базовые Warehouse, Reports, UI, администрирование и последовательное выделение модульных границ | Исторические разделы `CHANGELOG.md`, `docs/STAGES_HISTORY.md` и `docs/history/` |
| 0.12.16–0.12.17.1 | Первый release candidate, безопасный test-контур, навигация, поиск и product hardening | Исторические разделы `CHANGELOG.md` и `docs/history/` |
| 0.13.1–0.13.4 | Карточка оборудования, массовое назначение Inventory Number, УВР, справочники, migration review и scanner-операции | `CHANGELOG.md`, stage-specific документы и reviews |
| 0.14.0 | FULL Inventory Preview/resolutions, disposable rehearsal, Monitoring/Knowledge и presentation candidate | `CHANGELOG.md`, архитектурные и manual-testing contracts |
| 0.15.0 | Стабилизация Warehouse history/export/UI и чистый public baseline | `9492e0f`, [`RELEASE_REPORT_ODE_0_15_0.md`](../../RELEASE_REPORT_ODE_0_15_0.md) |
| 0.16.0 | Физическое выделение Administration, Reports, Warehouse, routes и templates | `ce0564e`…`7c04105`, [`RELEASE_REPORT_ODE_0_16_0.md`](../../RELEASE_REPORT_ODE_0_16_0.md) |
| 0.17.0 | Два физически изолированных склада IXcellerate/Solar | `b5fa6ce`, [`RELEASE_REPORT_ODE_0_17_0.md`](../../RELEASE_REPORT_ODE_0_17_0.md) |
| 0.18.0 | Отдельный модуль Vacations и UX stabilization | `898866d`, [`RELEASE_REPORT_ODE_0_18_0.md`](../../RELEASE_REPORT_ODE_0_18_0.md) |
| 0.18.1 | Registry трёх runtime-БД и проверенные multi-DB backup snapshots | `cc663be`, [`RELEASE_REPORT_ODE_0_18_1.md`](../../RELEASE_REPORT_ODE_0_18_1.md) |
| 0.19.0 | Синхронизация living-документации с фактическим runtime | `ab3e7ab`, [`RELEASE_REPORT_ODE_0_19_0.md`](../../RELEASE_REPORT_ODE_0_19_0.md) |
| 0.19.1 | Исправления startup, перехода из карточки в расход, модального окна и demo Solar contour | [`RELEASE_REPORT_ODE_0_19_1.md`](../../RELEASE_REPORT_ODE_0_19_1.md) |
| 0.20.0 | Evidence-only состав оборудования, полный system audit и интеграция УВР/PNR/XLSX | `96da2e`…`26a48a1`, [`RELEASE_REPORT_ODE_0_20_0.md`](../../RELEASE_REPORT_ODE_0_20_0.md) |
| 0.21.0 | Интеграция Monitoring, auth/runtime documentation и автономная инструкция оператора | `1d6ea03`…`ccbec75`, [`RELEASE_REPORT_ODE_0_21_0.md`](../../RELEASE_REPORT_ODE_0_21_0.md) |
| 0.21.1 RC | Windows portability: CRLF launcher, полный runtime dependency closure ZIP, extracted-package cold start, обновлённая документация и презентация | `v0.21.1-rc.1`, [`RELEASE_REPORT_ODE_0_21_1.md`](../../RELEASE_REPORT_ODE_0_21_1.md) |

## Как читать Git-историю

- До public baseline 0.15.0 ранние изменения были сведены в один опубликованный
  baseline. Их последовательность сохранена в `CHANGELOG.md`, stage-документах
  и датированных reviews; отдельные старые коммиты не выдумываются.
- Начиная с 0.15.0 таблица выше связывает продуктовые версии с фактическими
  commit anchors и release reports.
- `main` — текущая интеграционная линия. ODE 0.21.1 остаётся release candidate,
  пока не выполнен физический Windows sign-off. Успешный автоматический gate
  разрешает prerelease tag `v0.21.1-rc.1`; финальный `v0.21.1` создаётся только
  после успешной приёмки на рабочем ноутбуке.

## Участники

Распределение функциональных направлений приведено в
[`CONTRIBUTORS.md`](../../CONTRIBUTORS.md): Юра Устинов — Monitoring,
Никита Боронев — Reports, Александр Мерненко — остальные части ODE, интеграция
и сопровождение проекта.
