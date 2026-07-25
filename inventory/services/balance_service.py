"""Stock balance and position-card service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class BalanceService(ServiceAdapter):
    def dashboard_stats(self, *args: Any, **kwargs: Any) -> Any: return self.call("dashboard_stats", *args, **kwargs)
    def balance_by_category(self, *args: Any, **kwargs: Any) -> Any: return self.call("balance_by_category", *args, **kwargs)
    def warehouse_categories(self, *args: Any, **kwargs: Any) -> Any: return self.call("warehouse_categories", *args, **kwargs)
    def warehouse_type_summary(self, *args: Any, **kwargs: Any) -> Any: return self.call("warehouse_type_summary", *args, **kwargs)
    def stock_balance(self, *args: Any, **kwargs: Any) -> Any: return self.call("stock_balance", *args, **kwargs)
    def search_stock_positions(self, *args: Any, **kwargs: Any) -> Any: return self.call("search_stock_positions", *args, **kwargs)
    def position_card(self, *args: Any, **kwargs: Any) -> Any: return self.call("position_card", *args, **kwargs)
