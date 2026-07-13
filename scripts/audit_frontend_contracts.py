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
    # Engineer UX creates these controls after load.
    "activeDrafts",
    "balanceKpis",
    "balanceScope",
    "cableIssueForm",
    "dailyLogDate",
    "dailyLogRows",
    "deliveryScanner",
    "deliveryScanResult",
    "deliveryFillField",
    "deliveryFillValue",
    # Product shell creates the global-search lupe modal (input, result panel,
    # the dialog wrapper and its trigger button) after load.
    "globalSearch",
    "globalSearchResults",
    "globalSearchModal",
    "globalSearchTrigger",
    "shiftProfileCard",
    "simpleReceiptForm",
    "simpleReceiptTitle",
    "uxBalanceCategory",
    "uxBalanceProject",
    "uxBalanceType",
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
    print(f"frontend-contracts: html ids={len(known_ids)} static references={len(uses)}")
    if missing:
        print("frontend-contracts: missing static ids")
        for use in missing:
            print(f"- {use.element_id}: {use.source}:{use.line} {use.expression}")
        return 1
    print("frontend-contracts: OK, no missing static ids")
    if DYNAMIC_ID_WHITELIST:
        print("frontend-contracts: dynamic whitelist=" + ",".join(sorted(DYNAMIC_ID_WHITELIST)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
