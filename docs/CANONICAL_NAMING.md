# Canonical Naming — Stage 0.13.3A / 0.13.3A.5

## Warehouse runtime naming contract

Equipment Card показывает `canonical_name` рядом с неизменённым `source_name`.
Canonical rename/merge не изменяет `serial_number`, `source_serial_value`,
`raw_xml_value`, identity/match keys или reconciliation. Part Number выводится
отдельно, когда присутствует в migration identity.

Vendor и model — раздельные структурированные поля. Model разрешён только в
scope выбранного vendor: Vegman R200 и R220 различны, Huawei и xFusion не
объединяются. Placeholder (`?`, `N/A`, `Unknown`, пустое значение) не становится
canonical vendor/model/supplier; UI отображает человекопонятный fallback, не
создавая reference value.

Дата: 2026-07-14.

## Status

- **FACT:** source item names are inconsistent and cannot be identity.
- **IMPLEMENTED:** deterministic candidate-name builders exist in the offline
  migration layer.
- **PROPOSED:** generated names and structured candidates require review before
  becoming production master data.
- **IMPLEMENTED / PILOT ONLY (0.13.3A.5):** generated candidate names are shown
  next to source names and written to imported pilot cards in a disposable DB.
- **FUTURE STAGE:** production receipt UI and persisted catalog will use only
  approved structured values.

## Purpose

Canonical naming provides one predictable display style while preserving the
source text. It does not merge assets or models and does not alter S/N.

Every proposal retains:

- `source_item_name`;
- `canonical_item_name`;
- vendor, model and Part Number as separate fields;
- object kind, category and equipment/component type;
- `normalization_rule` and rule version;
- confidence and `requires_manual_review`;
- source file/sheet/row provenance in staging.

`canonical_item_name` is presentation. It may be recalculated when display
rules improve; S/N remains the serialized entity identity.

## Structured input first

The builder never treats the complete raw item name as an opaque new canonical
record when structured fields are available. In the Stage 0.13.3A candidate,
these are proposed source-derived fields rather than production-approved
references. Inputs are resolved in this order:

1. resolved/proposed object kind/type;
2. source-derived vendor candidate;
3. source-derived model candidate in vendor scope;
4. source Part Number where appropriate and safely text-preserved;
5. a structured primary characteristic when authoritative;
6. raw item text only as provenance/fallback proposal.

Unknown or conflicting fields make the proposal reviewable; they do not trigger
semantic guessing.

## Equipment format

Base format:

```text
<Type display name> <Vendor display name> <Model display name>
```

Examples:

- `Сервер Dell PowerEdge R650`;
- `Сервер Dell PowerEdge R740`;
- `Сервер Vegman R200`;
- `Сервер Vegman R220`;
- `Коммутатор Huawei CE6865`;
- `Система хранения данных Huawei OceanStor 5500`.

R200 and R220 remain separate model candidates. A common vendor or product
family never authorizes model merging.

The examples are naming-rule examples, not source inventory claims. **FACT:**
the current approved source contains Vegman R220 but no Vegman R200. The pilot
records `VEGMAN_R200_UNAVAILABLE_FROM_SOURCE` and never fabricates a source row
or pilot card to satisfy the example. A synthetic unit fixture still proves
that the builder keeps R200 and R220 distinct.

## Component format

Base format:

```text
<Component type> <Vendor> <Model or Part Number> <Primary characteristic>
```

Examples:

- `Оперативная память Samsung 32 GB DDR4`;
- `SSD Intel D7-P5500 7.68 TB`;
- `Сетевой адаптер Intel X710`.

Model and Part Number remain distinct even if only one is displayed. Capacity,
interface, speed or form factor may be a primary characteristic only when its
source field and unit are unambiguous. Free-text regex guesses remain manual
review proposals.

## Token rules

**IMPLEMENTED safe presentation operations:**

- Unicode NFKC for reference/display matching;
- trim outer whitespace;
- collapse repeated whitespace separators between display tokens;
- use approved display casing from the canonical reference;
- omit absent optional tokens without leaving repeated spaces.

**Forbidden automatic operations:**

- transliteration or Cyrillic/Latin confusable replacement;
- typo repair;
- removal of meaningful hyphens or punctuation from model/Part Number;
- model-family inference from a source name;
- capacity/unit conversion;
- vendor ownership inference, including Huawei/xFusion or HP/HPE;
- using a generated name as the unique key for an asset.

The S/N normalization policy is stricter and is defined only in
[SERIAL_NUMBER_PRESERVATION.md](SERIAL_NUMBER_PRESERVATION.md).

## Missing and conflicting values

| Condition | Candidate result |
|---|---|
| Resolved type + vendor + model | Generate an equipment-name proposal; candidate confidence depends on type inference |
| Type + vendor + Part Number, no model | Generate reviewable component/catalog proposal |
| Missing vendor or model | Preserve source text, generate only a partial proposal, require review |
| Vendor/model conflict for one S/N | Do not choose by frequency; create conflict |
| Distinct models differ only by digits/suffix | Keep distinct; never fuzzy-merge |
| Raw name contains multiple entities | Preserve raw value and require manual decomposition |
| `unknown`/`other` selected | Use explicit display value; never fabricate vendor/model |

## Algorithm contract

Conceptually:

```text
canonical_name = join_nonempty(
    resolved_type.display_name,
    vendor_candidate.display_name,
    model_candidate.display_name or text_part_number,
    structured_primary_characteristic,
)
```

The result includes a rule identifier/version so that staging can reproduce
which builder generated it. Recalculation produces a new proposal; it never
silently rewrites an approved source decision.

## Receipt UX

**FUTURE STAGE:** dependent selectors will propose models for the selected
vendor, show the generated name before save, retain the engineer's original
text and route `Other / unknown` to review. Shelf is optional placement data and
does not participate in naming or identity.

## Stage 0.13.3A.5 pilot behavior

The pilot preserves and displays two independent values:

- `source_item_name` — exact source description/provenance;
- `canonical_item_name` — Stage 0.13.3A structured proposal used as card
  display inside the disposable pilot.

The selector does not recalculate a missing semantic decision by fuzzy matching.
A row with insufficient type/vendor/model evidence is routed to
`MANUAL_REVIEW` or carries `REFERENCE_VALUE_UNRESOLVED`; it cannot silently
create a production reference. Huawei and xFusion remain separate vendor
tokens. Conflict-history rows retain every source vendor/model/item variant but
do not create another card.

Pilot card review must compare source and canonical names side by side. Approval
of the 200-row sample is evidence about the rule behavior only; it is not a
bulk rename, production catalog approval or Stage 0.13.3B import authorization.

## OPEN DECISIONS

- Approved Russian display labels and capitalization for every domain value.
- Which component characteristics have authoritative structured columns.
- Whether Part Number is displayed when a model is also present.
- Catalog-family layer between vendor/model/catalog item.
- Versioning and approval workflow for production name recalculation.
