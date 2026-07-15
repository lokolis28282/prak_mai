# OPEN DECISIONS ODE 0.13

Статус: **OPEN REGISTER — DDL-ВЛИЯЮЩИЕ РЕШЕНИЯ ЗАМОРОЖЕНЫ**
Правило: сюда попадают только решения, которые нельзя честно вывести из
утвержденных бизнес-инвариантов или проверенного source.

## Summary

Архитектурных blocker, меняющих PK, UNIQUE, FK, CHECK либо
snapshot/ledger/history/identity/UoW model, не осталось. Они закрыты ADR-006,
ADR-007 и ADR-010..012 и выражены approved DDL V001..V008. Открытые пункты
ниже относятся к data curation, эксплуатации или cutover acceptance; они не
делают DDL неоднозначным. Комплект утверждён как ODE 0.13 architecture
baseline; Stage 0.13.1 начинается только после отдельного пользовательского
подтверждения.

| ID | Blocker scope |
|---|---|
| OPEN-001 | Non-blocker implementation; blocker for enriched legacy FIO |
| OPEN-002 | Data blocker for reference migration/first baseline; not DDL |
| OPEN-003 | Operations blocker for first baseline/cutover; not DDL |
| OPEN-004 | Blocker for publish implementation acceptance |
| OPEN-005 | Blocker for cutover/cleanup |
| OPEN-006 | Blocker for performance acceptance |
| OPEN-007 | Non-blocker ODE 0.13 |
| OPEN-008 | Non-blocker release; separate security project if required |
| OPEN-009 | Non-blocker core; blocker only if monitoring is release scope |

## OPEN-001 — Legacy personnel codes

- Вопрос: являются ли numeric responsible values employee IDs, и существует ли
  authoritative code→ФИО directory?
- Варианты: approved mapping; сохранить CODE_ONLY; speculative decode.
- Рекомендация: сохранить raw CODE_ONLY; применить mapping только с owner/hash.
- Последствия: часть history не покажет ФИО, но не будет ложной.
- Утверждает: business/data owner.
- Blocker: non-blocker migration preservation; blocker only for claim of full
  name enrichment.

## OPEN-002 — Reference/catalog approval

- Вопрос: какие 433 candidate references, 408 pending aliases и 358 pending
  catalog items становятся approved?
- Варианты: ручная curation; authoritative DCIM/catalog import; auto-approve.
- Рекомендация: ручная/authoritative mapping; auto-approve запретить.
- Последствия: unresolved items блокируют inventory approval.
- Утверждает: warehouse/catalog data owner.
- Blocker: first baseline and corresponding migration stage.

## OPEN-003 — Warehouse/location master and freeze owner

- Вопрос: кто утверждает hierarchy склада/location и организационно запрещает
  physical movements на период count?
- Варианты: warehouse manager; DCIM owner; mixed ownership.
- Рекомендация: warehouse manager owns codes/freeze, DCIM only proposal source.
- Последствия: без signed hierarchy/freeze snapshot не имеет point-in-time.
- Утверждает: warehouse operations owner.
- Blocker: first baseline/cutover.

## OPEN-004 — Supported desktop platforms

- Вопрос: обязательны ли одновременно Windows 11 и macOS, нужен ли Linux local?
- Варианты: Windows+macOS; Windows only; all three.
- Рекомендация: Windows 11 + supported macOS local profiles; Linux future.
- Последствия: atomic replace/lock/backup drills нужны на каждой платформе.
- Утверждает: product/operations owner.
- Blocker: publish implementation acceptance, не domain/DDЛ.

## OPEN-005 — Archive storage and retention

- Вопрос: где хранятся две verified old DB/source copies и сколько дольше 10 лет?
- Варианты: encrypted NAS+offline; corporate backup; local-only.
- Рекомендация: corporate encrypted primary + offline second, минимум 10 лет.
- Последствия: cost/access/recovery ownership.
- Утверждает: data/security/operations owners.
- Blocker: cutover and cleanup.

## OPEN-006 — Deployment performance profile

- Вопрос: соответствует ли реальная минимальная машина reference profile?
- Варианты: принять профиль; измерить и заменить; несколько profiles.
- Рекомендация: измерить целевой Windows workstation и утвердить один minimum.
- Последствия: p95 gates могут быть подтверждены только после этого.
- Утверждает: product/operations owner.
- Blocker: performance acceptance, не architecture implementation.

## OPEN-007 — Future DCIM direction

- Вопрос: DCIM будет source, consumer или bidirectional integration?
- Варианты: consumer; proposal source; bidirectional.
- Рекомендация: вне 0.13; будущий proposal source через versioned API, без
  direct DB и без изменения domain authority.
- Последствия: возможно outbox/API adapter позже.
- Утверждает: product/DCIM owner.
- Blocker: non-blocker.

## OPEN-008 — Git history containing data artifacts

- Вопрос: требуется ли purge historical DB/ZIP из Git history?
- Варианты: оставить restricted history; rewrite and rotate; repository move.
- Рекомендация: отдельная security assessment; current cleanup только прекращает
  tracking.
- Последствия: history rewrite affects all clones and hashes.
- Утверждает: security/repository owner.
- Blocker: non-blocker 0.13 runtime, security action if exposure confirmed.

## OPEN-009 — Monitoring release scope

- Вопрос: входит ли operational monitoring UI в первый ODE 0.13 release?
- Варианты: health/diagnostics only; full monitoring module.
- Рекомендация: health/diagnostics only; full monitoring later.
- Последствия: не смешивать monitoring tables with warehouse truth.
- Утверждает: product owner.
- Blocker: non-blocker core.
