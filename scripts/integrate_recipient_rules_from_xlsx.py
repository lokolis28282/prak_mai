#!/usr/bin/env python3
"""Derive conservative monitoring recipient rules from confirmed XLSX rows."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from inventory.migration.xlsx_cells import column_index, iter_xlsx_cells  # noqa: E402
from inventory.monitoring.hostname_routing import (  # noqa: E402
    DIGITAL_RULES_NAME,
    TECH_RULES_NAME,
    normalize_hostname,
    normalize_information_system,
    normalize_project,
    validate_rules_payload,
)


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
PLACEHOLDERS = {"", "-", "—", "none", "n/a", "na", "модель:", "нет"}
MIN_SUPPORT = {
    "hostname": 3,
    "project": 3,
    "information_system": 3,
    "combined": 2,
}


@dataclass(frozen=True)
class Example:
    row_number: int
    hostname: str
    hostname_norm: str
    hostname_mask: str
    information_system: str
    information_system_norm: str
    project: str
    project_norm: str
    comment: str
    recipients: tuple[str, ...]
    route_project: str

    @property
    def target(self) -> tuple[str, tuple[str, ...]]:
        return self.route_project, self.recipients


@dataclass(frozen=True)
class Candidate:
    rule_type: str
    hostname_pattern: str
    dcim_project: str
    information_system: str
    route_project: str
    recipients: tuple[str, ...]
    support: int
    correct: int
    conflicts: int
    confidence: float
    source_rows: tuple[int, ...]

    @property
    def condition_key(self) -> tuple[str, str, str]:
        return (
            self.hostname_pattern.casefold(),
            normalize_project(self.dcim_project),
            normalize_information_system(self.information_system),
        )

    @property
    def target(self) -> tuple[str, tuple[str, ...]]:
        return self.route_project, self.recipients


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_header(value: Any) -> str:
    text = clean_text(value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-я]+", " ", text)).strip()


def useful_project(value: Any) -> tuple[str, str]:
    display = clean_text(value)
    normalized = normalize_project(display)
    return ("", "") if normalized in PLACEHOLDERS else (display, normalized)


def useful_system(value: Any) -> tuple[str, str]:
    display = clean_text(value)
    normalized = normalize_information_system(display)
    return ("", "") if normalized in PLACEHOLDERS else (display, normalized)


def split_recipients(value: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for email in EMAIL_RE.findall(str(value or "")):
        item = email.casefold()
        key = item[:-6] if item.endswith("@x5.ru") else item
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def hostname_family(hostname: str) -> str:
    normalized = normalize_hostname(hostname)
    family = re.sub(r"\d+$", "*", normalized)
    return family if family != normalized else ""


def route_project(project_norm: str, system_norm: str, recipients: tuple[str, ...]) -> str:
    recipient_keys = {item[:-6] if item.endswith("@x5.ru") else item for item in recipients}
    if project_norm == "x5 salt" or "portal.salt" in system_norm:
        return "Salt"
    if {"dis.srv", "dis.eng"}.issubset(recipient_keys):
        return "Digital"
    return "X5Tech"


def read_rows(path: Path) -> tuple[list[Example], dict[str, Any]]:
    sheets: dict[str, dict[int, dict[int, str]]] = defaultdict(lambda: defaultdict(dict))
    for cell in iter_xlsx_cells(path):
        sheets[cell.source_sheet][cell.source_row][column_index(cell.source_column)] = cell.source_display_value
    aliases = {
        "hostname": {"hostname", "host name", "имя хоста", "хостнейм"},
        "information_system": {"информационная система", "ис", "information system"},
        "project": {"проект", "project"},
        "comment": {"комментарий", "comment"},
        "recipients": {"адресаты", "адресат", "кому писать", "recipients", "recipient"},
    }
    aliases = {key: {normalize_header(value) for value in values} for key, values in aliases.items()}
    selected: tuple[str, int, dict[str, int]] | None = None
    for sheet_name, rows in sheets.items():
        for row_number in sorted(rows)[:60]:
            headers: dict[str, int] = {}
            for col, value in rows[row_number].items():
                normalized = normalize_header(value)
                for field, names in aliases.items():
                    if normalized in names:
                        headers[field] = col
            if {"hostname", "recipients"}.issubset(headers):
                selected = sheet_name, row_number, headers
                break
        if selected:
            break
    if selected is None:
        raise ValueError("В XLSX не найдены столбцы Hostname и Адресаты")
    sheet_name, header_row, headers = selected
    examples: list[Example] = []
    nonempty_rows = 0
    empty_recipient_rows = 0
    duplicate_hostnames: list[str] = []
    seen_hostnames: set[str] = set()
    for row_number in sorted(sheets[sheet_name]):
        if row_number <= header_row:
            continue
        row = sheets[sheet_name][row_number]
        if not any(clean_text(value) for value in row.values()):
            continue
        nonempty_rows += 1
        hostname = clean_text(row.get(headers["hostname"]))
        recipients = split_recipients(row.get(headers["recipients"]))
        if not recipients:
            empty_recipient_rows += 1
            continue
        if not hostname:
            continue
        hostname_norm = normalize_hostname(hostname)
        if hostname_norm in seen_hostnames:
            duplicate_hostnames.append(hostname)
        seen_hostnames.add(hostname_norm)
        project, project_norm = useful_project(row.get(headers.get("project", -1)))
        system, system_norm = useful_system(row.get(headers.get("information_system", -1)))
        comment = clean_text(row.get(headers.get("comment", -1)))
        examples.append(
            Example(
                row_number=row_number,
                hostname=hostname,
                hostname_norm=hostname_norm,
                hostname_mask=hostname_family(hostname),
                information_system=system,
                information_system_norm=system_norm,
                project=project,
                project_norm=project_norm,
                comment=comment,
                recipients=recipients,
                route_project=route_project(project_norm, system_norm, recipients),
            )
        )
    metadata = {
        "source_file": str(path),
        "sheets": sorted(sheets),
        "selected_sheet": sheet_name,
        "header_row": header_row,
        "headers": headers,
        "nonempty_data_rows": nonempty_rows,
        "empty_recipient_rows": empty_recipient_rows,
        "duplicate_hostnames": duplicate_hostnames,
    }
    return examples, metadata


def spec_matches(spec: tuple[str, str, str], example: Example) -> bool:
    pattern, project_norm, system_norm = spec
    return (
        fnmatch.fnmatchcase(example.hostname_norm, pattern)
        and (not project_norm or project_norm == example.project_norm)
        and (not system_norm or system_norm == example.information_system_norm)
    )


def candidate_type(pattern: str, project_norm: str, system_norm: str) -> str:
    feature_count = int(pattern != "*") + int(bool(project_norm)) + int(bool(system_norm))
    if feature_count > 1:
        return "combined"
    if pattern != "*":
        return "hostname"
    if project_norm:
        return "project"
    return "information_system"


def candidate_specs(examples: Iterable[Example]) -> set[tuple[str, str, str]]:
    specs: set[tuple[str, str, str]] = set()
    for item in examples:
        if item.hostname_mask:
            specs.add((item.hostname_mask, "", ""))
            if item.project_norm:
                specs.add((item.hostname_mask, item.project_norm, ""))
            if item.information_system_norm:
                specs.add((item.hostname_mask, "", item.information_system_norm))
            if item.project_norm and item.information_system_norm:
                specs.add((item.hostname_mask, item.project_norm, item.information_system_norm))
        if item.project_norm:
            specs.add(("*", item.project_norm, ""))
        if item.information_system_norm:
            specs.add(("*", "", item.information_system_norm))
        if item.project_norm and item.information_system_norm:
            specs.add(("*", item.project_norm, item.information_system_norm))
    return specs


def derive_candidates(examples: list[Example]) -> tuple[list[Candidate], list[dict[str, Any]]]:
    accepted: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    project_display = {item.project_norm: item.project for item in examples if item.project_norm}
    system_display = {
        item.information_system_norm: item.information_system
        for item in examples
        if item.information_system_norm
    }
    for spec in sorted(candidate_specs(examples)):
        pattern, project_norm, system_norm = spec
        matched = [item for item in examples if spec_matches(spec, item)]
        counts = Counter(item.target for item in matched)
        target, correct = counts.most_common(1)[0]
        support = len(matched)
        conflicts = support - correct
        confidence = correct / support
        rule_type = candidate_type(pattern, project_norm, system_norm)
        candidate = Candidate(
            rule_type=rule_type,
            hostname_pattern=pattern,
            dcim_project=project_display.get(project_norm, ""),
            information_system=system_display.get(system_norm, ""),
            route_project=target[0],
            recipients=target[1],
            support=support,
            correct=correct,
            conflicts=conflicts,
            confidence=confidence,
            source_rows=tuple(item.row_number for item in matched if item.target == target),
        )
        reason = ""
        if support < MIN_SUPPORT[rule_type]:
            reason = f"недостаточная поддержка: {support} < {MIN_SUPPORT[rule_type]}"
        elif confidence < 1.0:
            reason = f"конфликтующие адресаты: confidence={confidence:.2%}"
        elif rule_type == "project" and len({item.information_system_norm for item in matched if item.information_system_norm}) < 3:
            reason = "проект подтверждён менее чем тремя различными информационными системами"
        elif rule_type == "information_system" and len({item.project_norm for item in matched if item.project_norm}) < 2:
            reason = "информационная система подтверждена менее чем двумя различными проектами"
        elif rule_type in {"project", "information_system"} and len({item.hostname_mask or item.hostname_norm for item in matched}) < 3:
            reason = "правило подтверждено менее чем тремя независимыми hostname-семействами"
        elif rule_type == "combined" and pattern == "*" and len({item.hostname_mask or item.hostname_norm for item in matched}) < 2:
            reason = "комбинация project+ИС подтверждена только одним hostname-семейством"
        if reason:
            rejected.append(candidate_record(candidate, reason=reason))
        else:
            accepted.append(candidate)
    return accepted, rejected


def rule_score(candidate: Candidate, example: Example) -> tuple[int, int, int] | None:
    if not spec_matches(candidate.condition_key, example):
        return None
    project_condition = bool(candidate.dcim_project)
    system_condition = bool(candidate.information_system)
    condition_rank = 3 if project_condition and system_condition else (2 if project_condition else (1 if system_condition else 0))
    specificity = len(re.sub(r"[*?]", "", candidate.hostname_pattern))
    match_rank = 3 if candidate.rule_type == "exact_hostname" else 2
    return match_rank, condition_rank, specificity


def predict(example: Example, rules: Iterable[Candidate]) -> tuple[str, tuple[str, ...]] | str | None:
    matches = [(rule_score(rule, example), rule) for rule in rules]
    matches = [(score, rule) for score, rule in matches if score is not None]
    if not matches:
        return None
    salt_matches = [item for item in matches if item[1].route_project == "Salt"]
    choices = salt_matches or matches
    best_score = max(item[0] for item in choices)
    targets = {item[1].target for item in choices if item[0] == best_score}
    return next(iter(targets)) if len(targets) == 1 else "ambiguous"


def evaluate(examples: list[Example], rules: list[Candidate]) -> dict[str, Any]:
    correct = wrong = undefined = ambiguous = 0
    details: list[dict[str, Any]] = []
    for item in examples:
        result = predict(item, rules)
        if result is None:
            undefined += 1
            status = "undefined"
        elif result == "ambiguous":
            ambiguous += 1
            status = "ambiguous"
        elif result == item.target:
            correct += 1
            status = "correct"
        else:
            wrong += 1
            status = "wrong"
        if status != "correct":
            details.append({"row": item.row_number, "hostname": item.hostname, "status": status})
    total = len(examples)
    automatic = correct + wrong
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "undefined": undefined,
        "ambiguous": ambiguous,
        "accuracy": correct / total if total else 0.0,
        "precision": correct / automatic if automatic else 0.0,
        "coverage": automatic / total if total else 0.0,
        "non_correct_examples": details,
    }


def select_general_rules(examples: list[Example], accepted: list[Candidate]) -> list[Candidate]:
    selected = [rule for rule in accepted if rule.rule_type != "combined"]
    combined = sorted(
        (rule for rule in accepted if rule.rule_type == "combined"),
        key=lambda rule: (-rule.support, -len([v for v in rule.condition_key if v and v != "*"]), rule.condition_key),
    )
    for rule in combined:
        matched = [item for item in examples if rule_score(rule, item) is not None]
        if any(predict(item, selected) != item.target for item in matched):
            selected.append(rule)
    return selected


def exact_rule(example: Example) -> Candidate:
    return Candidate(
        rule_type="exact_hostname",
        hostname_pattern=example.hostname_norm,
        dcim_project="",
        information_system="",
        route_project=example.route_project,
        recipients=example.recipients,
        support=1,
        correct=1,
        conflicts=0,
        confidence=1.0,
        source_rows=(example.row_number,),
    )


def candidate_record(candidate: Candidate, *, reason: str = "") -> dict[str, Any]:
    record = {
        "condition": {
            "hostname_pattern": candidate.hostname_pattern,
            **({"project": candidate.dcim_project} if candidate.dcim_project else {}),
            **({"information_system": candidate.information_system} if candidate.information_system else {}),
        },
        "route_project": candidate.route_project,
        "recipients": list(candidate.recipients),
        "support": candidate.support,
        "correct": candidate.correct,
        "conflicts": candidate.conflicts,
        "confidence": candidate.confidence,
        "source_rows": list(candidate.source_rows),
    }
    if reason:
        record["reason"] = reason
    return record


def json_rule(candidate: Candidate, source_name: str) -> dict[str, Any]:
    exact = candidate.rule_type == "exact_hostname"
    rule: dict[str, Any] = {
        ("hostname" if exact else "hostname_pattern"): candidate.hostname_pattern,
        "match_type": "exact" if exact else "wildcard",
        "project": candidate.route_project,
        "is_salt": candidate.route_project == "Salt",
        "to": list(candidate.recipients),
        "cc": [],
        "source_rule_type": candidate.rule_type,
        "source_file": source_name,
        "support": candidate.support,
        "correct": candidate.correct,
        "conflicts": candidate.conflicts,
        "confidence": candidate.confidence,
        "source_rows": list(candidate.source_rows),
    }
    if candidate.dcim_project:
        rule["dcim_project"] = candidate.dcim_project
    if candidate.information_system:
        rule["information_system"] = candidate.information_system
    return rule


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} не содержит JSON-объект")
    return payload


def rule_signature(rule: dict[str, Any]) -> tuple[str, str, str, str]:
    identity = clean_text(rule.get("hostname") or rule.get("hostname_pattern") or rule.get("regex")).casefold()
    return (
        clean_text(rule.get("match_type")).casefold(),
        identity,
        normalize_project(rule.get("dcim_project")),
        normalize_information_system(rule.get("information_system")),
    )


def target_from_json(rule: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    return clean_text(rule.get("project")), split_recipients(";".join(str(value) for value in rule.get("to", [])))


def merge_rules(
    existing: list[dict[str, Any]],
    learned: list[Candidate],
    source_name: str,
) -> tuple[list[dict[str, Any]], list[Candidate], list[dict[str, Any]]]:
    merged = list(existing)
    added: list[Candidate] = []
    conflicts: list[dict[str, Any]] = []
    signatures = {rule_signature(rule): rule for rule in existing if isinstance(rule, dict)}
    for candidate in learned:
        rule = json_rule(candidate, source_name)
        signature = rule_signature(rule)
        old = signatures.get(signature)
        if old is not None:
            if target_from_json(old) != candidate.target:
                conflicts.append(
                    {
                        "existing_rule": old,
                        "new_rule": candidate_record(candidate),
                        "decision": "Сохранено существующее правило; новое не добавлено.",
                    }
                )
            continue
        merged.append(rule)
        signatures[signature] = rule
        added.append(candidate)
    return merged, added, conflicts


def group_holdout(examples: list[Example]) -> tuple[list[Example], list[Example]]:
    training: list[Example] = []
    holdout: list[Example] = []
    for item in examples:
        group = item.hostname_mask or item.hostname_norm
        bucket = int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % 5
        (holdout if bucket == 0 else training).append(item)
    if not holdout and examples:
        holdout.append(examples[-1])
        training = examples[:-1]
    return training, holdout


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def format_metric(value: float) -> str:
    return f"{value:.2%}"


def rule_line(rule: Candidate) -> str:
    conditions = [f"hostname={rule.hostname_pattern}"]
    if rule.dcim_project:
        conditions.append(f"project={rule.dcim_project}")
    if rule.information_system:
        conditions.append(f"information_system={rule.information_system}")
    return (
        f"Тип: {rule.rule_type}\nУсловие: {' + '.join(conditions)}\n"
        f"Адресат: {'; '.join(rule.recipients)}\nSupport: {rule.support}\n"
        f"Correct: {rule.correct}\nConflicts: {rule.conflicts}\n"
        f"Confidence: {format_metric(rule.confidence)}"
    )


def write_report(
    path: Path,
    *,
    source: Path,
    metadata: dict[str, Any],
    examples: list[Example],
    added: list[Candidate],
    rejected: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    mode_a: dict[str, Any],
    mode_b: dict[str, Any],
    holdout: dict[str, Any],
    existing_rule_count: int,
    verification: str,
) -> None:
    unique_emails = sorted({email for item in examples for email in item.recipients})
    unique_sets = {item.recipients for item in examples}
    sections = [
        "ОТЧЁТ ОБ ИНТЕГРАЦИИ ПРАВИЛ АДРЕСАТОВ ODE",
        f"Сформирован: {datetime.now(timezone.utc).isoformat()}",
        "",
        "1. АНАЛИЗ EXCEL",
        f"Файл: {source}",
        f"Листы: {', '.join(metadata['sheets'])}",
        f"Рабочий лист: {metadata['selected_sheet']}; строка заголовков: {metadata['header_row']}",
        f"Проанализировано строк данных: {metadata['nonempty_data_rows']}",
        f"Строк с подтверждёнными адресатами: {len(examples)}",
        f"Уникальных hostname: {len({item.hostname_norm for item in examples})}",
        f"Уникальных проектов: {len({item.project_norm for item in examples if item.project_norm})}",
        f"Уникальных информационных систем: {len({item.information_system_norm for item in examples if item.information_system_norm})}",
        f"Уникальных адресатов: {len(unique_emails)}",
        f"Уникальных наборов адресатов: {len(unique_sets)}",
        f"Строк с несколькими адресатами: {sum(len(item.recipients) > 1 for item in examples)}",
        f"Строк с пустым адресатом: {metadata['empty_recipient_rows']}",
        f"Строк без пригодного проекта: {sum(not item.project_norm for item in examples)}",
        f"Строк без пригодной информационной системы: {sum(not item.information_system_norm for item in examples)}",
        "",
        "2. СУЩЕСТВУЮЩАЯ АРХИТЕКТУРА ODE",
        "Resolver: inventory/monitoring/hostname_routing.py::resolve_hostname_routing.",
        "Вызов: inventory/monitoring/manual_search.py после извлечения данных DCIM.",
        "Правила: data/monitoring/Hostname Tech.json и Hostname Digital.json.",
        "Приоритет проектов сохранён: Salt, затем Digital, затем X5Tech.",
        "Приоритет hostname сохранён: exact, wildcard, regex; для равного типа добавлена специфичность условий project/information_system.",
        "Кому берётся из to, Копия из cc; списки дедуплицируются раздельно.",
        "Fallback остаётся fail-closed: при отсутствии надёжного совпадения письмо не считается готовым.",
        f"Существующих Tech-правил до интеграции: {existing_rule_count}.",
        "",
        "3. НАЙДЕННЫЕ ЗАКОНОМЕРНОСТИ",
        "Использованы окончания hostname с числовой серией, однозначные project/ИС и их комбинации.",
        "Широкие правила принимались только при confidence 100%; minimum support: hostname/project/ИС=3, combined=2.",
        "Значения project 'Модель:', None и пустые значения исключены как шум исходной выгрузки.",
        "Маршрутизация Digital присвоена наборам с DIS.SRV и DIS.ENG; Salt — явному X5 Salt/portal.salt; остальные правила остаются X5Tech.",
        "Комментарий не использовался как автоматический признак из-за неструктурированного содержания.",
        "",
        "4. ДОБАВЛЕННЫЕ ПРАВИЛА",
        f"Всего добавлено: {len(added)}",
        "\n\n".join(rule_line(rule) for rule in added) or "Новые правила не добавлены.",
        "",
        "5. ОТКЛОНЁННЫЕ ПРАВИЛА",
        f"Всего отклонено: {len(rejected)}",
    ]
    for item in rejected:
        condition = item["condition"]
        sections.append(
            f"{condition} -> {'; '.join(item['recipients'])}; support={item['support']}; "
            f"confidence={format_metric(item['confidence'])}; причина={item['reason']}"
        )
    sections.extend(["", "6. КОНФЛИКТЫ СО СТАРЫМИ ПРАВИЛАМИ ODE", f"Обнаружено: {len(conflicts)}"])
    for item in conflicts:
        sections.append(json.dumps(item, ensure_ascii=False))
    sections.extend(
        [
            "",
            "7. РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ",
            f"Всего подтверждённых строк: {mode_a['total']}",
            f"Правильно: {mode_a['correct']}",
            f"Неправильно: {mode_a['wrong']}",
            f"Не определено: {mode_a['undefined']}",
            f"Неоднозначно: {mode_a['ambiguous']}",
            f"Accuracy: {format_metric(mode_a['accuracy'])}",
            f"Precision: {format_metric(mode_a['precision'])}",
            f"Coverage: {format_metric(mode_a['coverage'])}",
            "",
            "С exact-hostname правилами:",
            f"Accuracy: {format_metric(mode_a['accuracy'])}",
            f"Precision: {format_metric(mode_a['precision'])}",
            f"Coverage: {format_metric(mode_a['coverage'])}",
            "",
            "Без exact-hostname правил:",
            f"Accuracy: {format_metric(mode_b['accuracy'])}",
            f"Precision: {format_metric(mode_b['precision'])}",
            f"Coverage: {format_metric(mode_b['coverage'])}",
            "",
            f"Holdout training rows: {holdout['training_rows']}",
            f"Holdout test rows: {holdout['test_rows']}",
            f"Holdout Accuracy: {format_metric(holdout['accuracy'])}",
            f"Holdout Precision: {format_metric(holdout['precision'])}",
            f"Holdout Coverage: {format_metric(holdout['coverage'])}",
            "",
            "8. ИЗМЕНЁННЫЕ И СОЗДАННЫЕ ФАЙЛЫ",
            "inventory/monitoring/hostname_routing.py",
            "inventory/monitoring/manual_search.py",
            "inventory/monitoring/facade.py",
            "tests/test_monitoring_hostname_routing.py",
            "tests/test_monitoring_manual_search.py",
            "scripts/integrate_recipient_rules_from_xlsx.py",
            "docs/MONITORING_HOSTNAME_ROUTING.md",
            "data/monitoring/Hostname Tech.json",
            "data/monitoring/Hostname Digital.json",
            "recipient_rules_analysis.json",
            "recipient_rules_integration_report.txt",
            "",
            "9. ПРОВЕРКА ЗАПУСКА",
            verification,
            "Реальный поиск в рабочем DCIM/Zabbix не выполнялся: он требует рабочего оборудования и сессии оператора.",
        ]
    )
    path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--verification", default="Проверки выполняются отдельно после генерации правил.")
    args = parser.parse_args()
    root = args.project_root.resolve()
    source = args.source.resolve()
    examples, metadata = read_rows(source)
    if not examples:
        raise ValueError("В XLSX нет строк с подтверждёнными адресатами")

    accepted, rejected = derive_candidates(examples)
    general_rules = select_general_rules(examples, accepted)
    selected_general = set(general_rules)
    rejected.extend(
        candidate_record(
            rule,
            reason="избыточно: подтверждённые строки уже покрыты выбранным правилом",
        )
        for rule in accepted
        if rule not in selected_general
    )
    mode_b = evaluate(examples, general_rules)
    exact_rules = [exact_rule(item) for item in examples if predict(item, general_rules) != item.target]
    learned = [*general_rules, *exact_rules]
    mode_a = evaluate(examples, learned)

    training, holdout_examples = group_holdout(examples)
    holdout_accepted, _ = derive_candidates(training)
    holdout_rules = select_general_rules(training, holdout_accepted)
    holdout_result = evaluate(holdout_examples, holdout_rules)
    holdout_result["training_rows"] = len(training)
    holdout_result["test_rows"] = len(holdout_examples)

    rules_dir = root / "data" / "monitoring"
    tech_path = rules_dir / TECH_RULES_NAME
    digital_path = rules_dir / DIGITAL_RULES_NAME
    tech_payload = load_json(tech_path, {"version": 1, "cc_exclusions": [], "rules": []})
    digital_payload = load_json(
        digital_path,
        {"version": 1, "default_to": [], "default_cc": [], "hostnames": []},
    )
    if validate_rules_payload(tech_payload, "Tech"):
        raise ValueError(f"Существующий {TECH_RULES_NAME} не прошёл проверку")
    if validate_rules_payload(digital_payload, "Digital"):
        raise ValueError(f"Существующий {DIGITAL_RULES_NAME} не прошёл проверку")
    all_existing_rules = tech_payload.get("rules", [])
    existing_rules = [
        rule
        for rule in all_existing_rules
        if not isinstance(rule, dict) or clean_text(rule.get("source_file")) != source.name
    ]
    merged, added, conflicts = merge_rules(existing_rules, learned, source.name)
    tech_payload["rules"] = merged
    tech_payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    tech_payload["learned_source_file"] = source.name
    if error := validate_rules_payload(tech_payload, "Tech"):
        raise ValueError(error)
    if error := validate_rules_payload(digital_payload, "Digital"):
        raise ValueError(error)
    atomic_json(tech_path, tech_payload)
    atomic_json(digital_path, digital_payload)

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in added:
        by_type[rule.rule_type].append(candidate_record(rule))
    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "statistics": {
            **metadata,
            "confirmed_rows": len(examples),
            "unique_hostnames": len({item.hostname_norm for item in examples}),
            "unique_projects": len({item.project_norm for item in examples if item.project_norm}),
            "unique_information_systems": len({item.information_system_norm for item in examples if item.information_system_norm}),
            "unique_recipients": len({email for item in examples for email in item.recipients}),
            "unique_recipient_sets": len({item.recipients for item in examples}),
            "multiple_recipient_rows": sum(len(item.recipients) > 1 for item in examples),
        },
        "thresholds": {"confidence": 1.0, "minimum_support": MIN_SUPPORT},
        "hostname_rules": by_type["hostname"],
        "project_rules": by_type["project"],
        "information_system_rules": by_type["information_system"],
        "combined_rules": by_type["combined"],
        "exact_hostname_rules": by_type["exact_hostname"],
        "rejected_rules": rejected,
        "conflicts": conflicts,
        "test_results": {"with_exact": mode_a, "without_exact": mode_b},
        "holdout_results": holdout_result,
        "integration": {
            "existing_tech_rules": len(existing_rules),
            "added_rules": len(added),
            "final_tech_rules": len(merged),
        },
        "verification": {"summary": args.verification},
    }
    atomic_json(root / "recipient_rules_analysis.json", analysis)
    write_report(
        root / "recipient_rules_integration_report.txt",
        source=source,
        metadata=metadata,
        examples=examples,
        added=added,
        rejected=rejected,
        conflicts=conflicts,
        mode_a=mode_a,
        mode_b=mode_b,
        holdout=holdout_result,
        existing_rule_count=len(existing_rules),
        verification=args.verification,
    )
    summary = {
        "rows": metadata["nonempty_data_rows"],
        "confirmed": len(examples),
        "unique_recipients": analysis["statistics"]["unique_recipients"],
        "added": len(added),
        "types": {key: len(value) for key, value in by_type.items()},
        "rejected": len(rejected),
        "conflicts": len(conflicts),
        "with_exact": mode_a,
        "without_exact": mode_b,
        "holdout": holdout_result,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
