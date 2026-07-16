"""Hostname-based project and email routing for manual monitoring searches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import fnmatch
from functools import lru_cache
import json
import logging
from pathlib import Path
import re
from typing import Any, Iterable


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES_DIR = APP_ROOT / "data" / "monitoring"
TECH_RULES_NAME = "Hostname Tech.json"
DIGITAL_RULES_NAME = "Hostname Digital.json"
MAX_RULES_FILE_BYTES = 5 * 1024 * 1024
MAX_TECH_RULES = 10_000
MAX_DIGITAL_HOSTNAMES = 100_000
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
HOSTNAME_PATTERN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._*?-]{0,252}$")
RECIPIENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+@-]{0,253}$")


@dataclass(frozen=True)
class RoutingDecision:
    hostname: str
    project: str = ""
    tag: str = ""
    to: tuple[str, ...] = ()
    cc: tuple[str, ...] = ()
    matched_rules: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def email_ready(self) -> bool:
        return bool(self.project and self.tag and self.to and not self.errors)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return re.sub(r"[\x00-\x20\x7f]+", " ", text).strip()


def normalize_hostname(value: Any) -> str:
    return clean_text(value).casefold()


def recipient_key(value: Any) -> str:
    key = clean_text(value).casefold()
    return key[:-6] if key.endswith("@x5.ru") else key


def dedupe_recipients(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_text(value)
        if not item:
            continue
        key = recipient_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def filter_cc(values: Iterable[Any], to: Iterable[Any], exclusions: Iterable[Any] = ()) -> list[str]:
    blocked = {recipient_key(value) for value in [*to, *exclusions] if clean_text(value)}
    return [value for value in dedupe_recipients(values) if recipient_key(value) not in blocked]


def format_recipients(values: Iterable[Any]) -> str:
    return "; ".join(dedupe_recipients(values))


def _recipient_list_error(value: Any, field: str) -> str:
    if not isinstance(value, list):
        return f"Поле {field} должно быть массивом"
    if len(value) > 1_000:
        return f"Поле {field} содержит слишком много адресатов"
    for item in value:
        if not isinstance(item, str) or not RECIPIENT_RE.fullmatch(clean_text(item)):
            return f"Поле {field} содержит недопустимого адресата"
    return ""


def _safe_regex_error(pattern: str) -> str:
    if len(pattern) > 253:
        return "regex hostname превышает допустимую длину"
    if "(?" in pattern or re.search(r"\\[1-9]", pattern):
        return "lookaround/backreference в regex hostname не поддерживается"
    if re.search(r"\([^)]*[*+]\)[*+{]", pattern):
        return "вложенные квантификаторы в regex hostname запрещены"
    try:
        re.compile(pattern, flags=re.IGNORECASE)
    except re.error:
        return "regex hostname некорректен"
    return ""


def _validate_tech_rule(rule: Any, index: int) -> str:
    if not isinstance(rule, dict):
        return f"Tech-правило {index} должно быть JSON-объектом"
    match_type = clean_text(rule.get("match_type")).casefold()
    identity = _rule_identity(rule)
    if match_type not in {"exact", "wildcard", "regex"}:
        return f"Tech-правило {index} имеет неподдерживаемый match_type"
    if not identity:
        return f"Tech-правило {index} не содержит hostname pattern"
    if match_type in {"exact", "wildcard"} and not HOSTNAME_PATTERN_RE.fullmatch(identity):
        return f"Tech-правило {index} содержит недопустимый hostname pattern"
    if match_type == "exact" and ("*" in identity or "?" in identity):
        return f"Tech-правило {index} exact содержит wildcard"
    if match_type == "regex":
        regex_error = _safe_regex_error(identity)
        if regex_error:
            return f"Tech-правило {index}: {regex_error}"
    project = clean_text(rule.get("project"))
    if project.casefold() not in {"x5tech", "salt"}:
        return f"Tech-правило {index} содержит неизвестный project"
    is_salt = rule.get("is_salt")
    if not isinstance(is_salt, bool):
        return f"Tech-правило {index} должно содержать boolean is_salt"
    if is_salt != (project.casefold() == "salt"):
        return f"Tech-правило {index} содержит противоречивый project/is_salt"
    for field in ("to", "cc"):
        error = _recipient_list_error(rule.get(field, []), f"rules[{index}].{field}")
        if error:
            return error
    return ""


def _validate_tech_payload(payload: dict[str, Any]) -> str:
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return "В Hostname Tech.json отсутствует массив rules"
    if len(rules) > MAX_TECH_RULES:
        return "Hostname Tech.json содержит слишком много правил"
    error = _recipient_list_error(payload.get("cc_exclusions", []), "cc_exclusions")
    if error:
        return error
    for index, rule in enumerate(rules, 1):
        error = _validate_tech_rule(rule, index)
        if error:
            return error
    return ""


def _validate_digital_payload(payload: dict[str, Any]) -> str:
    hostnames = payload.get("hostnames")
    if not isinstance(hostnames, list):
        return "В Hostname Digital.json отсутствует массив hostnames"
    if len(hostnames) > MAX_DIGITAL_HOSTNAMES:
        return "Hostname Digital.json содержит слишком много hostname"
    seen: set[str] = set()
    for hostname in hostnames:
        normalized = normalize_hostname(hostname)
        if not isinstance(hostname, str) or not HOSTNAME_RE.fullmatch(clean_text(hostname)):
            return "Hostname Digital.json содержит недопустимый hostname"
        if normalized in seen:
            return "Hostname Digital.json содержит дублирующийся hostname"
        seen.add(normalized)
    for field in ("default_to", "default_cc"):
        error = _recipient_list_error(payload.get(field, []), field)
        if error:
            return error
    return ""


def validate_rules_payload(payload: dict[str, Any], label: str) -> str:
    """Return a safe validation error, or an empty string for version-1 data."""
    if label == "Tech":
        return _validate_tech_payload(payload)
    if label == "Digital":
        return _validate_digital_payload(payload)
    return "Неизвестный тип файла правил"


@lru_cache(maxsize=32)
def _load_payload_cached(
    path_text: str,
    label: str,
    signature: tuple[int, int, int, int],
) -> tuple[dict[str, Any] | None, str]:
    del signature
    path = Path(path_text)
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_RULES_FILE_BYTES + 1)
        if len(raw) > MAX_RULES_FILE_BYTES:
            raise ValueError("размер файла правил превышает лимит")
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        message = f"Файл правил {label} не загружен"
        LOGGER.warning("%s: %s", message, error)
        return None, message
    if not isinstance(payload, dict):
        message = f"Файл правил {label} должен содержать JSON-объект"
        LOGGER.warning(message)
        return None, message
    if type(payload.get("version")) is not int or payload.get("version") != 1:
        message = f"Файл правил {label} имеет неподдерживаемую версию"
        LOGGER.warning(message)
        return None, message
    validation_error = validate_rules_payload(payload, label)
    if validation_error:
        message = f"Файл правил {label} отклонён: {validation_error}"
        LOGGER.warning(message)
        return None, message
    if label == "Digital":
        payload["_normalized_hostnames"] = frozenset(
            normalize_hostname(value) for value in payload["hostnames"]
        )
    return payload, ""


def _load_payload(path: Path, label: str) -> tuple[dict[str, Any] | None, str]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        message = f"Файл правил {label} не найден: {path}"
        LOGGER.warning(message)
        return None, message
    except OSError as error:
        message = f"Файл правил {label} не загружен"
        LOGGER.warning("%s: %s", message, error)
        return None, message
    if stat.st_size > MAX_RULES_FILE_BYTES:
        message = f"Файл правил {label} не загружен: размер превышает лимит"
        LOGGER.warning(message)
        return None, message
    signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return _load_payload_cached(str(path.absolute()), label, signature)


def _rule_identity(rule: dict[str, Any]) -> str:
    return clean_text(rule.get("hostname") or rule.get("hostname_pattern") or rule.get("regex"))


def _rule_score(hostname: str, rule: dict[str, Any]) -> tuple[int, int] | None:
    match_type = clean_text(rule.get("match_type")).casefold()
    pattern = _rule_identity(rule)
    if not pattern:
        return None
    normalized_pattern = pattern.casefold()
    if match_type == "exact":
        return (3, len(normalized_pattern)) if hostname == normalized_pattern else None
    if match_type == "wildcard":
        if fnmatch.fnmatchcase(hostname, normalized_pattern):
            specificity = len(re.sub(r"[*?]", "", normalized_pattern))
            return 2, specificity
        return None
    if match_type == "regex":
        try:
            return (1, len(normalized_pattern)) if re.fullmatch(pattern, hostname, flags=re.IGNORECASE) else None
        except re.error as error:
            LOGGER.warning("Некорректное regex-правило %s: %s", pattern, error)
    return None


def _best_tech_rule(hostname: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return None, [], ["В Hostname Tech.json отсутствует массив rules"]
    matches: list[tuple[tuple[int, int], int, dict[str, Any]]] = []
    warnings: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            warnings.append(f"Tech-правило {index + 1} пропущено: ожидался JSON-объект")
            continue
        score = _rule_score(hostname, rule)
        if score is not None:
            matches.append((score, index, rule))
    if not matches:
        return None, warnings, []
    salt_matches = [
        match for match in matches
        if match[2].get("is_salt") is True
        or clean_text(match[2].get("project")).casefold() == "salt"
    ]
    candidates = salt_matches or matches
    if salt_matches and len(salt_matches) != len(matches):
        warnings.append("Для hostname совпали Salt и X5Tech; применен приоритет Salt")
    best_score = max(match[0] for match in candidates)
    best = [match for match in candidates if match[0] == best_score]
    if len(matches) > 1:
        warnings.append("Для hostname совпало несколько Tech-правил; применяется наиболее точное")
    if len(best) > 1:
        identities = ", ".join(_rule_identity(match[2]) for match in best)
        return None, warnings, [f"Найдено несколько равнозначных Tech-правил: {identities}"]
    return best[0][2], warnings, []


def _digital_match(hostname: str, payload: dict[str, Any]) -> tuple[bool, list[str]]:
    hostnames = payload.get("hostnames")
    if not isinstance(hostnames, list):
        return False, ["В Hostname Digital.json отсутствует массив hostnames"]
    normalized = payload.get("_normalized_hostnames")
    if not isinstance(normalized, frozenset):
        normalized = frozenset(
            normalize_hostname(value) for value in hostnames if normalize_hostname(value)
        )
    return hostname in normalized, []


def resolve_hostname_routing(hostname: Any, *, rules_dir: Path | None = None) -> RoutingDecision:
    display_hostname = clean_text(hostname)
    normalized = normalize_hostname(display_hostname)
    if not normalized:
        return RoutingDecision(display_hostname, errors=("Hostname не указан",))
    if not HOSTNAME_RE.fullmatch(display_hostname):
        return RoutingDecision(display_hostname, errors=("Hostname имеет недопустимый формат",))
    directory = Path(rules_dir) if rules_dir is not None else DEFAULT_RULES_DIR
    tech_payload, tech_load_error = _load_payload(directory / TECH_RULES_NAME, "Tech")
    digital_payload, digital_load_error = _load_payload(directory / DIGITAL_RULES_NAME, "Digital")
    warnings = [message for message in (tech_load_error, digital_load_error) if message]
    errors: list[str] = []
    tech_rule: dict[str, Any] | None = None
    digital_found = False

    if tech_payload is not None:
        tech_rule, tech_warnings, tech_errors = _best_tech_rule(normalized, tech_payload)
        warnings.extend(tech_warnings)
        errors.extend(tech_errors)
    if digital_payload is not None:
        digital_found, digital_errors = _digital_match(normalized, digital_payload)
        errors.extend(digital_errors)

    tech_is_salt = bool(
        tech_rule
        and (tech_rule.get("is_salt") is True or clean_text(tech_rule.get("project")).casefold() == "salt")
    )
    project = ""
    tag = ""
    to: list[str] = []
    cc: list[str] = []
    matched_rules: list[str] = []

    if tech_is_salt:
        project, tag = "Salt", "[Salt]"
        matched_rules.append(f"Tech: {_rule_identity(tech_rule or {})}")
        to = dedupe_recipients((tech_rule or {}).get("to", []))
        exclusions = (tech_payload or {}).get("cc_exclusions", [])
        cc = filter_cc((tech_rule or {}).get("cc", []), to, exclusions)
        if digital_found:
            warnings.append("Hostname найден в Tech/SALT и Digital; применен приоритет Salt")
    elif digital_found:
        project, tag = "Digital", "[Digital]"
        matched_rules.append("Digital: exact")
        to = dedupe_recipients((digital_payload or {}).get("default_to", []))
        cc = filter_cc((digital_payload or {}).get("default_cc", []), to)
        if tech_rule is not None:
            warnings.append("Hostname найден в Tech и Digital; применен приоритет Digital")
            matched_rules.append(f"Tech conflict: {_rule_identity(tech_rule)}")
    elif tech_rule is not None:
        project, tag = "X5Tech", "[X5Tech]"
        matched_rules.append(f"Tech: {_rule_identity(tech_rule)}")
        to = dedupe_recipients(tech_rule.get("to", []))
        exclusions = (tech_payload or {}).get("cc_exclusions", [])
        cc = filter_cc(tech_rule.get("cc", []), to, exclusions)
    else:
        if not errors:
            errors.append(f"Hostname {display_hostname} не найден в правилах Tech и Digital")

    if project and not to:
        errors.append(f"Для проекта {project} не заданы адресаты поля «Кому»")
    for message in warnings:
        LOGGER.warning("Маршрутизация %s: %s", display_hostname, message)
    for message in errors:
        LOGGER.error("Маршрутизация %s: %s", display_hostname, message)
    return RoutingDecision(
        hostname=display_hostname,
        project=project,
        tag=tag,
        to=tuple(to),
        cc=tuple(cc),
        matched_rules=tuple(matched_rules),
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(dict.fromkeys(errors)),
    )


def build_email_subject(tag: Any, hostname: Any, problem: Any) -> str:
    clean_tag = clean_text(tag)
    clean_hostname = clean_text(hostname)
    clean_problem = clean_text(problem)
    if not clean_tag or not clean_hostname or not clean_problem:
        raise ValueError("Для темы письма нужны тег, hostname и описание проблемы")
    if not (clean_tag.startswith("[") and clean_tag.endswith("]")):
        clean_tag = f"[{clean_tag}]"
    return f"{clean_tag} {clean_hostname} {clean_problem}"


def greeting_for_hour(hour: int) -> str:
    if not 0 <= hour <= 23:
        raise ValueError("Час должен быть в диапазоне 0..23")
    if 5 <= hour <= 11:
        return "Коллеги, доброе утро!"
    if 12 <= hour <= 17:
        return "Коллеги, добрый день!"
    if 18 <= hour <= 22:
        return "Коллеги, добрый вечер!"
    return "Коллеги, доброй ночи!"


def build_email_body(hostname: Any, problem: Any, rooms_message: Any, *, at: datetime | None = None) -> str:
    clean_hostname = clean_text(hostname)
    clean_problem = clean_text(problem)
    if not clean_hostname or not clean_problem:
        raise ValueError("Для тела письма нужны hostname и описание проблемы")
    current = at or datetime.now()
    body = f"{greeting_for_hour(current.hour)}\n\nНа хосте {clean_hostname} наблюдается проблема: {clean_problem}"
    rooms = str(rooms_message or "").strip()
    return f"{body}\n\n{rooms}" if rooms else body


def build_email_text(subject: Any, to: Iterable[Any], cc: Iterable[Any], body: Any) -> str:
    lines = [
        f"Тема письма: {clean_text(subject)}",
        f"Кому: {format_recipients(to)}",
        f"Копия: {format_recipients(cc)}",
        "",
        str(body or "").strip(),
    ]
    return "\n".join(lines).rstrip()
