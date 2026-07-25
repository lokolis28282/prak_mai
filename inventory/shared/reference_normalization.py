"""Syntactic normalization shared by runtime and offline Reference Data flows.

These helpers are intentionally unsuitable for serial numbers: whitespace and
Unicode normalization are safe for reference aliases but not for S/N identity.
"""

from __future__ import annotations

import re
import unicodedata


_SPACE_RUN = re.compile(r"\s+", flags=re.UNICODE)


def clean_reference_display(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _SPACE_RUN.sub(" ", normalized.strip())


def normalize_reference_key(value: str) -> str:
    return clean_reference_display(value).casefold()
