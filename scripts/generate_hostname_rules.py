#!/usr/bin/env python3
"""Generate monitoring hostname routing rules from the approved Excel sources."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from inventory.migration.xlsx_cells import column_index, iter_xlsx_cells  # noqa: E402
from inventory.monitoring.hostname_routing import validate_rules_payload  # noqa: E402


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "monitoring"
TECH_OUTPUT_NAME = "Hostname Tech.json"
DIGITAL_OUTPUT_NAME = "Hostname Digital.json"
DIGITAL_SHEET_NAME = "Технические имена"
DIGITAL_HOSTNAME_COLUMN = 6
DIGITAL_HOSTNAME_HEADER = "X5T_Support_HostName"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
RECIPIENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+@-]*$")
HOSTNAME_PATTERN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._*?-]*$")


@dataclass
class GenerationStats:
    processed_rows: int = 0
    unique_hostnames: int = 0
    skipped_empty: int = 0
    skipped_invalid: int = 0
    duplicates_merged: int = 0


@dataclass(frozen=True)
class _Worksheet:
    """Small values-only worksheet adapter backed by the safe OOXML reader."""

    title: str
    rows: dict[int, dict[int, str]]

    def iter_rows(
        self,
        *,
        min_row: int = 1,
        max_row: int | None = None,
        min_col: int = 1,
        max_col: int | None = None,
        values_only: bool = False,
    ) -> Iterable[tuple[str | None, ...]]:
        if not values_only:
            raise ValueError("Monitoring generator supports values_only rows")
        final_row = max(self.rows, default=0) if max_row is None else max_row
        inferred_column = max(
            (max(values, default=0) for values in self.rows.values()),
            default=0,
        )
        final_column = inferred_column if max_col is None else max_col
        if final_row < min_row or final_column < min_col:
            return
        for row_number in range(min_row, final_row + 1):
            values = self.rows.get(row_number, {})
            yield tuple(values.get(column) for column in range(min_col, final_column + 1))


class _Workbook:
    """Read-only workbook facade; no optional spreadsheet dependency is needed."""

    def __init__(self, path: Path) -> None:
        rows_by_sheet: dict[str, dict[int, dict[int, str]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        order: list[str] = []
        for cell in iter_xlsx_cells(path):
            if cell.source_sheet not in rows_by_sheet:
                order.append(cell.source_sheet)
            rows_by_sheet[cell.source_sheet][cell.source_row][
                column_index(cell.source_column)
            ] = cell.source_display_value
        if not order:
            raise ValueError("XLSX не содержит непустых листов")
        self._worksheets = {
            title: _Worksheet(title, dict(rows_by_sheet[title])) for title in order
        }
        self.sheetnames = list(order)
        self.active = self._worksheets[order[0]]

    def __getitem__(self, name: str) -> _Worksheet:
        return self._worksheets[name]

    def close(self) -> None:
        return None


def load_workbook(path: Path, *, read_only: bool, data_only: bool) -> _Workbook:
    if not read_only or not data_only:
        raise ValueError("Monitoring generator opens XLSX only read-only/data-only")
    return _Workbook(path)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"[\x00-\x20\x7f]+", " ", text).strip()


def normalize_header(value: Any) -> str:
    text = clean_text(value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-я]+", " ", text)).strip()


def recipient_key(value: Any) -> str:
    key = clean_text(value).casefold()
    return key[:-6] if key.endswith("@x5.ru") else key


def dedupe(values: Iterable[Any], *, recipient_identity: bool = False) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_text(value)
        if not item:
            continue
        key = recipient_key(item) if recipient_identity else item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def split_recipients(value: Any) -> list[str]:
    text = str(value or "")
    emails = EMAIL_RE.findall(text)
    if emails:
        return dedupe(emails, recipient_identity=True)
    parts = re.split(r"[\n,;]+", text)
    return dedupe(
        (part for part in parts if RECIPIENT_RE.fullmatch(clean_text(part))),
        recipient_identity=True,
    )


def split_hostname_examples(value: Any) -> tuple[list[str], list[str]]:
    valid: list[str] = []
    invalid: list[str] = []
    for raw in re.split(r"[\n,;]+", str(value or "")):
        item = clean_text(raw).lstrip("•- ")
        if not item:
            continue
        if len(item) <= 128 and HOSTNAME_PATTERN_RE.fullmatch(item):
            valid.append(item)
        else:
            invalid.append(item)
    return dedupe(valid), invalid


def find_header(worksheet: Any, aliases: Iterable[str], *, max_rows: int = 60, max_cols: int = 40) -> tuple[int, int]:
    normalized_aliases = {normalize_header(alias) for alias in aliases}
    for row_index, row in enumerate(
        worksheet.iter_rows(min_row=1, max_row=max_rows, min_col=1, max_col=max_cols, values_only=True),
        1,
    ):
        for column_index, value in enumerate(row, 1):
            if normalize_header(value) in normalized_aliases:
                return row_index, column_index
    raise ValueError(f"Не найден столбец: {', '.join(aliases)}")


def extract_global_cc(worksheet: Any, main_header_row: int) -> list[str]:
    marker_row, marker_column = find_header(
        worksheet,
        ("Всегда добавляем", "Всегда добавлять"),
        max_rows=max(main_header_row, 30),
    )
    values: list[str] = []
    stop_row = main_header_row - 1 if marker_row < main_header_row else marker_row + 200
    for row in worksheet.iter_rows(
        min_row=marker_row + 1,
        max_row=stop_row,
        min_col=marker_column,
        max_col=marker_column,
        values_only=True,
    ):
        values.extend(split_recipients(row[0]))
    return dedupe(values, recipient_identity=True)


def without_recipients(values: Iterable[str], excluded: Iterable[str]) -> list[str]:
    excluded_keys = {recipient_key(value) for value in excluded}
    return [value for value in dedupe(values, recipient_identity=True) if recipient_key(value) not in excluded_keys]


def _append_unique(existing: list[str], incoming: Iterable[str]) -> None:
    merged = dedupe([*existing, *incoming], recipient_identity=True)
    existing[:] = merged


def build_tech_payload(
    path: Path,
    cc_exclusions: Iterable[str] = (),
) -> tuple[dict[str, Any], GenerationStats, list[str]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.active
    recipients_header = find_header(worksheet, ("адресаты", "адресат"))
    naming_header = find_header(worksheet, ("Примеры нейминга", "пример нейминга"))
    owner_header = find_header(worksheet, ("Технический владелец",))
    header_rows = {recipients_header[0], naming_header[0], owner_header[0]}
    if len(header_rows) != 1:
        raise ValueError("Заголовки Tech-таблицы находятся в разных строках")
    header_row = header_rows.pop()
    global_cc = extract_global_cc(worksheet, header_row)
    normalized_exclusions = dedupe(cc_exclusions, recipient_identity=True)
    tech_cc = without_recipients(global_cc, normalized_exclusions)
    rules_by_pattern: dict[str, dict[str, Any]] = {}
    stats = GenerationStats()
    invalid_examples: list[str] = []

    max_column = max(recipients_header[1], naming_header[1], owner_header[1])
    for row_number, row in enumerate(
        worksheet.iter_rows(min_row=header_row + 1, min_col=1, max_col=max_column, values_only=True),
        header_row + 1,
    ):
        owner = clean_text(row[owner_header[1] - 1])
        recipients_value = row[recipients_header[1] - 1]
        naming_value = row[naming_header[1] - 1]
        if not any(clean_text(value) for value in (owner, recipients_value, naming_value)):
            stats.skipped_empty += 1
            continue
        stats.processed_rows += 1
        examples, invalid = split_hostname_examples(naming_value)
        invalid_examples.extend(f"строка {row_number}: {value}" for value in invalid)
        stats.skipped_invalid += len(invalid)
        to = split_recipients(recipients_value)
        if not examples or not to:
            if examples and not to:
                stats.skipped_invalid += len(examples)
                invalid_examples.append(f"строка {row_number}: нет адресатов")
            continue
        is_salt = normalize_header(owner) == "salt"
        for example in examples:
            pattern = example if any(character in example for character in "*?") else f"{example}*"
            key = pattern.casefold()
            existing = rules_by_pattern.get(key)
            if existing is None:
                rules_by_pattern[key] = {
                    "hostname_pattern": pattern,
                    "match_type": "wildcard",
                    "project": "Salt" if is_salt else "X5Tech",
                    "is_salt": is_salt,
                    "to": to.copy(),
                    "cc": tech_cc.copy(),
                    "source_owner": [owner] if owner else [],
                    "source_rows": [row_number],
                }
                continue
            stats.duplicates_merged += 1
            _append_unique(existing["to"], to)
            existing["source_owner"] = dedupe([*existing["source_owner"], owner])
            if row_number not in existing["source_rows"]:
                existing["source_rows"].append(row_number)
            if is_salt:
                existing["project"] = "Salt"
                existing["is_salt"] = True

    rules = list(rules_by_pattern.values())
    stats.unique_hostnames = len(rules)
    payload = {
        "version": 1,
        "source_file": path.name,
        "source_sheet": worksheet.title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cc_exclusions": normalized_exclusions,
        "rules": rules,
    }
    return payload, stats, global_cc


def _digital_header_row(worksheet: Any) -> int:
    for row_number, row in enumerate(
        worksheet.iter_rows(
            min_row=1,
            max_row=50,
            min_col=DIGITAL_HOSTNAME_COLUMN,
            max_col=DIGITAL_HOSTNAME_COLUMN,
            values_only=True,
        ),
        1,
    ):
        if normalize_header(row[0]) == normalize_header(DIGITAL_HOSTNAME_HEADER):
            return row_number
    raise ValueError(
        f"На листе {DIGITAL_SHEET_NAME!r} в столбце F не найден "
        f"заголовок {DIGITAL_HOSTNAME_HEADER!r}"
    )


def build_digital_payload(
    path: Path,
    global_cc: Iterable[str],
    default_to: Iterable[str],
) -> tuple[dict[str, Any], GenerationStats]:
    normalized_to = dedupe(default_to, recipient_identity=True)
    if not normalized_to:
        raise ValueError("Для Digital требуется хотя бы один --digital-default-to")
    workbook = load_workbook(path, read_only=True, data_only=True)
    if DIGITAL_SHEET_NAME not in workbook.sheetnames:
        workbook.close()
        raise ValueError(f"В Digital-таблице не найден лист {DIGITAL_SHEET_NAME!r}")
    worksheet = workbook[DIGITAL_SHEET_NAME]
    try:
        header_row = _digital_header_row(worksheet)
    except ValueError:
        workbook.close()
        raise
    stats = GenerationStats()
    hostnames: list[str] = []
    seen: set[str] = set()
    for row in worksheet.iter_rows(
        min_row=header_row + 1,
        min_col=DIGITAL_HOSTNAME_COLUMN,
        max_col=DIGITAL_HOSTNAME_COLUMN,
        values_only=True,
    ):
        raw = row[0]
        hostname = clean_text(raw)
        if not hostname:
            stats.skipped_empty += 1
            continue
        stats.processed_rows += 1
        if len(hostname) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", hostname):
            stats.skipped_invalid += 1
            continue
        key = hostname.casefold()
        if key in seen:
            stats.duplicates_merged += 1
            continue
        seen.add(key)
        hostnames.append(hostname)

    stats.unique_hostnames = len(hostnames)
    default_cc = without_recipients(global_cc, normalized_to)
    payload = {
        "version": 1,
        "source_file": path.name,
        "source_sheet": worksheet.title,
        "source_column": "F",
        "source_header": DIGITAL_HOSTNAME_HEADER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "default_to": normalized_to,
        "default_cc": default_cc,
        "hostnames": hostnames,
    }
    workbook.close()
    return payload, stats


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Генерация JSON-правил адресации ODE из Excel")
    parser.add_argument("--tech-source", type=Path, required=True)
    parser.add_argument("--digital-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--tech-cc-exclusion",
        action="append",
        default=[],
        help="локальный адресат, исключаемый из Tech CC; флаг можно повторять",
    )
    parser.add_argument(
        "--digital-default-to",
        action="append",
        default=[],
        help="локальный адресат Digital To; требуется хотя бы один, флаг можно повторять",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    missing = [path for path in (args.tech_source, args.digital_source) if not path.is_file()]
    if missing:
        for path in missing:
            print(f"Файл не найден: {path}", file=sys.stderr)
        return 2
    try:
        tech_payload, tech_stats, global_cc = build_tech_payload(
            args.tech_source,
            cc_exclusions=args.tech_cc_exclusion,
        )
        digital_payload, digital_stats = build_digital_payload(
            args.digital_source,
            global_cc,
            args.digital_default_to,
        )
        for payload, label in ((tech_payload, "Tech"), (digital_payload, "Digital")):
            validation_error = validate_rules_payload(payload, label)
            if validation_error:
                raise ValueError(f"Сгенерированный {label} JSON отклонён: {validation_error}")
        write_json(args.output_dir / TECH_OUTPUT_NAME, tech_payload)
        write_json(args.output_dir / DIGITAL_OUTPUT_NAME, digital_payload)
    except (OSError, ValueError) as error:
        print(f"Генерация не выполнена: {error}", file=sys.stderr)
        return 1

    print(
        f"Tech: обработано строк {tech_stats.processed_rows}, "
        f"уникальных шаблонов {tech_stats.unique_hostnames}, "
        f"пропущено {tech_stats.skipped_empty + tech_stats.skipped_invalid}, "
        f"объединено дублей {tech_stats.duplicates_merged}"
    )
    print(
        f"Digital: обработано строк {digital_stats.processed_rows}, "
        f"уникальных hostname {digital_stats.unique_hostnames}, "
        f"пропущено {digital_stats.skipped_empty + digital_stats.skipped_invalid}, "
        f"объединено дублей {digital_stats.duplicates_merged}"
    )
    print(f"Создано: {args.output_dir / TECH_OUTPUT_NAME}")
    print(f"Создано: {args.output_dir / DIGITAL_OUTPUT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
