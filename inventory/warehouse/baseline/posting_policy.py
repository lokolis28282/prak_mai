"""Fail-closed posting policy for the pre-baseline Warehouse."""

from __future__ import annotations

import os
from pathlib import Path

from inventory.shared.validators import WarehouseError


class WarehousePostingBlocked(WarehouseError):
    code = "WAREHOUSE_NOT_INITIALIZED"

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "Склад не инициализирован полной инвентаризацией; "
            "операции прихода, расхода и перемещения заблокированы"
        )


def _same_file(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


class PostingPolicy:
    """Allow mutations only for an explicitly configured disposable contour."""

    VALID_MODES = {"production", "demo"}

    def __init__(
        self,
        db_path: str | Path,
        *,
        mode: str,
        production_db_path: str | Path,
    ):
        self.db_path = Path(db_path).expanduser().resolve()
        self.production_db_path = Path(production_db_path).expanduser().resolve()
        self.mode = str(mode or "").strip().lower()
        self._configuration_error = ""
        if self.mode not in self.VALID_MODES:
            self._configuration_error = "Неизвестный режим Warehouse contour"
        elif self.mode == "demo" and _same_file(self.db_path, self.production_db_path):
            self._configuration_error = "Demo contour указывает на рабочую базу"

    @property
    def demo(self) -> bool:
        return self.mode == "demo" and not self._configuration_error

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode or "unknown",
            "demo": self.demo,
            "posting_allowed": self.demo,
            "configuration_ok": not self._configuration_error,
            "configuration_error": self._configuration_error,
        }

    def assert_mutation_allowed(self, operation: str = "") -> None:
        if self.demo:
            return
        detail = f" ({operation})" if operation else ""
        if self._configuration_error:
            raise WarehousePostingBlocked(
                f"WAREHOUSE_NOT_INITIALIZED: {self._configuration_error}{detail}"
            )
        raise WarehousePostingBlocked(
            "WAREHOUSE_NOT_INITIALIZED: склад доступен только для просмотра "
            f"до публикации initial baseline{detail}"
        )
