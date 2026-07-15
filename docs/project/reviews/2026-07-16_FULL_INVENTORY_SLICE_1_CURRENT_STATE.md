# FULL Inventory Slice 1 — Current State

Дата: 2026-07-16.

Slice 1 заканчивается на external XLSX Preview и статусе
`READY_FOR_APPROVAL` либо `REVIEW_REQUIRED`. Approval, candidate database,
snapshot, initial baseline и publish в этот Slice не входят.

## Catalog validation limitation

Catalog/model ambiguity и validation новых единиц оборудования отложены до
Slice 2 / Equipment integration. В текущем runtime отсутствует утверждённый
Equipment Query Port и target Equipment identity, поэтому Slice 1 намеренно:

- не связывает строки по Vendor/Model/Description;
- не утверждает, что Catalog/Model validation полностью выполнена;
- не создаёт Equipment/Catalog records;
- сохраняет только существующее exact historical S/N evidence;
- публикует в Preview summary marker `catalog_validation: "DEFERRED"`.

Совпадение Vendor/Model не является доказательством identity и не может
автоматически перевести строку в baseline. Equipment linking потребует
отдельного утверждённого контракта и остаётся за границей Slice 1.
