"""Warehouse HTTP routes."""

from __future__ import annotations

import csv
import logging
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..importing import parse_csv_bytes, unknown_csv_headers
from ..service import WarehouseError
from ..warehouse.baseline.posting_policy import WarehousePostingBlocked
from . import reports as reports_routes
from .csv import (
    BALANCE_HEADERS,
    ISSUE_HEADERS,
    ISSUE_IMPORT_HEADERS,
    RECEIPT_EXPORT_HEADERS,
    RECEIPT_HEADERS,
    USER_CSV_TEMPLATES,
    localized as _localized,
)
from .runtime import RouteRuntime


LOGGER = logging.getLogger(__name__)

def handle_get(handler: Any, runtime: RouteRuntime, path: str, query: dict[str, list[str]]):
    """Handle Warehouse reads, exports, and CSV templates."""
    self = handler
    app_context = runtime.app_context
    service = runtime.service
    migration_full_status = runtime.migration_full_status
    migration_pilot_status = runtime.migration_pilot_status
    database_fingerprint = runtime.database_fingerprint
    if path == '/api/data':
        try:
            warehouse_data = app_context.warehouse.get_overview(include_balance=self._query(query, 'include_balance') != '0')
            current_user = self._current_user_payload()
        except Exception:
            LOGGER.exception('Failed to load warehouse overview or current user')
            self._send_json(500, {'error': 'Не удалось загрузить данные интерфейса'})
            return
        LOGGER.info('Warehouse overview loaded user_id=%s history_events=%d', current_user.get('id'), len(warehouse_data.get('warehouse_history', [])))
        self._send_json(200, {**warehouse_data, 'task_sources': list(service.TASK_SOURCES), 'task_types': list(service.TASK_TYPES), 'work_log_statuses': list(service.WORK_LOG_STATUSES), 'daily_report_uploads': app_context.reports.daily_report_uploads(), 'current_user': current_user, 'warehouse_site': {'key': runtime.warehouse_key, 'label': runtime.warehouse_label}, 'runtime': {'database': service.db_path.name, 'database_fingerprint': database_fingerprint, 'working_database': not migration_full_status.get('read_only') and (not migration_pilot_status.get('enabled'))}, 'migration_pilot': migration_pilot_status, 'migration_full': migration_full_status, 'warehouse_system': app_context.warehouse.get_system_status()})
    elif path == '/api/warehouse/system-status':
        self._send_json(200, app_context.warehouse.get_system_status())
    elif path == '/api/full-inventory/session':
        self._send_json(200, app_context.full_inventory.get_session(self._query(query, 'session_id')))
    elif path == '/api/full-inventory/summary':
        self._send_json(200, app_context.full_inventory.preview_summary(self._query(query, 'session_id')))
    elif path == '/api/full-inventory/rows':
        self._send_json(200, app_context.full_inventory.preview_rows(self._query(query, 'session_id'), limit=self._query_int(query, 'limit', default=100, minimum=1, maximum=500), offset=self._query_int(query, 'offset', default=0, minimum=0), status=self._query(query, 'status')))
    elif path == '/api/full-inventory/findings':
        self._send_json(200, app_context.full_inventory.preview_findings(self._query(query, 'session_id'), limit=self._query_int(query, 'limit', default=100, minimum=1, maximum=500), offset=self._query_int(query, 'offset', default=0, minimum=0), severity=self._query(query, 'severity'), blocking=self._query(query, 'blocking')))
    elif path == '/api/full-inventory/resolutions':
        self._send_json(200, app_context.full_inventory.list_resolutions(self._query(query, 'session_id')))
    elif path == '/api/full-inventory/template.xlsx':
        self._send_binary_download('ODE_FULL_INVENTORY_v1.xlsx', app_context.full_inventory.template(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    elif path == '/api/migration-full':
        if not migration_full_status.get('enabled'):
            raise WarehouseError('Full migration review не включён')
        self._send_json(200, app_context.warehouse.list_migration_full_rows(filter_name=self._query(query, 'filter'), query=self._query(query, 'query'), vendor=self._query(query, 'vendor'), model=self._query(query, 'model'), limit=self._query_int(query, 'limit', default=200, minimum=1, maximum=500), offset=self._query_int(query, 'offset', default=0, minimum=0)))
    elif path == '/api/migration-pilot':
        if not migration_pilot_status.get('enabled'):
            raise WarehouseError('Migration pilot review не включён')
        self._send_json(200, app_context.warehouse.list_migration_pilot_rows(filter_name=self._query(query, 'filter'), query=self._query(query, 'query'), limit=self._query_int(query, 'limit', default=200, minimum=1, maximum=300), offset=self._query_int(query, 'offset', default=0, minimum=0)))
    elif path == '/api/delivery':
        self._send_json(200, app_context.warehouse.get_delivery(self._query_int(query, 'id', minimum=1), {'query': self._query(query, 'query'), 'state': self._query(query, 'state'), 'limit': self._query_int(query, 'limit', default=500, minimum=1, maximum=5000), 'offset': self._query_int(query, 'offset', default=0, minimum=0)}))
    elif path == '/api/delivery-selection':
        self._send_json(200, app_context.warehouse.get_delivery_selection(self._query_int(query, 'id', minimum=1)))
    elif path == '/api/deliveries':
        self._send_json(200, {'deliveries': app_context.warehouse.list_deliveries(self._query(query, 'query'))})
    elif path == '/api/warehouse-stock-tree':
        tree_path = {name: self._query(query, name) for name in ('category', 'item_type', 'vendor', 'model')}
        self._send_json(200, app_context.warehouse.get_stock_tree(level=self._query(query, 'level') or 'category', path=tree_path, filters=self._balance_filters(query), limit=self._query_int(query, 'limit', default=100, minimum=1, maximum=200), offset=self._query_int(query, 'offset', default=0, minimum=0, maximum=1000000)))
    elif path == '/api/balance':
        balance_limit = self._query_int(query, 'limit', default=500, minimum=1, maximum=5000)
        balance_offset = self._query_int(query, 'offset', default=0, minimum=0, maximum=1000000)
        balance_rows = app_context.warehouse.get_balance(self._balance_filters(query), limit=balance_limit + 1, offset=balance_offset)
        self._send_json(200, {'rows': balance_rows[:balance_limit], 'limit': balance_limit, 'offset': balance_offset, 'has_previous': balance_offset > 0, 'has_more': len(balance_rows) > balance_limit, 'truncated': len(balance_rows) > balance_limit})
    elif path == '/api/position-search':
        self._send_json(200, {'rows': app_context.warehouse.search_warehouse(self._query(query, 'query'))})
    elif path == '/api/global-search':
        self._send_json(200, {'results': app_context.warehouse.global_search(self._query(query, 'query'), self._query_int(query, 'limit', default=30, minimum=1, maximum=50))})
    elif path == '/api/scan-serial':
        kind = self._query(query, 'kind')
        serial = self._query(query, 'serial_number')
        if kind == 'receipt':
            self._send_json(200, app_context.warehouse.validate_receipt_serial(serial))
        elif kind == 'issue':
            self._send_json(200, app_context.warehouse.validate_issue_serial(serial))
        elif kind == 'issue_target':
            self._send_json(200, app_context.warehouse.validate_issue_target(serial))
        else:
            raise WarehouseError('Неизвестный режим сканирования')
    elif path == '/api/position-card':
        if migration_full_status.get('enabled') and 'full_reconciliation_id' in query:
            self._send_json(200, app_context.warehouse.get_migration_full_card(self._query_int(query, 'full_reconciliation_id', minimum=1)))
        elif migration_pilot_status.get('enabled') and 'pilot_selection_id' in query:
            self._send_json(200, app_context.warehouse.get_migration_pilot_card(self._query_int(query, 'pilot_selection_id', minimum=1)))
        else:
            self._send_json(200, app_context.warehouse.get_position_card({'serial_number': self._query(query, 'serial_number'), 'item_name': self._query(query, 'item_name'), 'cable_type': self._query(query, 'cable_type'), 'project': self._query(query, 'project'), 'datacenter': self._query(query, 'datacenter')}))
    elif path == '/export/stock.csv':
        self._send_csv('equipment_stock.csv', app_context.warehouse.get_inventory_view())
    elif path == '/export/log.csv':
        self._send_csv('operation_log.csv', app_context.warehouse.get_warehouse_history_legacy())
    elif path == '/export/receipt.csv':
        self._send_csv('receipt_operations.csv', _localized(app_context.warehouse.receipts(), RECEIPT_EXPORT_HEADERS), fieldnames=list(RECEIPT_EXPORT_HEADERS.values()))
    elif path == '/export/receipt-current.csv':
        rows = app_context.warehouse.receipt_import_preview_rows(self._query(query, 'preview_id'))
        ode = self._query(query, 'format') == 'ode'
        self._send_csv('receipt_current_ode.csv' if ode else 'receipt_current_excel.csv', _localized(rows, RECEIPT_HEADERS), delimiter=',' if ode else ';')
    elif path == '/export/issue.csv':
        self._send_csv('issue_operations.csv', _localized(app_context.warehouse.issue_rows(), ISSUE_HEADERS), fieldnames=list(ISSUE_HEADERS.values()))
    elif path == '/export/issue-current.csv':
        rows = service.import_preview_rows('issue', self._query(query, 'preview_id'))
        ode = self._query(query, 'format') == 'ode'
        self._send_csv('issue_current_ode.csv' if ode else 'issue_current_excel.csv', _localized(rows, ISSUE_IMPORT_HEADERS), delimiter=',' if ode else ';')
    elif path == '/export/problem-issues.csv':
        rows = app_context.warehouse.get_problem_issues()
        self._send_csv('problem_issues.csv', _localized(rows, {'date': 'Дата', 'serial_number': 'S/N', 'item_name': 'Наименование', 'cable_type': 'Тип кабеля', 'quantity': 'Количество', 'matched_quantity': 'Сопоставлено', 'unmatched_quantity': 'Не сопоставлено', 'responsible': 'ФИО', 'comment': 'Комментарий'}))
    elif path == '/export/balance.csv':
        rows = app_context.warehouse.export_balance_rows(self._balance_filters(query))
        self._send_csv('stock_balance.csv', _localized(rows, BALANCE_HEADERS))
    elif path == '/export/delivery.csv':
        rows = app_context.warehouse.export_delivery_rows(self._query_int(query, 'id', minimum=1))
        self._send_csv('delivery_result.csv', rows)
    elif path == '/import/delivery-template.csv':
        self._send_template('delivery_template.csv', app_context.warehouse.get_delivery_import_template())
    elif path == '/import/equipment-template.csv':
        self._send_template('equipment_import_template.csv', USER_CSV_TEMPLATES['equipment'])
    elif path == '/import/receipt-template.csv':
        self._send_template('receipt_import_template.csv', USER_CSV_TEMPLATES['receipt'])
    elif path == '/import/issue-template.csv':
        self._send_template('issue_import_template.csv', USER_CSV_TEMPLATES['issue'])
    elif path == '/import/bulk-issue-template.csv':
        self._send_template('bulk_issue_template.csv', USER_CSV_TEMPLATES['bulk_issue'])
    elif path == '/import/inventory-template.csv':
        self._send_template('inventory_template.csv', USER_CSV_TEMPLATES['inventory'])
    elif path == '/import/inventory-numbers-template.csv':
        self._send_template('inventory_numbers_template.csv', USER_CSV_TEMPLATES['inventory_numbers'])
    else:
        return False
    return True


def handle_post(handler: Any, runtime: RouteRuntime, parsed: Any):
    """Handle Warehouse POST endpoints outside the compatibility action route."""
    self = handler
    app_context = runtime.app_context
    if parsed.path == '/api/full-inventory/sessions':
        result = app_context.full_inventory.create_session(self._full_inventory_actor(), correlation_id=self._correlation_id())
        self._send_json(201, {'ok': True, 'session': result})
        return
    if parsed.path == '/api/full-inventory/upload':
        query = parse_qs(parsed.query)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError as error:
            raise WarehouseError('Некорректный размер XLSX-запроса') from error
        result = app_context.full_inventory.upload_source(self._query(query, 'session_id'), filename=unquote(self.headers.get('X-Filename', '')), content_type=self.headers.get('Content-Type', ''), content_length=length, stream=self.rfile, actor=self._full_inventory_actor(), correlation_id=self._correlation_id())
        self._send_json(200, {'ok': True, 'session': result})
        return
    if parsed.path in {'/api/full-inventory/preview', '/api/full-inventory/revalidate', '/api/full-inventory/candidate-rehearsal', '/api/full-inventory/reject', '/api/full-inventory/resolutions'}:
        data = self._read_json_object(100000)
        session_id = str(data.get('session_id') or '')
        actor = self._full_inventory_actor()
        if parsed.path.endswith('/preview') or parsed.path.endswith('/revalidate'):
            result = app_context.full_inventory.build_preview(session_id, actor, correlation_id=self._correlation_id())
            self._send_json(200, {'ok': True, **result})
        elif parsed.path.endswith('/candidate-rehearsal'):
            result = app_context.full_inventory.build_candidate_rehearsal(session_id, actor, correlation_id=self._correlation_id())
            self._send_json(201, {'ok': True, **result})
        elif parsed.path.endswith('/resolutions'):
            result = app_context.full_inventory.record_resolution(session_id, actor, action_code=str(data.get('action_code') or ''), reason=str(data.get('reason') or ''), correlation_id=self._correlation_id(), row_id=self._optional_json_int(data, 'row_id'), finding_id=self._optional_json_int(data, 'finding_id'), field_code=str(data.get('field_code') or ''), target_public_id=str(data.get('target_public_id') or ''), replacement_value=str(data.get('replacement_value') or ''), supersedes_resolution_id=self._optional_json_int(data, 'supersedes_resolution_id'))
            self._send_json(201, {'ok': True, **result})
        else:
            result = app_context.full_inventory.reject_session(session_id, actor, correlation_id=self._correlation_id())
            self._send_json(200, {'ok': True, 'session': result})
        return
    return False


def handle_action(handler: Any, runtime: RouteRuntime, action: str, data: dict[str, Any], response: dict[str, Any]):
    """Handle Warehouse mutations routed through the compatibility action URL."""
    self = handler
    app_context = runtime.app_context
    service = runtime.service
    if action in {'RECEIPT', 'ISSUE'}:
        method = service.receipt if action == 'RECEIPT' else service.issue
        method(int(data['equipment_id']), int(data['quantity']), data.get('basis', ''), data.get('responsible', ''))
    elif action == 'MOVE':
        service.move(int(data['equipment_id']), data.get('destination', ''), data.get('basis', ''), data.get('responsible', ''))
    elif action == 'ADD':
        service.add_equipment(data.get('category', ''), data.get('model', ''), data.get('serial_number', ''), data.get('inventory_number', ''), data.get('location_code', ''), int(data.get('quantity', 0)), 'Создание карточки', 'Кладовщик № 1', '', data.get('datacenter', 'Ixcellerate'))
    elif action == 'STOCK_RECEIPT':
        if app_context.warehouse._is_cable_receipt(data):
            app_context.warehouse.create_cable_receipt(data)
        else:
            app_context.warehouse.create_receipt(data)
    elif action == 'ASSIGN_INVENTORY_NUMBER':
        response['position'] = app_context.warehouse.assign_inventory_number(data.get('serial_number', ''), data.get('inventory_number', ''))
    elif action == 'UPDATE_POSITION_CARD':
        response['position'] = app_context.warehouse.update_position_card(data.get('serial_number', ''), data.get('fields', {}))
    elif action == 'FILL_RECEIPT_FIELDS':
        response['fill'] = app_context.warehouse.fill_receipt_fields(self._query_int_value(data.get('receipt_id'), 'receipt_id'), data.get('values', {}))
    elif action == 'FILL_RECEIPT_DATE':
        response['fill'] = app_context.warehouse.fill_receipt_date(self._query_int_value(data.get('receipt_id'), 'receipt_id'), data.get('receipt_date', ''))
    elif action == 'CORRECT_DUPLICATE_SERIAL':
        response['correction'] = app_context.warehouse.correct_duplicate_serial(self._query_int_value(data.get('receipt_id'), 'receipt_id'), data.get('new_serial_number', ''))
    elif action == 'DELETE_DUPLICATE_RECEIPT':
        response['deletion'] = app_context.warehouse.delete_duplicate_receipt(self._query_int_value(data.get('receipt_id'), 'receipt_id'))
    elif action == 'STOCK_ISSUE':
        if app_context.warehouse._is_cable_issue(data):
            app_context.warehouse.create_cable_issue(data)
        else:
            app_context.warehouse.create_issue(data)
    elif action == 'CONFIRM_SCANNED_RECEIPTS':
        response['imported'] = app_context.warehouse.confirm_scanned_receipts(data.get('common_fields', {}), data.get('serial_numbers', []))
    elif action == 'CONFIRM_SCANNED_ISSUES':
        response.update(app_context.warehouse.create_issue_by_serials(data.get('common_fields', {}), data.get('serial_numbers', [])))
    elif action == 'CONFIRM_SCANNED_ISSUE_PAIRS':
        response.update(app_context.warehouse.create_issue_pairs(data.get('common_fields', {}), data.get('pairs', [])))
    elif action == 'CONFIRM_IMPORT_PREVIEW':
        kind = data.get('kind', '')
        if kind == 'receipt':
            response['imported'] = app_context.warehouse.confirm_receipt_import(data.get('preview_id', ''))
        elif kind == 'issue':
            response['imported'] = app_context.warehouse.confirm_issue_import(data.get('preview_id', ''))
        elif kind == 'inventory_numbers':
            response.update(app_context.warehouse.confirm_inventory_number_import(data.get('preview_id', '')))
        else:
            raise WarehouseError('Неизвестный тип подтверждения')
    elif action == 'CONFIRM_BULK_ISSUE':
        response['imported'] = app_context.warehouse.confirm_bulk_issue_preview(data.get('preview_id', ''), data.get('issue_date', ''), data.get('responsible', ''), data.get('task_type', ''), data.get('task_number', ''), data.get('comment', ''), data.get('target_serial_number', ''))
    elif action == 'CONFIRM_DELIVERY':
        response['delivery_id'] = app_context.warehouse.confirm_delivery_import(data.get('preview_id', ''), {'session': self._session_token()})
    elif action == 'UPDATE_DELIVERY_LINES':
        response['changed'] = app_context.warehouse.update_delivery_line_metadata(int(data.get('delivery_id', 0)), data.get('line_ids', []), data.get('values', {}), only_empty=self._json_boolean(data.get('only_empty', False), 'only_empty'))
    elif action == 'INSPECT_DELIVERY_SERIAL':
        response.update(app_context.warehouse.inspect_delivery_serial(int(data.get('delivery_id', 0)), data.get('serial_number', '')))
    elif action == 'ACCEPT_DELIVERY_SERIAL':
        if self._json_boolean(data.get('unplanned', False), 'unplanned'):
            response.update(app_context.warehouse.accept_unplanned_delivery_serial(int(data.get('delivery_id', 0)), data.get('serial_number', ''), data.get('values', {})))
        else:
            response.update(app_context.warehouse.accept_delivery_serial(int(data.get('delivery_id', 0)), data.get('serial_number', ''), data.get('values', {})))
    elif action == 'ACCEPT_DELIVERY_BATCH':
        response.update(app_context.warehouse.accept_delivery_batch(int(data.get('delivery_id', 0)), data.get('line_ids', []), data.get('common_values', {})))
    elif action == 'DELIVERY_ACCEPTANCE_SUMMARY':
        response['summary'] = app_context.warehouse.get_delivery_acceptance_summary(int(data.get('delivery_id', 0)))
    elif action == 'DELIVERY_CONFLICTS':
        response['conflicts'] = app_context.warehouse.get_delivery_conflicts(int(data.get('delivery_id', 0)))
    elif action == 'CLOSE_DELIVERY':
        service.close_delivery(int(data.get('delivery_id', 0)))
    elif action == 'ADD_REFERENCE':
        service.add_reference(data.get('kind', ''), data.get('name', ''))
    elif action == 'TOGGLE_REFERENCE':
        app_context.warehouse.set_reference_active(int(data.get('reference_id', 0)), self._json_boolean(data.get('is_active', False), 'is_active'))
    elif action == 'PROPOSE_REFERENCE':
        response['reference_id'] = app_context.warehouse.propose_reference(data.get('domain', ''), data.get('value', ''), data.get('parent', ''))
    elif action == 'REFERENCE_RENAME':
        app_context.warehouse.rename_reference(int(data.get('reference_id', 0)), data.get('display_name', ''))
    elif action == 'REFERENCE_MERGE_PREVIEW':
        response['preview'] = app_context.warehouse.preview_reference_merge(int(data.get('source_id', 0)), int(data.get('target_id', 0)))
    elif action == 'REFERENCE_MERGE':
        response['result'] = app_context.warehouse.merge_reference(int(data.get('source_id', 0)), int(data.get('target_id', 0)))
    else:
        return False
    return True


def import_csv(handler: Any, runtime: RouteRuntime, *, kind: str, preview: bool=False):
    """Parse and dispatch CSV imports while preserving the legacy HTTP contract."""
    self = handler
    app_context = runtime.app_context
    service = runtime.service
    route_runtime = runtime
    try:
        if kind not in {'equipment', 'receipt', 'issue', 'bulk_issue', 'work_logs', 'daily_report', 'inventory', 'inventory_numbers', 'delivery'}:
            raise WarehouseError('Неизвестный тип CSV-импорта')
        length = int(self.headers.get('Content-Length', '0'))
        if length <= 0:
            raise WarehouseError('Выберите непустой CSV-файл')
        if length > 50000000:
            raise WarehouseError('CSV-файл превышает допустимый размер 50 МБ')
        body = self.rfile.read(length)
        rows = parse_csv_bytes(body, kind)
        soft = self._query(parse_qs(urlparse(self.path).query), 'mode') != 'strict'
        if reports_routes.handle_csv_import(self, route_runtime, kind=kind, rows=rows, preview=preview, soft=soft):
            return
        if not preview and kind in {'equipment', 'receipt', 'issue', 'bulk_issue'}:
            app_context.warehouse.assert_posting_allowed(f'import_csv:{kind}')
        if kind == 'delivery':
            result = app_context.warehouse.preview_delivery_import(rows, unquote(self.headers.get('X-Filename', 'delivery.csv')), {'session': self._session_token()}, unknown_columns=unknown_csv_headers(body))
            self._send_json(200, {'ok': True, **result})
            return
        if kind == 'inventory':
            self._send_json(200, {'ok': True, **service.inventory_compare(rows)})
            return
        if kind == 'inventory_numbers':
            if not preview:
                raise WarehouseError('Назначение Inventory Number требует предпросмотра и подтверждения')
            result = app_context.warehouse.preview_inventory_number_import(rows, unquote(self.headers.get('X-Filename', 'inventory_numbers.csv')))
            self._send_json(200, {'ok': True, **result})
            return
        if kind == 'bulk_issue':
            result = app_context.warehouse.preview_bulk_issue_serials(rows, unquote(self.headers.get('X-Filename', 'bulk_issue.csv')))
            self._send_json(200, {'ok': True, **result})
            return
        if kind == 'equipment':
            imported = service.import_equipment_rows(rows)
        elif kind == 'receipt':
            for row in rows:
                row['receipt_date'] = row.pop('work_date', row.get('receipt_date', ''))
            if preview:
                result = app_context.warehouse.preview_receipt_import(rows, unquote(self.headers.get('X-Filename', 'receipt.csv')), unknown_columns=unknown_csv_headers(body), soft=soft)
                self._send_json(200, {'ok': True, **result})
                return
            imported = app_context.warehouse.import_receipts(rows, soft=soft)
        else:
            for row in rows:
                row['issue_date'] = row.pop('work_date', row.get('issue_date', ''))
                row['source_serial_number'] = row.get('source_serial_number', row.pop('serial_number', ''))
                row['source_item_name'] = row.get('source_item_name', row.pop('item_name', ''))
                row['source_cable_type'] = row.get('source_cable_type', row.pop('cable_type', ''))
            if preview:
                result = app_context.warehouse.preview_issue_import(rows, unquote(self.headers.get('X-Filename', 'issue.csv')), unknown_columns=unknown_csv_headers(body), soft=soft)
                self._send_json(200, {'ok': True, **result})
                return
            imported = app_context.warehouse.import_issues(rows, soft=soft)
        response = {'ok': True, 'imported': imported}
        self._send_json(200, response)
    except WarehousePostingBlocked as error:
        self._send_json(409, {'error': str(error), 'code': error.code})
    except (WarehouseError, ValueError, csv.Error, UnicodeError) as error:
        self._send_json(400, {'error': str(error)})
    except Exception:
        self._send_json(500, {'error': 'Внутренняя ошибка сервера'})
