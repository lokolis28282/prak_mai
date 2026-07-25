"""Application-wide configuration and feature flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeatureFlags:
    FEATURE_WAREHOUSE: bool = True
    FEATURE_REPORTS: bool = True
    FEATURE_MONITORING: bool = False
    FEATURE_MOBILE: bool = False
    FEATURE_EXTERNAL_API: bool = False


@dataclass
class RuntimeConfig:
    db_path: Path
    feature_flags: FeatureFlags = field(default_factory=FeatureFlags)
    warehouse_contour: str = "unknown"
    production_db_path: Path | None = None
    full_inventory_state_root: Path | None = None
    settings: dict[str, Any] = field(default_factory=dict)
