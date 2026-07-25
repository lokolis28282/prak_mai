# Inventory Data Model Review before Stage 0.13.3

Original review status: analytical source review. Nothing described in its
**PROPOSED MODEL** section was implemented by the review itself. The review did
not change database schema, ODE business logic, production data, API or UI.

Stage 0.13.3A follow-up status (2026-07-14):

- **FACT:** the source findings and production-model facts below remain valid;
- **IMPLEMENTED:** only the offline reference/alias/canonical-naming, exact S/N
  extraction, staging, disposable candidate-DB and validation foundation;
- **PROPOSED:** candidate references and mappings still require review;
- **FUTURE STAGE:** production reference integration and historical
  receipt/issue import;
- **OPEN DECISION:** source conflicts, semantic aliases, final asset/operation
  model and production replacement approval.

Stage 0.13.3A does not retroactively make every proposed model in this document
production architecture. Normative implemented contracts are now in
[REFERENCE_DATA_ARCHITECTURE.md](REFERENCE_DATA_ARCHITECTURE.md),
[CANONICAL_NAMING.md](CANONICAL_NAMING.md),
[SERIAL_NUMBER_PRESERVATION.md](SERIAL_NUMBER_PRESERVATION.md) and
[MIGRATION_STAGING_ARCHITECTURE.md](MIGRATION_STAGING_ARCHITECTURE.md).

Stage 0.13.3A.5 follow-up status (2026-07-14):

- **IMPLEMENTED / PILOT ONLY:** a deterministic 200-row receipt selection,
  preservation-aware writer, disposable `warehouse_pilot_candidate.db`,
  provenance/quarantine/audit and marker-guarded read-only review UI;
- **FACT:** only 130 `TEXT_EXACT` primary rows create pilot cards; 70 selected
  rows are duplicate/conflict history, manual/quarantine, quantity-deferred or
  corrupted evidence. Historical issues and `БАЛАНС` are not imported;
- **FACT:** the real source provides Vegman R220 but no Vegman R200. No
  synthetic row was introduced; Huawei/xFusion conflicts remain separate
  source facts;
- **NOT PRODUCTION:** the pilot neither installs data nor changes the proposed
  production model described below;
- **FUTURE 0.13.3B / OPEN DECISION:** bulk receipt migration, case-sensitive
  production identity, reference approvals and reset/install authority still
  require explicit review and approval.

The normative pilot contract and reviewer procedure are
[MIGRATION_PILOT_ARCHITECTURE.md](MIGRATION_PILOT_ARCHITECTURE.md) and
[MIGRATION_PILOT_REVIEW_GUIDE.md](MIGRATION_PILOT_REVIEW_GUIDE.md).

Detailed source evidence is stored locally in `migration_inputs/reports/ODE_MIGRATION_AUDIT.xlsx`; management conclusions are in `migration_inputs/reports/ODE_MIGRATION_AUDIT.md`.

## FACTS FROM SOURCE

### Source authority

The warehouse workbook has eight sheets. `ПРИХОД` contains 51,003 operational receipt rows and `РАСХОД` contains 20,357 issue rows. `БАЛАНС` is a formula-derived control snapshot, not an operation source. Summary sheets are stale/filtered. `_info` contains candidate taxonomy only: four formulas return `#REF!`, all ten workbook defined names are broken, and the item-name `UNIQUE` range ends before the actual receipt data.

The DCIM workbook is structurally valid but empty. The TXT file contains 97 issue-S/N review entries; 82 are likely valid nonstandard serials, so format strictness must not be used as a deletion rule. `_info` also lists 55 unique role-like labels across thematic columns, but they have no operational assignments and are taxonomy candidates only.

### Identity facts

- Receipt S/N filled: 50,975; plausible unique normalized S/N: 49,708.
- Issue source S/N filled: 19,225; plausible unique normalized S/N: 18,795.
- Plausible union: 49,842; both sides: 18,661; receipt-only: 31,047; issue-only: 134.
- Receipt duplicate groups: 628; issue duplicate groups: 269.
- Conflicts in receipt data: 417 S/N with multiple models, 237 with multiple vendors, 344 with multiple item names.
- Forty values are item descriptions used as pseudo-S/N across 198 quantity rows. No cell is proven to contain two independent S/N.
- Numeric Excel storage affects 6,697 receipt S/N and 3,186 issue S/N. Two
  distinct values exceed Excel's 15-digit precision and recur in four source
  cells (`ПРИХОД!L19513`, `ПРИХОД!L19580`, `РАСХОД!J4826`,
  `РАСХОД!J4866`); all four are `SOURCE_CORRUPTED` without an
  independent authoritative source.
- No usable Inventory Number exists in either operations sheet.

### Operation and balance facts

`ПРИХОД.H` is movement quantity. `ПРИХОД.I` is a helper count and must not be used as per-asset quantity. Only 14,322 issue rows have numeric `РАСХОД.I`.

Formula-backed `РАСХОД.G/F/H/K/L` cannot be treated as raw truth because some formulas reference another row's S/N. Conservative reconciliation accepts static item values or rederives item/location from the current `РАСХОД.J` only when every matching receipt agrees.

This resolves 13,299 issue rows and leaves 1,023 unresolved: 614 have no current S/N, 268 map to conflicting receipt item names, and 141 have no receipt S/N. Ten additional item-resolved rows lack an unambiguous location.

The balance lists 184 item names; receipts contain 369 normalized names. All balance items occur in receipts, but 185 receipt item names are absent from the balance. Balance absence is therefore `CANNOT_RECONCILE`, never assumed zero.

### Current ODE model facts

Verified code and DDL currently use:

- `stock_receipts` as both a receipt row and the equipment/card-bearing record (`inventory/db.py`);
- `stock_issues` plus `stock_issue_allocations` for issues and allocations;
- receipt quantity minus allocations as the warehouse balance (`inventory/services/warehouse_service.py`);
- FIFO allocation behavior in `inventory/warehouse/issue_repository.py`;
- case-insensitive uniqueness for non-empty receipt S/N and Inventory Number;
- a flat `reference_values(kind, name, is_active)` mechanism;
- `audit_log` for technical audit and the existing warehouse event infrastructure;
- `inventory/warehouse/facade.py` as the write boundary.

Current limitations relevant to migration:

- a unique receipt S/N cannot represent repeated historical receipts for the same asset;
- receipt-as-card conflates an asset instance with an operation;
- no import-run/source-file/source-row/raw-value provenance model exists;
- no dedicated receipt comment, part-number/catalog relationship, equipment role, Capex/Opex, issue reason, operation source, DCIM object ID or DCIM URL exists;
- identifiers are uppercased/trimmed on current writes without retaining the original spelling;
- soft reference imports could create every raw spelling when strict references are disabled;
- current parser limits and preview truncation are below the 51,003-row receipt source;
- cable quantity validation and REAL database quantity have inconsistent semantics for fractional metres.

## PROPOSED MODEL

This section remains a design candidate, not the production schema. Stage
0.13.3A implements compatible candidate/staging representations only in a
disposable DB; it does not add these entities to `data/warehouse.db`.

### Identity and operations

Separate these concepts:

```text
AssetInstance
  serial_number
  inventory_number
  hostname (optional/current)
  catalog_item_id
  current deployment/storage state

ReceiptOperation ──< ReceiptLine/AssetLink >── AssetInstance
IssueOperation   ──< Allocation/AssetLink  >── AssetInstance
ImportRun        ──< SourceRecord/Decision >── every migrated fact
```

For serialized positions, one asset instance has one canonical S/N. Repeated historical operations refer to the same asset rather than creating duplicate cards. Quantity positions remain line-level quantities and do not fabricate S/N.

### Catalog and references

Use a related catalog model:

```text
Vendor ──< CatalogModel ──< CatalogItem >── PartNumber
                              │
                              └── PLU aliases/order attributes
```

`model`, `part_number`, human-readable item name and order position are separate concepts. Model identity should be vendor/catalog scoped; the same generic model text appears under multiple vendors.

Controlled domains to evaluate: `object_kind`, `equipment_category`, `equipment_role`, `component_type`, `cable_type`, `cable_category`, `supplier`, `project`, `unit_of_measure`, `capex_opex`, `issue_reason`, and `operation_source`.

Do not make S/N, Inventory Number, hostname, PLU, order/request/case, comments, cable connection ID, DCIM object ID or URL into reference values.

Aliases need explicit provenance and approval state:

```text
ReferenceValue
ReferenceAlias(source_value, canonical_id, rule, confidence, approved_by, source_record)
```

Case/whitespace cleanup can be proposed automatically. Semantic, legal-name and ownership aliases remain manual. In particular, Huawei/xFusion and HP/HPE must not be globally merged by spelling rules.

### Locations

Keep deployment and storage locations independent:

```text
Datacenter → Hall → Row/Zone → Rack → Rack Unit
Warehouse  → Storage Zone → Rack/Shelving → Shelf
```

Retain the raw composite location with every parsed proposal. Rack Unit is not Unit of Measure. Generic `Склад`, a blank balance bucket and template headers are not automatically real leaf locations.

### Provenance and lifecycle

Every proposed fact should retain:

- source SHA-256, filename, sheet and row;
- source field and raw value;
- normalized/proposed value and rule version;
- confidence and manual-review requirement;
- decision author/time where applicable;
- import-run ID, preview hash and confirm transaction ID;
- rollback boundary and post-import verification result.

Future writes must use the warehouse facade, a single atomic transaction, existing Audit and Timeline/Event infrastructure, and a disposable database before production approval. No second event or audit subsystem is proposed.

### Proposed sequence

```mermaid
sequenceDiagram
    participant Raw as Immutable source
    participant N as Offline normalizer
    participant R as Review queue
    participant P as Preview on disposable DB
    participant F as Warehouse facade
    participant E as Existing Audit/Timeline

    Raw->>N: Verify SHA; read only
    N->>R: Raw + proposed value + rule + confidence
    R-->>N: Approved/rejected decisions
    N->>P: Deterministic migration plan
    P-->>R: Reconciliation and validation result
    R->>F: Explicit confirm (future stage only)
    F->>F: One atomic transaction
    F->>E: Existing audit and event records
    F-->>R: Commit or complete rollback
```

## OPEN DECISIONS

1. Migrate only current state, or preserve the complete receipt/issue history?
2. Introduce `AssetInstance`, or keep receipt-as-card and accept the historical-duplicate limitation?
3. Which source is authoritative for Inventory Number?
4. What are the exact semantics of `Объект`, PLU, equipment type, case/change and order position?
5. Which reference aliases are spelling variants versus genuinely distinct legal/catalog entities?
6. How are quantity positions, serialized positions, cable length and UOM represented?
7. Are static issue locations historical movement facts, stale values or relocation evidence?
8. What is the approved location hierarchy and identity of the warehouse/datacenter parents?
9. What do the unnamed cable columns A/C/G/L/N/Q mean, and how are side lists N/Q mapped to ports?
10. Which future migration events are required within the existing event vocabulary?
11. What are the retention, rollback and approval requirements for migration provenance?

Required additional sources:

- authoritative Inventory Number export;
- non-empty DCIM export with stable object IDs;
- primary evidence for corrupted S/N and Part Number;
- warehouse/datacenter location dictionary;
- supplier/vendor legal-name authority;
- decision on current-state versus full-history scope;
- cable column specification and UOM rules.

## REJECTED OPTIONS

- Treating `БАЛАНС` as operations: it is a formula-derived and incomplete control snapshot.
- Importing cached issue lookup columns as facts: formulas can reference another row.
- Creating equipment for issue-only S/N: absence of receipt requires review, not a fabricated card.
- Dropping nonstandard S/N by format: the TXT review proves that most are likely valid.
- Automatically fixing Cyrillic/Latin confusables, leading zeros, exponent values or composite cells.
- Removing S/N uniqueness without separating asset identity from operation history.
- Combining model, Part Number, item name and order position into one reference.
- Creating every raw spelling through soft-reference behavior.
- Using `_info` as a master dictionary.
- Flattening deployment and storage into one `shelf` field.
- Mapping Rack Unit to the current `unit`/UOM concept.
- Using `delivery_lines` as a universal staging model without an approved contract.
- Using `audit_log` as the movement ledger or creating a second audit/event system.
- Letting DCIM silently overwrite populated ODE values.

## MIGRATION RISKS

| Risk | Evidence | Required control |
|---|---|---|
| Duplicate asset creation | 628 receipt S/N duplicate groups | Asset identity decision and duplicate review |
| Attribute overwrite | Hundreds of S/N/vendor/model/item conflicts | Field-level conflict policy; no silent overwrite |
| Identifier corruption | Numeric/exponent storage and >15-digit S/N | Text-only output and external corroboration |
| Wrong issue mapping | Shifted lookup formulas | Current-row S/N rederivation only when unanimous |
| False stock totals | 185 receipt item names absent from balance | Balance as control only; explicit `CANNOT_RECONCILE` |
| Reference explosion | Raw case/space/semantic variants | Approved canonical/alias layer; strict writes |
| Location misplacement | Mixed levels and punctuation variants | Preserve raw; proposal-only parser; parent identity |
| Quantity/asset confusion | Item names used as S/N | Separate serialized and quantity grain |
| Incomplete rollback | No import-run provenance today | Atomic run boundary and reversible plan |
| Scale truncation | Source exceeds current parser/preview limits | Streaming/deterministic preview with complete counts |
| Missing Inventory Number/DCIM | Zero usable values; empty DCIM file | Obtain authoritative exports before implementation |

## RECOMMENDED STAGES

### 0.13.3A — Reference Data Foundation and Migration Staging

**IMPLEMENTED:** immutable source/hash contract, exact S/N extraction,
reference/alias/canonical-name candidate models, deterministic row hashes and
rule-driven staging proposals,
disposable candidate DB and validation/reporting. No production writes and no
historical receipt/issue import.

This Stage does not close semantic/manual decisions. Candidate auto-approval is
limited to safe Unicode/case/whitespace spelling variants.

### 0.13.3B — Historical Receipt Migration

**FUTURE STAGE:** approve the receipt column map and reference subset; resolve
receipt S/N duplicates/corruption; build a complete read-only preview with
source-row provenance; trial on a disposable DB. Do not import issues or use
the balance snapshot as operations.

### 0.13.3C — Historical Issue Migration

**FUTURE STAGE:** map only issues supported by approved receipt identity,
preserve unresolved issue-only rows for review and build allocations without
negative stock or inferred cards.

### 0.13.3D — Reconciliation and manual closure

**FUTURE STAGE:** resolve remaining S/N, item/vendor/model, quantity/UOM,
supplier, alias and location conflicts. Compare the operation-derived result
with balance only as a control snapshot.

### 0.13.3E — Production model/ADR and import workflow

**FUTURE STAGE:** approve identity/catalog/location/reference/provenance schema,
events, access control, preview hash and atomic confirm contract through the
Warehouse facade. Candidate tables must not be copied into production by
implication.

### 0.13.3F — Disposable full trial

**FUTURE STAGE:** run the approved complete plan on a disposable clone; verify
security transfer, events/audit, balance, performance, rollback and full UI/API
gate.

### 0.13.3G — Separate production replacement approval

**FUTURE STAGE:** execute the independently reviewed backup/reset/swap plan only
after explicit approval of the exact candidate SHA. The old DB remains in
`release_backups/migration/` with manifest and hashes.
