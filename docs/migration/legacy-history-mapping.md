# Legacy history field mapping

Статус: **APPROVED — ODE 0.13 architecture baseline**

Primary source — migration_full_reconciliation joined to staging/source files,
serial cells and warnings. stock receipts/issues are validation only.

| Target field | Source | Transform / quality |
|---|---|---|
| source_file_id | reconciliation.source_file → migration_source_files | Resolve immutable source and verify SHA/size |
| source_sheet | source_sheet | Exact text |
| source_row_number | source_row | Must be >0 |
| source_row_key | operation_kind + source_row_hash | Versioned canonical key |
| source_row_sha256 | source_row_hash | Decode 64-char hex |
| event_type | operation_kind | RECEIPT/ISSUE only |
| serial_raw | source_serial_value; serial cell evidence | Exact raw/display evidence; never numeric coercion |
| serial_key | normalized_match_value | Recompute conservative v1; compare old value, record warning on difference |
| inventory_number_raw | source_inventory_number/raw payload | Exact source string |
| part_number_raw | part_number/raw payload | Exact |
| vendor_raw/model_raw | vendor/model | Exact |
| source_item_name_raw | source_item_name | Exact |
| performed_by_name_raw | raw_payload.responsible | Exact raw including blank |
| performed_by_quality | responsible | Blank→MISSING; approved name mapping→EXACT; numeric/code→CODE_ONLY; invalid→CORRUPTED |
| accepted_by_name_raw | receipt responsible only if source semantics proves receiver | Otherwise NULL; never infer counterparty |
| occurred_at_us | source date fields + raw cell/workbook | Set only EXACT or ESTIMATED with basis |
| date_raw | source_operation_date_raw | Exact raw |
| date_quality | old status + validation | Rules below |
| estimation_basis | explicit reviewed rule | Required only ESTIMATED |
| comment_raw | raw_payload.comments | Exact |
| quantity_raw | quantity/raw_payload.quantity | Exact string, no balance arithmetic |
| location_raw | shelf/raw_payload.warehouse_location | Exact |
| equipment link | legacy_history_equipment_links | Не создается при base migration; позднее только EXACT/REVIEWED additive resolution |
| raw_payload_json | raw_payload + serial evidence | Canonical wrapper, raw strings unchanged |
| normalized_payload_json | normalized_payload | Stored as migration interpretation, not raw truth |
| record_status | migration decision | IMPORTED, QUARANTINED or EXCLUDED; every source row still gets one event |

## Date mapping

| Current status | Count at audit | Target |
|---|---:|---|
| NUMERIC_DATE_EXACT_1900_EPOCH | 49 094 | EXACT only after workbook epoch/raw-cell verification; otherwise CORRUPTED |
| SOURCE_DATE_UNPROVEN | 22 266 | CORRUPTED because raw exists but parsed date is empty |
| Empty raw in future delta | variable | MISSING |
| Explicit approved estimate | none baseline | ESTIMATED + basis/actor |

Нельзя использовать file mtime, row order или neighboring row date как
ESTIMATED без отдельного approved transformation rule.

## Final status

Все 71 360 source rows остаются архивными событиями. final_status
EXACT_DUPLICATE, CONFLICT_HISTORY_ONLY, OPENING_STATE_CREATED,
NUMERIC_PROVISIONAL_* и QUANTITY_DEFERRED становится warning/classification, но
не исключает source event и не создает balance.

QUARANTINED/SOURCE_CORRUPTED_REJECTED получают record_status=QUARANTINED и
доступны auditor search с warning.

EXCLUDED используется только для явно классифицированной source row, которая
не является складским событием, но должна остаться в count proof и provenance.
В audit baseline таких rows 0; значение не означает физическое удаление.

## FIO limitation

Audit baseline показывает 48 451 пустых responsible rows. Нельзя выполнить
обещание «показать ФИО» там, где source его не содержит. Lossless requirement:
показать raw/quality и отсутствие данных. Numeric codes могут быть обогащены
только утвержденным personnel mapping, см. OPEN-001.

## Validation

- one source row → one event;
- all 5 source file manifests verified;
- all serial cell rows linked or quarantined;
- warning source counts accounted;
- no source date synthesized;
- raw payload SHA stable before/after transform;
- random and risk-based sample rendered against original workbook;
- no target event FK to balance/ledger;
- rerun produces identical event public IDs and checksums.
