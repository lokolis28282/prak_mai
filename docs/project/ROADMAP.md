# Roadmap

Roadmap разделён по продуктовым направлениям. Номера исторических Stage не
переиспользуются как общий порядок работ.

## Lane W — рабочий Warehouse

### W0. Stabilization gate — завершён 2026-07-15

- warning-clean unit/contract/API suite;
- module/frontend audits;
- browser smoke на временной byte-copy рабочей БД;
- проверка login, search, card, receipt, issue, balance, deliveries,
  inventory-number Preview/Confirm и references;
- неизменность production SHA при тестах;
- актуальный runbook и manual QA.

Результат: browser E2E и 394-test full suite PASS; рабочая БД не изменена.
Evidence: `reviews/2026-07-15_WAREHOUSE_OPERATIONAL_ACCEPTANCE.md`.

### W1. Operational acceptance — safety workflow реализован

- выполнить финальный owner walkthrough по
  `MANUAL_TESTING_WAREHOUSE_STABILIZATION.md` на рабочем ноутбуке;
- закрыть подтверждённые defects без cosmetic redesign;
- определить безопасные correction/reversal workflows;
- проверить backup/restore drill на копиях;
- зафиксировать release candidate и data-separation gate.

Scanner Operations 0.13.4 реализован как проверяемый compatibility slice:
строгий массовый расход и пары `компонент → сервер`. Следующий W1 slice —
явная граница legacy history / `NOT_INITIALIZED`, затем FULL inventory Preview
и approval baseline. До baseline scanner mutations используются только в
disposable test contour.

ODE 0.14 добавил следующую цепочку без изменения рабочей БД:
`NOT_INITIALIZED → FULL session → XLSX → Preview → resolutions → revalidation
→ READY_FOR_APPROVAL → disposable target-schema candidate`. Candidate создаёт
initial snapshot и projection и проходит target domain invariants. Реальный
approval/publish/cutover остаётся отдельным controlled change с backup,
остановкой writers и atomic replace.

### W2. Server-readiness design

- process owner и single-writer policy;
- server paths, service account и filesystem permissions;
- secrets/bootstrap/password reset;
- backup retention и restore acceptance;
- maintenance/migration procedure;
- concurrency and network/filesystem preflight;
- deployment runbook без включения локальной/test DB в code release.

## Lane T — Target ODE 0.13 platform

1. Получить independent post-fix PASS Platform Stage 0.13.1.
2. Утвердить Argon2id library/profile и bootstrap policy.
3. Реализовать security/audit/references вертикальными slices.
4. Реализовать equipment identity, Preview, FULL baseline, ledger и projection.
5. Выполнить отдельный rehearsal/cutover. V001..V008 не применять напрямую к
   текущей Warehouse DB.

Этот lane не должен ломать рабочий Warehouse до утверждённого cutover.

## Lane M — Monitoring

Сначала inventory/hash/diff второй копии/ветки коллеги, dependency map и
integration plan. Перенос каталогов автоматически запрещён. Целевая связь:
`Monitoring → Equipment query port`.

## Lane R/Wiki — Reports и знания

Reports интегрируется через WarehouseEventReader/application queries. Wiki
развивается отдельной веткой/changeset. Оба направления не блокируют W0/W1.
