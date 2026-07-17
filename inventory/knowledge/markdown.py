"""Small safe Markdown renderer for knowledge articles.

Raw HTML is always escaped. The supported subset intentionally matches the
editor help: headings, paragraphs, lists, emphasis, links and fenced code.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_UNORDERED = re.compile(r"^\s*[-+*]\s+(.+)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _safe_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https", "mailto"}:
        return None
    return value.strip()


def _inline(value: str) -> str:
    tokens: list[str] = []

    def stash(markup: str) -> str:
        tokens.append(markup)
        return f"\x00ODE{len(tokens) - 1}\x00"

    def code_replacement(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(match.group(1), quote=True)}</code>")

    protected = _CODE_SPAN.sub(code_replacement, value)

    def link_replacement(match: re.Match[str]) -> str:
        url = _safe_url(match.group(2))
        if url is None:
            return match.group(0)
        label = html.escape(match.group(1), quote=True)
        href = html.escape(url, quote=True)
        return stash(f'<a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a>')

    protected = _LINK.sub(link_replacement, protected)
    rendered = html.escape(protected, quote=True)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", rendered)
    for index, token in enumerate(tokens):
        rendered = rendered.replace(f"\x00ODE{index}\x00", token)
    return rendered


def render_markdown(source: str) -> str:
    """Render the supported Markdown subset without allowing raw HTML."""
    lines = str(source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_kind = ""
    list_items: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            output.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_kind
        if list_items:
            tag = "ol" if list_kind == "ol" else "ul"
            output.append(f"<{tag}>" + "".join(f"<li>{_inline(item)}</li>" for item in list_items) + f"</{tag}>")
            list_items.clear()
        list_kind = ""

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                output.append("<pre><code>" + html.escape("\n".join(code_lines), quote=True) + "</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                flush_paragraph()
                flush_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        heading = _HEADING.match(line)
        unordered = _UNORDERED.match(line)
        ordered = _ORDERED.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif unordered or ordered:
            flush_paragraph()
            wanted = "ul" if unordered else "ol"
            if list_kind and list_kind != wanted:
                flush_list()
            list_kind = wanted
            list_items.append((unordered or ordered).group(1))
        else:
            flush_list()
            paragraph.append(line)
    if in_code:
        output.append("<pre><code>" + html.escape("\n".join(code_lines), quote=True) + "</code></pre>")
    flush_paragraph()
    flush_list()
    return "\n".join(output)
