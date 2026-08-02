#!/usr/bin/env python3
"""Audit static HTML id usage from frontend JavaScript.

The audit is intentionally conservative: it checks only literal static ids from
getElementById("..."), byId("...") and querySelector("#..."). Dynamic ids are
reported only when they are known static strings and not whitelisted.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBAPP = ROOT / "inventory" / "webapp.py"
STATIC_JS = ROOT / "static" / "js"


# Ids created dynamically by legacy UI code or intentionally outside the main
# HTML shell. Keep this list small and add a reason near every group.
DYNAMIC_ID_WHITELIST = {
    # Login page ids live in LOGIN_HTML, not in the authenticated app shell.
    "admin",
    "engineer",
    "error",
    "login",
    "mode",
    "submit",
    # Preview containers can be created lazily by renderPreview(kind, ...).
    "bulk_issuePreview",
    "deliveryPreview",
    "receiptPreview",
    "issuePreview",
    # УВР edit modal builds this form dynamically in openUvrEdit().
    "uvrEditForm",
    # Engineer UX creates these controls after load.
    "activeDrafts",
    "balanceFilterSummary",
    "balanceKpis",
    "balancePager",
    "balanceSummary",
    "balanceScope",
    "cableIssueForm",
    "deliveryScanner",
    "deliveryScanResult",
    "deliveryFillField",
    "deliveryFillValue",
    # Delivery detail renders its selection menu and paginated table only
    # after a concrete delivery has been opened.
    "deliveryLines",
    "deliverySelectMenu",
    "deliverySelectTrigger",
    "movementViewHeading",
    # Monitoring builds its manual-search form, result and history lazily.
    "monitoringManualForm",
    "monitoringManualHistory",
    "monitoringManualHost",
    "monitoringManualResult",
    # Pair scanner controls are created after the Warehouse shell is ready.
    "issuePairPrompt",
    "issueScanModes",
    # Reference editor builds its table body after the permission-checked API
    # returns the selected canonical domain.
    "referenceEditorBody",
    # Product shell creates the global-search lupe modal (input, result panel,
    # the dialog wrapper and its trigger button) after load.
    "globalSearch",
    "globalSearchResults",
    "globalSearchModal",
    "globalSearchTrigger",
    "shiftProfileCard",
    # Multi-warehouse shell adds the active-site switcher after /api/data.
    "warehouseSiteSwitcher",
    # The marker-guarded review is created only for an administrator after
    # /api/data confirms the selected review database.
    "migration_pilot",
    "migrationPilotBody",
    "migrationPilotCounts",
    "migrationPilotDatabase",
    "migrationPilotFilters",
    "migrationPilotQuery",
    "migrationPilotResultCount",
    "migrationPilotSearch",
    "migrationFullModel",
    "migrationFullVendor",
    "simpleReceiptForm",
    "simpleReceiptTitle",
    "uxBalanceCategory",
    "uxBalanceProject",
    "uxBalanceSupplier",
    "uxBalanceSort",
    "uxBalanceStock",
    "uxBalanceType",
    "uxBalanceVendor",
    "wDc",
    "wProject",
    "wShelf",
    "wSupplier",
}


@dataclass(frozen=True)
class IdUse:
    source: str
    line: int
    expression: str
    element_id: str


@dataclass
class ButtonUse:
    attributes: dict[str, str]
    text: str
    form_depth: int


class StaticControlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.buttons: list[ButtonUse] = []
        self._form_depth = 0
        self._button_attributes: dict[str, str] | None = None
        self._button_text: list[str] = []
        self._button_form_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "form":
            self._form_depth += 1
        if tag == "button":
            self._button_attributes = attributes
            self._button_text = []
            self._button_form_depth = self._form_depth

    def handle_data(self, data: str) -> None:
        if self._button_attributes is not None:
            self._button_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._button_attributes is not None:
            self.buttons.append(
                ButtonUse(
                    attributes=self._button_attributes,
                    text=" ".join("".join(self._button_text).split()),
                    form_depth=self._button_form_depth,
                )
            )
            self._button_attributes = None
            self._button_text = []
        if tag == "form":
            self._form_depth -= 1


def line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def html_ids() -> set[str]:
    sys.path.insert(0, str(ROOT))
    from inventory import webapp

    html = "\n".join([webapp.LOGIN_HTML, webapp.HTML])
    return set(re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", html))


def source_files() -> list[Path]:
    files = [WEBAPP]
    if STATIC_JS.exists():
        files.extend(sorted(STATIC_JS.rglob("*.js")))
    return files


def static_control_violations() -> tuple[int, list[str]]:
    sys.path.insert(0, str(ROOT))
    from inventory import webapp

    parser = StaticControlParser()
    parser.feed("\n".join([webapp.LOGIN_HTML, webapp.HTML]))
    violations: list[str] = []
    duplicate_ids = sorted(
        {
            element_id
            for element_id in parser.ids
            if parser.ids.count(element_id) > 1
        }
    )
    violations.extend(f"duplicate HTML id: {element_id}" for element_id in duplicate_ids)

    javascript = "\n".join(
        path.read_text(encoding="utf-8") for path in source_files()
    )
    for index, button in enumerate(parser.buttons, start=1):
        attributes = button.attributes
        label = button.text or attributes.get("aria-label") or attributes.get("title")
        if not label:
            violations.append(f"button #{index} has no accessible label")
        if attributes.get("disabled") is not None:
            continue
        if button.form_depth or attributes.get("onclick"):
            continue
        element_id = attributes.get("id", "")
        classes = attributes.get("class", "").split()
        id_bound = bool(
            element_id
            and re.search(rf"['\"#]{re.escape(element_id)}['\"]", javascript)
        )
        class_bound = any(f".{class_name}" in javascript for class_name in classes)
        if not id_bound and not class_bound:
            violations.append(
                f"button #{index} ({label or 'unnamed'}) has no static JS binding"
            )

    for forbidden in ("restoreBackup", "prodDb"):
        if forbidden in parser.ids:
            violations.append(f"fail-closed control leaked into runtime HTML: {forbidden}")
    if "runtimeRestoreStatus" not in parser.ids:
        violations.append("runtime restore fail-closed status is absent")
    return len(parser.buttons), violations


def id_uses(path: Path) -> list[IdUse]:
    text = path.read_text(encoding="utf-8")
    uses: list[IdUse] = []
    literal_call = re.compile(
        r"""\b(?P<fn>getElementById|byId)\s*\(\s*(?P<quote>['"])(?P<id>[A-Za-z][\w:.-]*)(?P=quote)\s*\)"""
    )
    selector_call = re.compile(
        r"""\bquerySelector(?:All)?\s*\(\s*(?P<quote>['"])(?P<selector>[^'"]*#[^'"]+)(?P=quote)\s*\)"""
    )
    for match in literal_call.finditer(text):
        uses.append(
            IdUse(
                source=str(path.relative_to(ROOT)),
                line=line_number(text, match.start()),
                expression=match.group(0),
                element_id=match.group("id"),
            )
        )
    for match in selector_call.finditer(text):
        selector = match.group("selector")
        for element_id in re.findall(r"#([A-Za-z][\w:.-]*)", selector):
            uses.append(
                IdUse(
                    source=str(path.relative_to(ROOT)),
                    line=line_number(text, match.start()),
                    expression=match.group(0),
                    element_id=element_id,
                )
            )
    return uses


def main() -> int:
    known_ids = html_ids()
    uses = [use for path in source_files() for use in id_uses(path)]
    missing = [
        use for use in uses
        if use.element_id not in known_ids and use.element_id not in DYNAMIC_ID_WHITELIST
    ]
    button_count, control_violations = static_control_violations()
    print(f"frontend-contracts: html ids={len(known_ids)} static references={len(uses)}")
    if missing or control_violations:
        print("frontend-contracts: missing static ids")
        for use in missing:
            print(f"- {use.element_id}: {use.source}:{use.line} {use.expression}")
        for violation in control_violations:
            print(f"- {violation}")
        return 1
    print(
        "frontend-contracts: OK, no missing static ids; "
        f"{button_count} static buttons have labels and bindings"
    )
    if DYNAMIC_ID_WHITELIST:
        print("frontend-contracts: dynamic whitelist=" + ",".join(sorted(DYNAMIC_ID_WHITELIST)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
