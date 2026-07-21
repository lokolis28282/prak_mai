"""Deterministic warehouse-card classification and safe display cleanup.

The classifier deliberately never changes identifiers (S/N, inventory number,
PN, order/request numbers).  It only derives operational type fields from the
descriptive evidence already stored on a card.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class Classification:
    field: str
    value: str
    confidence: str
    rule: str

    @property
    def category(self) -> str:
        values = {
            "equipment_type": "",
            "component_type": "",
            "cable_type": "",
        }
        values[self.field] = self.value
        return operational_category(**values)


WAREHOUSE_CATEGORY_ORDER = (
    "Оборудование",
    "Трансиверы",
    "Память",
    "Накопители",
    "Адаптеры и контроллеры",
    "Комплектующие",
    "Кабели",
    "Кабельные сборки",
    "Другое оборудование",
)


def operational_category(
    equipment_type: object = "",
    component_type: object = "",
    cable_type: object = "",
) -> str:
    """Map approved warehouse types to operator-facing balance groups."""

    cable = clean_display(cable_type).casefold()
    equipment = clean_display(equipment_type).casefold()
    component = clean_display(component_type).casefold()
    if cable in {"aoc", "dac"}:
        return "Кабельные сборки"
    if cable:
        return "Кабели"
    item_type = component or equipment
    if item_type in {"трансивер", "transceiver"}:
        return "Трансиверы"
    if item_type in {"оперативная память", "memory", "ram"}:
        return "Память"
    if item_type in {"ssd", "hdd"}:
        return "Накопители"
    if item_type in {
        "сетевой адаптер", "nic", "hba-адаптер", "hba",
        "raid-контроллер", "raid controller",
    }:
        return "Адаптеры и контроллеры"
    if item_type in {"аксессуар", "accessory"}:
        return "Другое оборудование"
    if component in {"прочий компонент", "other"}:
        return "Другое оборудование"
    if component:
        return "Комплектующие"
    if equipment in {"прочее оборудование", "other"} or not equipment:
        return "Другое оборудование"
    return "Оборудование"


EQUIPMENT_TYPE_DISPLAY = {
    "server": "Сервер",
    "switch": "Коммутатор",
    "storage system": "Система хранения данных",
    "san switch": "SAN-коммутатор",
    "load balancer": "Балансировщик нагрузки",
    "pdu": "PDU",
    "ups": "ИБП",
    "router": "Маршрутизатор",
    "other": "Прочее оборудование",
    "usb dongle server": "USB-сервер ключей",
}

COMPONENT_TYPE_DISPLAY = {
    "cpu": "Процессор",
    "memory": "Оперативная память",
    "ssd": "SSD",
    "hdd": "HDD",
    "nic": "Сетевой адаптер",
    "hba": "HBA-адаптер",
    "raid controller": "RAID-контроллер",
    "psu": "Блок питания",
    "fan": "Вентилятор",
    "transceiver": "Трансивер",
    "motherboard": "Материнская плата",
    "gpu": "GPU",
    "board": "Плата",
    "chassis": "Шасси",
    "accessory": "Аксессуар",
    "components": "Комплектующие",
    "other": "Прочий компонент",
}

CABLE_TYPE_DISPLAY = {
    "utp": "UTP",
    "om4": "OM4",
    "mtp": "MTP",
    "aoc": "AOC",
    "dac": "DAC",
    "other": "Прочий кабель",
}


VENDOR_CANONICAL = {
    "avago": "AVAGO",
    "avaya": "AVAYA",
    "brocade": "Brocade",
    "cisco": "Cisco",
    "citrix": "Citrix",
    "dataru": "ДатаРу",
    "датару": "ДатаРу",
    "dell": "Dell",
    "dell inc": "Dell",
    "dell inc.": "Dell",
    "finisar": "Finisar",
    "huawei": "Huawei",
    "intel": "Intel",
    "intel corporation": "Intel",
    "juniper": "Juniper",
    "kioxia": "Kioxia",
    "kioxia corporation": "Kioxia",
    "mellanox": "Mellanox",
    "connectx": "Mellanox",
    "micron": "Micron",
    "modultech": "Modultech",
    "netwell": "Netwell",
    "nio electronics": "NIO Electronics",
    "palo alto": "Palo Alto",
    "ruijie": "Ruijie Networks",
    "ruijie networks": "Ruijie Networks",
    "solidigm": "Solidigm",
    "xfusion": "xFusion",
    "check point": "Check Point Software",
    "ceckpoint": "Check Point Software",
    "check point software": "Check Point Software",
}

INVALID_VENDOR_VALUES = frozenset({"?", "???", "unknown", "n/a", "#n/a", "null", "jbod"})
INVALID_MODEL_VALUES = frozenset({"?", "???", "unknown", "n/a", "#n/a", "null", "добавить название", "указать имя хоста"})
INVALID_ITEM_VALUES = frozenset({
    "?", "???", "unknown", "n/a", "#n/a", "null", "добавить название",
    "указать имя хоста",
})
UNKNOWN_ITEM_NAME = "Историческая позиция — наименование не восстановлено"


def clean_display(value: object) -> str:
    """Normalize safe presentation whitespace without touching identifiers."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def canonical_vendor(value: object) -> str:
    display = clean_display(value)
    key = display.casefold()
    if key in INVALID_VENDOR_VALUES:
        return ""
    return VENDOR_CANONICAL.get(key, display)


def clean_model(value: object) -> str:
    display = clean_display(value)
    return "" if display.casefold() in INVALID_MODEL_VALUES else display


def clean_item_name(value: object) -> str:
    display = clean_display(value)
    return UNKNOWN_ITEM_NAME if display.casefold() in INVALID_ITEM_VALUES else display


def infer_vendor(item_name: object, model: object, part_number: object = "") -> str:
    text = " ".join(clean_display(value) for value in (item_name, model, part_number)).casefold()
    patterns = (
        (r"\bdell(?:emc)?\b|\bpoweredge\b", "Dell"),
        (r"\bxfusion\b", "xFusion"),
        (r"\bhuawei\b|\bcloudengine\b", "Huawei"),
        (r"\bhpe\b", "HPE"),
        (r"\bhp\b|\bproliant\b", "HP"),
        (r"\bsk hynix\b|\bhynix\b", "Hynix"),
        (r"\bsamsung\b", "Samsung"),
        (r"\bmicron\b|\bmtfd[a-z0-9]+\b", "Micron"),
        (r"\bkioxia\b|\bkc[dm][a-z0-9]+\b", "Kioxia"),
        (r"\bsolidigm\b", "Solidigm"),
        (r"\bintel\b|\bssdp[a-z0-9]+\b", "Intel"),
        (r"\bseagate\b|\bexos\b", "Seagate"),
        (r"\bwestern digital\b", "Western Digital"),
        (r"\bkingston\b", "Kingston"),
        (r"\bmellanox\b|\bconnectx\b|\bmcx\d", "Mellanox"),
        (r"\bnvidia\b|\bquadro\b|\brtx\s*8000\b", "NVIDIA"),
        (r"\blenovo\b|\bthinksystem\b", "Lenovo"),
        (r"\bjuniper\b", "Juniper"),
        (r"\bcisco\b|\bnexus\b", "Cisco"),
        (r"\bbrocade\b", "Brocade"),
        (r"\bfibo\b", "FIBO"),
        (r"\bruijie\b", "Ruijie Networks"),
        (r"\bfinisar\b", "Finisar"),
        (r"\byadro\b", "YADRO"),
        (r"\bvegman\b", "Vegman"),
        (r"\bnetapp\b", "NetApp"),
        (r"\bbroadcom\b", "Broadcom"),
    )
    for pattern, vendor in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return vendor
    return ""


def _classification(field: str, value: str, rule: str, confidence: str = "HIGH") -> Classification:
    return Classification(field, value, confidence, rule)


def classify_card(
    *,
    item_name: object,
    vendor: object = "",
    model: object = "",
    part_number: object = "",
    equipment_type: object = "",
    component_type: object = "",
    cable_type: object = "",
) -> Classification:
    """Classify one card from descriptive fields, with existing type as fallback."""

    text = " ".join(clean_display(value) for value in (item_name, vendor, model, part_number)).casefold()

    rules: tuple[tuple[str, str, str, str], ...] = (
        (r"(?:^|\W)dac(?:\W|$)|dac[- ]?кабел|1002973501|(?:^|[-_])cu(?:1|2|3|5|7|10)m(?:[-_\s]|$)", "cable_type", "DAC", "DAC"),
        (r"(?:^|\W)aoc(?:\W|$)|active optical cable|активн\w* оптическ\w* кабел", "cable_type", "AOC", "AOC"),
        (r"\butp\b", "cable_type", "UTP", "UTP"),
        (r"\bom4\b", "cable_type", "OM4", "OM4"),
        (r"\bmtp\b", "cable_type", "MTP", "MTP"),
        (r"кабел|\bcable\b|патч[- ]?корд|patch[ -]?cord", "cable_type", "Прочий кабель", "GENERIC_CABLE"),
        (r"\bсхд\b|storage system|storeserv|dellemc.*storage|\bpowerstore\b|\bnetapp\b|\bjbod\b|полк\w* (?:расшир|р-я)|\bdorado\s*5000\b|\bsc220\b|\bprimera\b|\bts4300\b", "equipment_type", "Система хранения данных", "STORAGE"),
        (r"\bpan-pa-5400-nc-a\b", "component_type", "Сетевой адаптер", "NIC_MODEL"),
        (r"check\s+point|\bqp-?10\b|\bpan-pa-?\d+\b|palo\s+alto.*\bpa-?\d+", "equipment_type", "Межсетевой экран", "FIREWALL"),
        (r"load balanc|балансировщик|citrix\s+mpx|\bradware\b|\balteon\b", "equipment_type", "Балансировщик нагрузки", "LOAD_BALANCER"),
        (r"маршрутизатор|(?:^|\W)router(?:\W|$)|juniper\s+mx-?\d|(?:^|\W)mx-?(?:204|304)(?:\W|$)|\bisr\d{4}\b|медиа-шлюз|media gateway", "equipment_type", "Маршрутизатор", "ROUTER"),
        (r"^сервер\b.*(?:\bxe9680\b|\bpoweredge\b|\b2288[hx]?\b|\br220\b)", "equipment_type", "Сервер", "SERVER_EXPLICIT"),
        (r"cloudengine|(?:^|\W)ce\d{4}[a-z0-9-]*|(?:^|\W)xh\d{4}[a-z0-9-]*", "equipment_type", "Коммутатор", "SWITCH_MODEL"),
        (r"бэкплейн|backplane", "component_type", "Плата", "BACKPLANE"),
        (r"(?:^|\W)hba(?:\W|$)|\bemulex\b|\blpe\d|9500-8e|карта\s+san", "component_type", "HBA-адаптер", "HBA"),
        (r"\bnic\b|\bconnectx\b|\bmcx\d|\bcx\d{5,}\w*\b|\bx710\b|\be810\b|562\s*(?:flr-)?sfp|631\s*(?:flr-)?sfp|\bxl710\b|\bxxv710\b|\brndc\b|\bql41112\b", "component_type", "Сетевой адаптер", "NIC_MODEL"),
        (r"\bssd\b|\bссд\b|solid state|\bmicron\b.*\b(?:7450|7500)\b|\b(?:7450|7500)\b.*\bmicron\b|\bd7-p55\d+\b|\bmtfdk[a-z0-9]+\b|\bssdpf[a-z0-9]+\b|\bkcd[a-z0-9]+\b|\bkcm[a-z0-9]+\b|\bpm173[35]\b|\bsm883\b|\bsedc[a-z0-9/]+\b|\bhfs\d+[a-z0-9]+\b", "component_type", "SSD", "SSD"),
        (r"\bhdd\b|(?:^|\W)жд(?:\W|$)|ж[её]стк\w* диск|hard disk|\bexos\b", "component_type", "HDD", "HDD"),
        (r"оперативн\w* памят|модул[ья]\s+памят|(?:^|\W)озу(?:\W|$)|\bddr[345]\b|\b[lr]?dimm\b|\bmicron\b.*\b64gb\b.*\b3200mhz\b|\bhma[a-z0-9-]+\b|\bh1xv[a-z0-9]+\b|\bm393[a-z0-9-]+\b|\bksm\d", "component_type", "Оперативная память", "MEMORY"),
        (r"(?:^|\W)gpu(?:\W|$)|(?:^|\W)гпу(?:\W|$)|\bquadro\b|\brtx\s*\d|tesla\s+[a-z0-9]", "component_type", "GPU", "GPU"),
        (r"(?:^|\W)cpu(?:\W|$)|процессор|\bxeon\b|\bepyc\b", "component_type", "Процессор", "CPU"),
        (r"raid|рейд|\bperc\b|boss-s1|\bh7[34]0p?\b|\bh345\b|930-16i|9500-16i|storage cntlr|storage controller", "component_type", "RAID-контроллер", "RAID"),
        (r"блок\s+питан|(?:^|\W)бп(?:\W|$)|(?:^|\W)psu(?:\W|$)|pwr\s+sply|power supply", "component_type", "Блок питания", "PSU"),
        (r"вентилят|(?:^|\W)fan(?:\W|$)|fan tray", "component_type", "Вентилятор", "FAN"),
        (r"мат(?:еринск\w*)?[.\s-]*карт|материнск\w* плат|motherboard|system board", "component_type", "Материнская плата", "MOTHERBOARD"),
        (r"линейн\w* карт|(?:^|\W)r(?:iser|aiser)(?:\W|$)|райзер|\bnim-24a\b|\bpcie\s*4\.0\s*x\d|\bcex-[a-z0-9-]+\b|\bmpud\b|\blmic\w*\b", "component_type", "Плата", "BOARD"),
        (r"батаре|battery|аккумуля|rail kit|комплект креп|bezel|usb\s+концентратор", "component_type", "Аксессуар", "ACCESSORY"),
        (r"трансив|optical transceiver|оптическ\w* модул|(?:^|\W)[qo]?sfp(?:\+|\d|\W)|\bqsfp\w*\b|\bomxd\d+\b|\bfibo-(?:ft-)?s\d", "component_type", "Трансивер", "TRANSCEIVER"),
        (r"сетев\w* адаптер|сетев\w* карт|network (?:interface )?(?:card|adapter)|ethernet adapter|ethernet network adapter", "component_type", "Сетевой адаптер", "NIC"),
        (r"san[- ]?коммут|san\s+switch", "equipment_type", "SAN-коммутатор", "SAN_SWITCH"),
        (r"коммутатор|network\s+switch|cloudengine|(?:^|\W)ce\d{4}[a-z0-9-]*|\bxh9210|brocade.*\bds\d|\bds7720\b|\bws-c\d", "equipment_type", "Коммутатор", "SWITCH"),
        (r"сервер|(?:^|\W)server(?:\W|$)|poweredge|proliant|(?:^|\W)dl3[568]0(?:\W|$)|(?:^|\W)sr6\d{2}(?:\W|$)|(?:^|\W)xe9680(?:\W|$)|(?:^|\W)2288[hx](?:\W|$)|(?:^|\W)h22h(?:\W|$)|(?:^|\W)r220(?:\W|$)|(?:^|\W)pi750(?:\W|$)|\baquarius\s+t40\b", "equipment_type", "Сервер", "SERVER"),
        (r"\bmyutn-?800\b|dongleserver", "equipment_type", "USB-сервер ключей", "USB_DONGLE_SERVER"),
        (r"шасси|(?:^|\W)chassis(?:\W|$)|enclosure|drivebay", "component_type", "Шасси", "CHASSIS"),
        (r"(?:^|\W)(?:плата|карта)(?:\W|$)", "component_type", "Плата", "GENERIC_BOARD"),
    )
    for pattern, field, value, rule in rules:
        if re.search(pattern, text, re.IGNORECASE):
            return _classification(field, value, rule)

    existing = (
        ("equipment_type", clean_display(equipment_type), EQUIPMENT_TYPE_DISPLAY),
        ("component_type", clean_display(component_type), COMPONENT_TYPE_DISPLAY),
        ("cable_type", clean_display(cable_type), CABLE_TYPE_DISPLAY),
    )
    for field, display, mapping in existing:
        if not display:
            continue
        value = mapping.get(display.casefold(), display)
        if value not in {"Прочее оборудование", "Прочий компонент", "Прочий кабель"}:
            return _classification(field, value, "EXISTING_TYPE", "MEDIUM")

    if re.search(r"комплектующ", text, re.IGNORECASE):
        return _classification("component_type", "Комплектующие", "COMPONENTS")
    if re.search(r"компонент", text, re.IGNORECASE):
        return _classification("component_type", "Комплектующие", "GENERIC_COMPONENT")

    if "оборудован" in text:
        return _classification("equipment_type", "Прочее оборудование", "UNRESOLVED_EQUIPMENT", "LOW")
    return _classification("component_type", "Прочий компонент", "UNRESOLVED", "LOW")


def semantic_type(field: str, value: object) -> tuple[str, str]:
    """Return a language-independent comparison key for before/after metrics."""

    display = clean_display(value)
    mappings = {
        "equipment_type": EQUIPMENT_TYPE_DISPLAY,
        "component_type": COMPONENT_TYPE_DISPLAY,
        "cable_type": CABLE_TYPE_DISPLAY,
    }
    reverse = {label.casefold(): key for key, label in mappings.get(field, {}).items()}
    key = display.casefold()
    return field, reverse.get(key, key)
