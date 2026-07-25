"""Manual Zabbix problem enrichment ported from v24.py."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from .hostname_routing import (
    build_email_body,
    build_email_subject,
    build_email_text,
    resolve_hostname_routing,
)

APP_ROOT = Path(__file__).resolve().parents[2]
DCIM_BASE = os.environ.get("ODE_MONITORING_DCIM_BASE_URL", "https://dcim.x5.ru").strip().rstrip("/")
DCIM_SEARCH_URL = f"{DCIM_BASE}/search/?q={{host}}"
OLD_DELL_MODELS = ["R630", "R730", "R730XD", "R830"]
TYPICAL_PROBLEM_REGEXES = [r"BMC:\s*No health data more than", r"Host is unavailable by API more than"]
DEFAULT_PROJECT = "-"
DEFAULT_TICKET = "-"
DEFAULT_SUPPORT = "Группа эксплуатации и развития ЦОД"
DEFAULT_DEFERRED = "-"
EDGE_PROFILE_DIR = Path(
    os.environ.get(
        "ODE_MONITORING_EDGE_PROFILE_DIR",
        str(APP_ROOT / "data" / "selenium_edge_profile"),
    )
).expanduser()


class ManualSearchError(RuntimeError):
    pass


def normalize_spaces(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ").replace("\t", " ")
    return re.sub(r"[ ]{2,}", " ", text).strip()


def fix_visible_newlines(text: Any) -> str:
    if text is None:
        return ""
    return str(text).replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def clean_lines(text: Any) -> list[str]:
    return [normalize_spaces(line) for line in str(text).splitlines() if normalize_spaces(line)]


def extract_emails(text: Any) -> list[str]:
    result: list[str] = []
    for email in re.findall(r"[A-Za-z0-9._%+-]+@x5\.ru", str(text or ""), flags=re.IGNORECASE):
        if email not in result:
            result.append(email)
    return result


def validate_hostname(host: Any) -> tuple[bool, str]:
    host = normalize_spaces(host)
    if not host:
        return False, "Hostname пустой."
    if len(host) < 3:
        return False, "Hostname слишком короткий."
    if len(host) > 128:
        return False, "Hostname слишком длинный."
    if not re.match(r"^[A-Za-z0-9_.-]+$", host):
        return False, "Hostname содержит недопустимые символы."
    return True, "OK"


def validate_problem_text(problem: Any) -> tuple[bool, str]:
    problem = fix_visible_newlines(problem).strip()
    if not problem:
        return False, "Описание проблемы пустое."
    if len(problem) < 4:
        return False, "Описание проблемы слишком короткое."
    if len(problem) > 1500:
        return False, "Описание проблемы слишком длинное. Лучше сократить перед обработкой."
    return True, "OK"


def make_problem_stable_key(host: Any, problem: Any) -> str:
    host_norm = normalize_spaces(host).upper()
    problem_norm = re.sub(r"\s+", " ", normalize_spaces(problem).upper())
    return f"{host_norm}|{problem_norm}"


def find_value_after_exact_marker(lines: list[str], marker: str, default: str = "-") -> str:
    marker_norm = normalize_spaces(marker).lower()
    for index, line in enumerate(lines):
        if normalize_spaces(line).lower() == marker_norm:
            for value_line in lines[index + 1:]:
                value = normalize_spaces(value_line)
                if value and value not in {"—", "-", "None"}:
                    return value
    return default


def find_value_after_any_marker(lines: list[str], markers: list[str], default: str = "-") -> str:
    for marker in markers:
        value = find_value_after_exact_marker(lines, marker, "")
        if value:
            return value
    return default


def find_host(lines: list[str], original_host: str) -> str:
    return find_value_after_exact_marker(lines, "Имя", "") or original_host or "-"


def find_model(lines: list[str]) -> str:
    model = find_value_after_exact_marker(lines, "Модель", "")
    if model:
        return model
    text = "\n".join(lines).upper()
    for model_name in ["POWEREDGE R630", "POWEREDGE R730XD", "POWEREDGE R730", "POWEREDGE R830", "POWEREDGE R740", "POWEREDGE R750", "2288H V6", "2288H V5"]:
        if model_name in text:
            return model_name
    return "-"


def find_serial(lines: list[str]) -> str:
    bad_values = {"Серийный номер мониторинг", "Серийный номер инвентарный", "Расхождение данных", "PartNumber", "Инвентарный номер", "—", "-", "None"}
    for index, line in enumerate(lines):
        if normalize_spaces(line).lower() == "серийный номер мониторинг":
            for value_line in lines[index + 1:index + 6]:
                value = normalize_spaces(value_line)
                if value and value not in bad_values:
                    return value
    for index, line in enumerate(lines):
        if normalize_spaces(line).lower() in {"серийный номер", "s/n", "sn"}:
            for value_line in lines[index + 1:index + 5]:
                value = normalize_spaces(value_line)
                if value and value not in bad_values:
                    return value
    return "-"


def find_location_line(lines: list[str]) -> str:
    for line in lines:
        line_norm = normalize_spaces(line)
        upper = line_norm.upper()
        if "ЦОД" in line_norm and "МАШ.ЗАЛ" in upper and "РЯД" in upper and "/" in line_norm:
            return line_norm
    for index, line in enumerate(lines):
        if line.startswith("ЦОД"):
            joined = " / ".join(lines[index:index + 5])
            if "Маш.зал" in joined and "Ряд" in joined:
                return joined
    return "-"


def parse_location(location: str) -> tuple[str, str, str]:
    if not location or location == "-":
        return "-", "-", "-"
    parts = [normalize_spaces(part) for part in location.split("/") if normalize_spaces(part)]
    dc = parts[0] if len(parts) >= 1 else "-"
    room = parts[1] if len(parts) >= 2 else "-"
    row = " / ".join(parts[2:5]) if len(parts) >= 5 else (" / ".join(parts[2:]) if len(parts) >= 3 else "-")
    return dc, room, row


def find_technical_owner(lines: list[str]) -> str:
    stop_markers = {
        "информационная система", "экземпляр информационной системы", "активность", "поставщик оборудования",
        "номер заказа в торг", "дата заказа", "номер заявки в торг", "тип бюджета", "дата приемки",
        "дата окончания срока службы", "тестовое оборудование", "неисправно", "парное оборудование",
        "воздушный поток", "id rt", "id мониторинга",
    }
    for index, line in enumerate(lines):
        line_clean = normalize_spaces(line)
        line_low = line_clean.lower()
        if line_low == "технический владелец" or line_low.startswith("технический владелец"):
            inline = re.sub(r"(?i)^технический владелец\s*[:\-]?\s*", "", line_clean).strip()
            if inline and inline.lower() != "технический владелец":
                return inline
            values: list[str] = []
            for value in lines[index + 1:index + 8]:
                value = normalize_spaces(value)
                value_low = value.lower()
                if not value or value in {"—", "-", "None"}:
                    continue
                if value_low in stop_markers or value_low.endswith(":"):
                    break
                values.append(value)
                if extract_emails(value):
                    break
            if values:
                return " ".join(values)
    return "-"


def parse_dcim_page(page_text: str, original_host: str) -> dict[str, str]:
    lines = clean_lines(page_text)
    location_line = find_location_line(lines)
    dc, room, row = parse_location(location_line)
    return {
        "host": find_host(lines, original_host),
        "model": find_model(lines),
        "serial": find_serial(lines),
        "dc": dc,
        "room": room,
        "row": row,
        "location_raw": location_line,
        "support": find_value_after_any_marker(lines, ["Группа поддержки", "Группы поддержки", "Тип поддержки"], DEFAULT_SUPPORT),
        "deferred": DEFAULT_DEFERRED,
        "env": find_value_after_any_marker(lines, ["Класс критичности", "Среда", "Environment"], "-"),
        "owner": find_technical_owner(lines),
        "information_system": find_value_after_any_marker(lines, ["Информационная система", "ИС"], "-"),
    }


def find_all_ips(text: Any) -> list[str]:
    ips: list[str] = []
    for item in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b", str(text)):
        ip = item.split("/")[0]
        try:
            ok = all(part.isdigit() and 0 <= int(part) <= 255 for part in ip.split("."))
        except Exception:
            ok = False
        if ok and ip not in ips:
            ips.append(ip)
    return ips


def ping_ip(ip: str, count: int = 2, timeout_ms: int = 1000) -> str:
    try:
        result = subprocess.run(
            ["ping", "-n", str(count), "-w", str(timeout_ms), ip],
            capture_output=True, text=True, encoding="cp866", errors="ignore",
            timeout=max(5, count * timeout_ms // 1000 + 3),
        )
        if "TTL=" in (result.stdout + "\n" + result.stderr).upper():
            return "Пинг ДА"
        return "Пинг НЕТ"
    except Exception as error:
        return f"Ошибка ping: {error}"


def ping_all_ips(ips: list[str], log_func: Callable[[str], None] | None = None) -> tuple[str, list[tuple[str, str]]]:
    if not ips:
        return "IP не найдены", []
    results = []
    for ip in ips:
        if log_func:
            log_func(f"Пингую {ip} ...")
        results.append((ip, ping_ip(ip)))
    if any(status == "Пинг ДА" for _, status in results):
        return "Пинг ДА", results
    if any(status.startswith("Ошибка") for _, status in results):
        return "Ошибка ping", results
    return "Пинг НЕТ", results


def is_typical_problem(problem: Any) -> bool:
    return any(re.search(pattern, str(problem), flags=re.IGNORECASE) for pattern in TYPICAL_PROBLEM_REGEXES)


def is_old_dell_model(model: Any) -> bool:
    return any(item.upper() in str(model).upper() for item in OLD_DELL_MODELS)


def is_hardware_problem(problem: Any) -> bool:
    text = str(problem).lower()
    if is_typical_problem(text):
        return False
    keywords = [
        "psu", "power", "power supply", "disk", "physical disk", "predictive failure", "raid", "controller",
        "storage", "memory", "ram", "dimm", "fan", "battery", "temperature", "voltage", "hardware",
        "желез", "диск", "памят", "вентил", "блок питания", "питани", "контроллер", "батар",
    ]
    return any(keyword in text for keyword in keywords)


def classify_problem(problem: Any) -> str:
    return "BMC/API" if is_typical_problem(problem) else "Нетипичная"


def is_information_event(item_or_text: Any) -> bool:
    text = item_or_text.get("raw", "") + "\n" + item_or_text.get("problem", "") if isinstance(item_or_text, dict) else str(item_or_text)
    return bool(re.search(r"\bInformation\b", text, flags=re.IGNORECASE))


def classify_task_status(problem: Any, ping_status: str, item: dict[str, Any] | None = None) -> tuple[str, str]:
    if item is not None and is_information_event(item):
        return "green", "Information"
    if is_hardware_problem(problem):
        return "red", "Железная неисправность"
    if is_typical_problem(problem) and ping_status == "Пинг ДА":
        return "green", "Можно наблюдать"
    return "red", "Требует проверки"


def make_recommendation(model: Any, problem: Any, ping_status: str, ips: list[str]) -> str:
    if "information" in str(problem).lower():
        return "Рекомендация: событие уровня Information. Задача отмечена зелёным, сообщение сформировано для истории."
    if is_hardware_problem(problem):
        return "Рекомендация: обнаружена неисправность, похожая на железную (disk/psu/memory/fan/raid/storage и т.п.). Проверь данные вручную, гарантию/сервисный контракт, ЗИП и ответственных по направлению."
    if not is_typical_problem(problem):
        if ping_status == "Пинг ДА":
            return "Рекомендация: проблема не типичная для автоматической логики. Один из IP пингуется. Сообщение сформировано, но дальше проблему нужно проверить самостоятельно."
        if ping_status == "Пинг НЕТ":
            return "Рекомендация: проблема не типичная для автоматической логики. IP не пингуются. Сообщение сформировано, но дальше проблему нужно проверить самостоятельно."
        return "Рекомендация: проблема не типичная для автоматической логики. IP не найдены или ping не проверился. Проверь проблему самостоятельно."
    if not ips:
        return "Рекомендация: типовая BMC/API-проблема, но IP-адреса не найдены автоматически. Проверь IP вручную в DCIM."
    if is_old_dell_model(model):
        if ping_status == "Пинг ДА":
            return "Рекомендация: старый Dell R630/R730/R730XD/R830 + типовая BMC/API-проблема. Один из IP пингуется. Похоже на проблему BMC/iDRAC/мониторинга. Сообщение подготовлено, можно наблюдать и ждать RESOLVED."
        if ping_status == "Пинг НЕТ":
            return "Рекомендация: старый Dell R630/R730/R730XD/R830 + типовая BMC/API-проблема. IP не пингуются. Проверить вебморду/iDRAC. Если вебморда недоступна - писать в Rooms."
    if ping_status == "Пинг ДА":
        return "Рекомендация: типовая BMC/API-проблема. Один из IP пингуется. Сообщение подготовлено, можно наблюдать и ждать RESOLVED."
    if ping_status == "Пинг НЕТ":
        return "Рекомендация: типовая BMC/API-проблема. IP не пингуются. Проверить вебморду/iDRAC. Если вебморда недоступна - писать в Rooms."
    return "Рекомендация: типовая BMC/API-проблема, но ping не удалось определить. Проверить вручную."


def build_rooms_message(data: dict[str, Any], problem: Any) -> str:
    def val(key: str, default: str = "-") -> str:
        value = fix_visible_newlines(data.get(key, default)).strip()
        return value if value else default
    return (
        f"1. Описание проблемы: {fix_visible_newlines(problem).strip()}\n"
        f"2. имя хоста: {val('host')}\n"
        f"3. Модель оборудования: {val('model')}\n"
        f"4. S/N: {val('serial')}\n"
        f"5. {val('dc')}\n"
        f"6. {val('room')}\n"
        f"7. {val('row')}\n"
        f"8. Проект: {DEFAULT_PROJECT}\n"
        f"9. Номер заявки: {DEFAULT_TICKET}\n"
        f"10. Тип поддержки: {val('support')}\n"
        f"11. Отложенный ремонт: {DEFAULT_DEFERRED}\n"
        f"12. Среда: {val('env')}\n"
        f"13. Технический владелец: {val('owner')}"
    )


def import_selenium() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except Exception as error:
        raise ManualSearchError(f"Selenium недоступен: {error}. Установите selenium и Microsoft Edge WebDriver для сбора DCIM.") from error
    return webdriver, By, Options, WebDriverWait, EC


def build_edge_options(options_class: Any, headless: bool = False) -> Any:
    EDGE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    options = options_class()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-data-dir={EDGE_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    if headless:
        options.add_argument("--headless=new")
    return options


def extract_device_id(device_url: str) -> str:
    match = re.search(r"/dcim/devices/(\d+)/", device_url)
    return match.group(1) if match else ""


def open_dcim_card(host: str, log_func: Callable[[str], None], headless: bool = False) -> tuple[str, str, str, Any]:
    webdriver, By, Options, WebDriverWait, EC = import_selenium()
    log_func(f"Открываю Microsoft Edge с профилем: {EDGE_PROFILE_DIR}")
    driver = webdriver.Edge(options=build_edge_options(Options, headless=headless))
    try:
        search_url = DCIM_SEARCH_URL.format(host=host)
        log_func("Открываю DCIM...")
        driver.get(search_url)
        time.sleep(5)
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
        except Exception:
            log_func("Не дождался ссылок, продолжаю поиск по загруженной странице.")
        device_links = []
        for link in driver.find_elements(By.TAG_NAME, "a"):
            text = normalize_spaces(link.text or "")
            href = link.get_attribute("href") or ""
            if "/dcim/devices/" in href:
                device_links.append((text, href))
        target_href = ""
        for text, href in device_links:
            if text.upper() == host.upper():
                target_href = href
                break
        if not target_href:
            for text, href in device_links:
                if host.upper() in text.upper():
                    target_href = href
                    break
        if not target_href and len(device_links) == 1:
            target_href = device_links[0][1]
        if not target_href:
            log_func("Не нашёл ссылку на устройство автоматически.")
            return "", "", search_url, driver
        log_func(f"Открываю карточку: {target_href}")
        driver.get(target_href)
        time.sleep(4)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        return driver.find_element(By.TAG_NAME, "body").text, driver.current_url, search_url, driver
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        raise


def find_occupied_mgmt_port_link(driver: Any, device_url: str, log_func: Callable[[str], None]) -> tuple[str, str]:
    _, By, _, WebDriverWait, EC = import_selenium()
    device_id = extract_device_id(device_url)
    if not device_id:
        log_func("Не смог извлечь device_id из URL карточки.")
        return "", ""
    mgmt_ports_url = f"{DCIM_BASE}/dcim/devices/{device_id}/mgmt-ports/"
    log_func(f"IP в карточке не найден. Открываю MGMT ports: {mgmt_ports_url}")
    driver.get(mgmt_ports_url)
    time.sleep(3)
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        log_func("Не дождался body на странице MGMT ports.")
    mgmt_page_text = driver.find_element(By.TAG_NAME, "body").text
    candidates = []
    for row in driver.find_elements(By.CSS_SELECTOR, "tr"):
        row_text = normalize_spaces(row.text)
        if "занят" in row_text.lower():
            for link in row.find_elements(By.TAG_NAME, "a"):
                href = link.get_attribute("href") or ""
                text = normalize_spaces(link.text)
                if "/dcim/mgmt-ports/" in href:
                    candidates.append((text, href))
    if candidates:
        text, href = candidates[0]
        log_func(f"Нашёл занятый MGMT port: {text} | {href}")
        return href, mgmt_page_text
    all_links = []
    for link in driver.find_elements(By.TAG_NAME, "a"):
        href = link.get_attribute("href") or ""
        text = normalize_spaces(link.text)
        if "/dcim/mgmt-ports/" in href:
            all_links.append((text, href))
    if len(all_links) == 1:
        text, href = all_links[0]
        log_func(f"Ссылка на mgmt-port одна, беру её: {text} | {href}")
        return href, mgmt_page_text
    log_func("Не нашёл занятый MGMT port автоматически.")
    return "", mgmt_page_text


def get_ips_from_mgmt_port_page(driver: Any, mgmt_port_url: str, log_func: Callable[[str], None]) -> tuple[list[str], str, str]:
    if not mgmt_port_url:
        return [], "", ""
    _, By, _, WebDriverWait, EC = import_selenium()
    log_func(f"Открываю страницу MGMT port: {mgmt_port_url}")
    driver.get(mgmt_port_url)
    time.sleep(3)
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        log_func("Не дождался body на странице MGMT port.")
    port_text = driver.find_element(By.TAG_NAME, "body").text
    return find_all_ips(port_text), port_text, driver.current_url


def get_dcim_data_and_ips(host: str, log_func: Callable[[str], None], headless: bool = False) -> tuple[dict[str, Any], list[str], dict[str, str], dict[str, str]]:
    driver = None
    try:
        page_text, dcim_url, search_url, driver = open_dcim_card(host, log_func, headless=headless)
        if not page_text:
            return {}, [], {"dcim_url": dcim_url, "search_url": search_url}, {}
        data = parse_dcim_page(page_text, host)
        ips = find_all_ips(page_text)
        ip_source = "device_card"
        mgmt_ports_url = ""
        mgmt_port_url = ""
        mgmt_ports_text = ""
        mgmt_port_text = ""
        if not ips:
            mgmt_port_url, mgmt_ports_text = find_occupied_mgmt_port_link(driver, dcim_url, log_func)
            if mgmt_port_url:
                ips, mgmt_port_text, current_url = get_ips_from_mgmt_port_page(driver, mgmt_port_url, log_func)
                mgmt_port_url = current_url or mgmt_port_url
                ip_source = "mgmt_port_page"
            device_id = extract_device_id(dcim_url)
            if device_id:
                mgmt_ports_url = f"{DCIM_BASE}/dcim/devices/{device_id}/mgmt-ports/"
        urls = {"search_url": search_url, "dcim_url": dcim_url, "mgmt_ports_url": mgmt_ports_url, "mgmt_port_url": mgmt_port_url, "ip_source": ip_source}
        raw_texts = {"device_page_text": page_text, "mgmt_ports_page_text": mgmt_ports_text, "mgmt_port_page_text": mgmt_port_text}
        return data, ips, urls, raw_texts
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


def build_manual_item(host: str, problem: str) -> dict[str, Any]:
    now = datetime.now()
    return {
        "key": f"manual|{now.isoformat()}|{host}|{problem}",
        "stable_key": f"manual|{make_problem_stable_key(host, problem)}|{now.isoformat()}",
        "event_dt": now,
        "host": host,
        "problem": problem,
        "raw": f"MANUAL INPUT\n{now}\n{host}\n{problem}",
        "source": "manual",
    }


def run_manual_search(
    host: Any,
    problem: Any,
    *,
    headless: bool = False,
    collect_dcim: bool = True,
    rules_dir: str | Path | None = None,
) -> dict[str, Any]:
    logs: list[str] = []

    def log(message: str) -> None:
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    host = normalize_spaces(host)
    problem = fix_visible_newlines(problem).strip()
    host_ok, host_msg = validate_hostname(host)
    if not host_ok:
        raise ManualSearchError(host_msg)
    problem_ok, problem_msg = validate_problem_text(problem)
    if not problem_ok:
        raise ManualSearchError(problem_msg)
    item = build_manual_item(host, problem)
    log("Старт ручной обработки проблемы.")
    log(f"Источник: {item['source']}")
    log(f"Host: {host}")
    log(f"Problem: {problem}")

    if collect_dcim:
        data, ips, urls, raw_texts = get_dcim_data_and_ips(host, log, headless=headless)
        if not data:
            raise ManualSearchError("Не удалось получить данные из DCIM.")
    else:
        data = {"host": host, "model": "-", "serial": "-", "dc": "-", "room": "-", "row": "-", "support": DEFAULT_SUPPORT, "env": "-", "owner": "-", "information_system": "-"}
        ips = []
        urls = {"search_url": DCIM_SEARCH_URL.format(host=host), "dcim_url": "", "mgmt_ports_url": "", "mgmt_port_url": "", "ip_source": "skipped"}
        raw_texts = {}

    missing_fields = [field for field in ["host", "model", "serial", "dc", "room", "row"] if not data.get(field) or data.get(field) == "-"]
    if missing_fields:
        log("Предупреждение: часть полей DCIM не найдена: " + ", ".join(missing_fields))
    log("Данные DCIM получены.")
    log(f"Модель: {data.get('model', '-')}")
    log(f"S/N: {data.get('serial', '-')}")
    log(f"Локация: {data.get('dc', '-')} / {data.get('room', '-')} / {data.get('row', '-')}")
    log(f"Технический владелец: {data.get('owner', '-')}")
    log("Найдено IP: " + ", ".join(ips) if ips else "IP не найдены автоматически.")
    ping_status, ping_results = ping_all_ips(ips, log)
    for ip, status in ping_results:
        log(f"{ip}: {status}")
    problem_type = classify_problem(problem)
    recommendation = make_recommendation(data.get("model", "-"), problem, ping_status, ips)
    task_tag, task_status_label = classify_task_status(problem, ping_status, item)
    message = build_rooms_message(data, problem)
    routing = resolve_hostname_routing(
        host,
        rules_dir=Path(rules_dir) if rules_dir is not None else None,
    )
    for routing_warning in routing.warnings:
        log(f"Предупреждение маршрутизации: {routing_warning}")
    for routing_error in routing.errors:
        log(f"Ошибка маршрутизации: {routing_error}")
    recipients = list(routing.to)
    cc_recipients = list(routing.cc)
    matched_rules = list(routing.matched_rules)
    email_subject = ""
    email_body = ""
    email_text = ""
    if routing.email_ready:
        email_subject = build_email_subject(routing.tag, host, problem)
        email_body = build_email_body(host, problem, message)
        email_text = build_email_text(email_subject, recipients, cc_recipients, email_body)
        log(f"Проект письма: {routing.project} ({routing.tag})")
        log(f"Кому: {'; '.join(recipients)}")
        log(f"Копия: {'; '.join(cc_recipients) if cc_recipients else '-'}")
    routing_message = "\n".join([*routing.errors, *routing.warnings])
    return {"ok": True, "event": {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "source": item["source"],
        "zabbix_event_time": item["event_dt"].strftime("%Y-%m-%d %H:%M:%S"), "input_host": host,
        "host": data.get("host", host), "problem": problem, "problem_type": problem_type,
        "task_tag": task_tag, "task_status": task_status_label, "model": data.get("model", "-"),
        "serial": data.get("serial", "-"), "dc": data.get("dc", "-"), "room": data.get("room", "-"),
        "row": data.get("row", "-"), "support": data.get("support", "-"), "deferred": DEFAULT_DEFERRED,
        "env": data.get("env", "-"), "owner": data.get("owner", "-"),
        "information_system": data.get("information_system", "-"), "ips": ips, "ping_status": ping_status,
        "ping_results": [{"ip": ip, "status": status} for ip, status in ping_results],
        "ip_source": urls.get("ip_source", "-"), "urls": urls, "recommendation": recommendation,
        "business_note": "", "message": message, "email_recipients": recipients,
        "email_to": recipients, "email_cc": cc_recipients, "email_project": routing.project,
        "email_tag": routing.tag, "email_ready": routing.email_ready,
        "email_routing_warning": routing_message, "email_matched_rules": matched_rules,
        "email_subject": email_subject, "email_body": email_body, "email_text": email_text,
        "logs": logs,
    }, "raw_text_available": bool(raw_texts)}
