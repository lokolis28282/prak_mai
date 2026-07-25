"""External FULL inventory preview contour for the legacy Warehouse runtime."""

from typing import TYPE_CHECKING, Any

from .models import SystemState
from .posting_policy import PostingPolicy, WarehousePostingBlocked

if TYPE_CHECKING:
    from .service import FullInventoryService


def __getattr__(name: str) -> Any:
    if name == "FullInventoryService":
        from .service import FullInventoryService

        return FullInventoryService
    raise AttributeError(name)

__all__ = (
    "FullInventoryService",
    "PostingPolicy",
    "SystemState",
    "WarehousePostingBlocked",
)
