"""Receipt workflow service."""

from __future__ import annotations

from typing import Any

from ._base import ServiceAdapter


class ReceiptService(ServiceAdapter):
    def preview_stock_receipt_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("preview_stock_receipt_rows", *args, **kwargs)
    def confirm_stock_receipt_preview(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_stock_receipt_preview", *args, **kwargs)
    def scan_receipt_serial(self, *args: Any, **kwargs: Any) -> Any: return self.call("scan_receipt_serial", *args, **kwargs)
    def confirm_scanned_receipts(self, *args: Any, **kwargs: Any) -> Any: return self.call("confirm_scanned_receipts", *args, **kwargs)
    def add_stock_receipt(self, *args: Any, **kwargs: Any) -> Any: return self.call("add_stock_receipt", *args, **kwargs)
    def import_stock_receipt_rows(self, *args: Any, **kwargs: Any) -> Any: return self.call("import_stock_receipt_rows", *args, **kwargs)
    def stock_receipts(self, *args: Any, **kwargs: Any) -> Any: return self.call("stock_receipts", *args, **kwargs)
    def receipt(self, *args: Any, **kwargs: Any) -> Any: return self.call("receipt", *args, **kwargs)
