"""Extracted Warehouse domain service."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from inventory.db import connect
from inventory.shared.validators import WarehouseError

from .classification import (
    canonical_vendor,
    classify_card,
    infer_vendor,
    operational_category,
)
from .component import WarehouseComponent
from .issue_repository import IssueRepository


class WarehouseMonitoringService(WarehouseComponent):
    def data_quality_problems(
        self, date_from: str = "", date_to: str = "", limit: int | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Return warehouse inconsistencies without preventing normal balance reads."""
        start, end = self._validated_period(date_from, date_to, optional=True)
        issue_where = ""
        params: list[Any] = []
        if start:
            issue_where += " AND i.issue_date >= ?"
            params.append(start)
        if end:
            issue_where += " AND i.issue_date <= ?"
            params.append(end)
        limit_sql = ""
        if limit is not None:
            limit = max(1, min(int(limit), 5_000))
            limit_sql = " LIMIT ?"
        with connect(self.db_path) as db:
            unmatched = [dict(row) for row in db.execute(
                f"""SELECT i.id, i.issue_date AS date, i.source_serial_number AS serial_number,
                           i.source_item_name AS item_name, i.source_cable_type AS cable_type,
                           i.quantity, COALESCE(SUM(a.quantity), 0) AS matched_quantity,
                           i.quantity - COALESCE(SUM(a.quantity), 0) AS unmatched_quantity,
                           i.responsible, i.comment
                      FROM stock_issues i
                      LEFT JOIN stock_issue_allocations a ON a.issue_id = i.id
                     WHERE 1=1 {issue_where}
                     GROUP BY i.id
                    HAVING unmatched_quantity > 0.0000001
                     ORDER BY i.issue_date, i.id{limit_sql}""",
                [*params, *([limit] if limit is not None else [])],
            )]
            duplicates = [dict(row) for row in db.execute(
                f"""SELECT serial_number, COUNT(*) AS count
                     FROM stock_receipts WHERE trim(serial_number) <> ''
                     GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                     {limit_sql}""",
                ([limit] if limit is not None else []),
            )]
            negative = [dict(row) for row in db.execute(
                f"""SELECT r.serial_number, r.item_name,
                           SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                    FROM stock_receipts r
                    LEFT JOIN (
                        SELECT receipt_id, SUM(quantity) AS issued
                        FROM stock_issue_allocations GROUP BY receipt_id
                    ) a ON a.receipt_id = r.id
                    GROUP BY r.project, r.item_name, r.vendor, r.model, r.serial_number,
                             r.inventory_number, r.unit, r.object_name, r.equipment_type,
                             r.component_type, r.cable_type, r.datacenter
                    HAVING balance < -0.0000001{limit_sql}""",
                ([limit] if limit is not None else []),
            )]
            receipt_where = ""
            receipt_params: list[Any] = []
            if start:
                receipt_where += " AND receipt_date >= ?"
                receipt_params.append(start)
            if end:
                receipt_where += " AND receipt_date <= ?"
                receipt_params.append(end)
            incomplete = [dict(row) for row in db.execute(
                f"""SELECT id, receipt_date AS date, item_name, serial_number,
                            inventory_number, project, shelf, vendor, model, quantity
                       FROM stock_receipts
                      WHERE (trim(project) = '' OR trim(shelf) = '' OR trim(vendor) = ''
                             OR trim(model) = '') {receipt_where}
                      ORDER BY receipt_date, id{limit_sql}""",
                [*receipt_params, *([limit] if limit is not None else [])],
            )]
        return {
            "unmatched_issues": unmatched, "duplicate_serials": duplicates,
            "negative_balances": negative, "incomplete_rows": incomplete,
        }

    def data_quality_problem_counts(self) -> dict[str, int]:
        """Count problem groups without materializing every problematic row."""
        with connect(self.db_path) as db:
            row = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) issued
                       FROM stock_issue_allocations GROUP BY receipt_id
                   ), grouped_balance AS (
                       SELECT SUM(r.quantity - COALESCE(a.issued, 0)) balance
                       FROM stock_receipts r LEFT JOIN allocations a ON a.receipt_id = r.id
                       GROUP BY r.project, r.item_name, r.vendor, r.model, r.serial_number,
                                r.inventory_number, r.unit, r.object_name, r.equipment_type,
                                r.component_type, r.cable_type, r.datacenter
                   ), issue_allocations AS (
                       SELECT issue_id, SUM(quantity) matched
                       FROM stock_issue_allocations GROUP BY issue_id
                   )
                   SELECT
                     (SELECT COUNT(*) FROM stock_issues i
                       LEFT JOIN issue_allocations a ON a.issue_id = i.id
                       WHERE i.quantity - COALESCE(a.matched, 0) > 0.0000001) unmatched_issues,
                     (SELECT COUNT(*) FROM (
                       SELECT 1 FROM stock_receipts WHERE trim(serial_number) <> ''
                       GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                     )) duplicate_serials,
                     (SELECT COUNT(*) FROM grouped_balance WHERE balance < -0.0000001) negative_balances,
                     (SELECT COUNT(*) FROM stock_receipts
                       WHERE trim(shelf) = '' OR trim(vendor) = ''
                          OR trim(model) = '') incomplete_rows"""
            ).fetchone()
        return {key: int(row[key]) for key in (
            "unmatched_issues", "duplicate_serials", "negative_balances", "incomplete_rows"
        )}

    def data_quality_summary(self, limit: int = 200) -> dict[str, Any]:
        """Return bounded problem examples and exact counts in the same SQL passes."""
        limit = max(1, min(int(limit), 5_000))

        def rows_and_count(rows: list[sqlite3.Row]) -> tuple[list[dict[str, Any]], int]:
            count = int(rows[0]["_total_count"]) if rows else 0
            result: list[dict[str, Any]] = []
            for source in rows:
                item = dict(source)
                item.pop("_total_count", None)
                result.append(item)
            return result, count

        with connect(self.db_path) as db:
            unmatched_rows = db.execute(
                """WITH problems AS (
                       SELECT i.id, i.issue_date AS date,
                              i.source_serial_number AS serial_number,
                              i.source_item_name AS item_name,
                              i.source_cable_type AS cable_type, i.quantity,
                              COALESCE(SUM(a.quantity), 0) AS matched_quantity,
                              i.quantity - COALESCE(SUM(a.quantity), 0) AS unmatched_quantity,
                              i.responsible, i.comment
                         FROM stock_issues i
                         LEFT JOIN stock_issue_allocations a ON a.issue_id = i.id
                        GROUP BY i.id
                       HAVING unmatched_quantity > 0.0000001
                   )
                   SELECT problems.*, COUNT(*) OVER() AS _total_count
                     FROM problems ORDER BY date, id LIMIT ?""",
                (limit,),
            ).fetchall()
            duplicate_rows = db.execute(
                """WITH dup AS (
                       SELECT serial_number
                         FROM stock_receipts WHERE trim(serial_number) <> ''
                        GROUP BY serial_number COLLATE NOCASE HAVING COUNT(*) > 1
                   ), problems AS (
                       SELECT r.id, r.receipt_date AS date, r.item_name,
                              r.serial_number, r.inventory_number, r.vendor,
                              r.model, r.quantity
                         FROM stock_receipts r
                         JOIN dup ON r.serial_number = dup.serial_number COLLATE NOCASE
                   )
                   SELECT problems.*, (SELECT COUNT(*) FROM dup) AS _total_count
                     FROM problems
                    ORDER BY serial_number COLLATE NOCASE, id LIMIT ?""",
                (limit,),
            ).fetchall()
            negative_rows = db.execute(
                """WITH allocations AS (
                       SELECT receipt_id, SUM(quantity) AS issued
                         FROM stock_issue_allocations GROUP BY receipt_id
                   ), problems AS (
                       SELECT r.serial_number, r.item_name,
                              SUM(r.quantity - COALESCE(a.issued, 0)) AS balance
                         FROM stock_receipts r
                         LEFT JOIN allocations a ON a.receipt_id = r.id
                        GROUP BY r.project, r.item_name, r.vendor, r.model,
                                 r.serial_number, r.inventory_number, r.unit,
                                 r.object_name, r.equipment_type, r.component_type,
                                 r.cable_type, r.datacenter
                       HAVING balance < -0.0000001
                   )
                   SELECT problems.*, COUNT(*) OVER() AS _total_count
                     FROM problems LIMIT ?""",
                (limit,),
            ).fetchall()
            incomplete_rows = db.execute(
                """SELECT id, receipt_date AS date, item_name, serial_number,
                          inventory_number, project, shelf, vendor, model, quantity,
                          COUNT(*) OVER() AS _total_count
                     FROM stock_receipts
                    WHERE trim(shelf) = '' OR trim(vendor) = ''
                       OR trim(model) = ''
                    ORDER BY receipt_date, id LIMIT ?""",
                (limit,),
            ).fetchall()
        groups = {
            "unmatched_issues": rows_and_count(unmatched_rows),
            "duplicate_serials": rows_and_count(duplicate_rows),
            "negative_balances": rows_and_count(negative_rows),
            "incomplete_rows": rows_and_count(incomplete_rows),
        }
        return {
            "problems": {key: value[0] for key, value in groups.items()},
            "counts": {key: value[1] for key, value in groups.items()},
        }

    def _validated_period(
        self, date_from: str, date_to: str, optional: bool = False
    ) -> tuple[str, str]:
        if optional and not date_from and not date_to:
            return "", ""
        start = self._date(date_from, "дата начала") if date_from else ""
        end = self._date(date_to, "дата окончания") if date_to else ""
        if not optional and (not start or not end):
            raise WarehouseError("Укажите дату начала и дату окончания")
        if start and end and start > end:
            raise WarehouseError("Дата начала не может быть позже даты окончания")
        return start, end
