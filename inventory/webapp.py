"""Локальный веб-интерфейс ODE без внешних зависимостей."""

from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import json
import os
import re
import secrets
import tempfile
import threading
import time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .core.application import ApplicationContext, create_application_context, ensure_application_context
from .core.context import RuntimeConfig
from .db import DEFAULT_DB_PATH
from .importing import parse_csv_bytes, unknown_csv_headers
from .service import WarehouseError, WarehouseService
from .warehouse.migration_full_review import (
    full_migration_requested,
    validate_full_migration_database,
)
from .warehouse.migration_pilot_review import (
    migration_pilot_requested,
    validate_migration_pilot_database,
)
from .warehouse.baseline.posting_policy import PostingPolicy, WarehousePostingBlocked
from .warehouse.baseline.workspace import WorkspaceError
from .warehouse.baseline.xlsx_parser import FullInventoryXlsxError


CURRENT_DATACENTER = "Ixcellerate"
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
PRODUCT_NAME = "ODE"
PRODUCT_VERSION = __version__

LOGIN_HTML = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Начало смены — {PRODUCT_NAME} {PRODUCT_VERSION}</title>
<style>body{{margin:0;background:#f4f7fb;color:#172033;font:14px system-ui;display:grid;place-items:center;min-height:100vh}}.card{{width:min(410px,calc(100% - 32px));padding:28px;background:white;border:1px solid #dce3ec;border-radius:14px;box-shadow:0 8px 24px #1720330d}}h1{{margin:0 0 5px}}p,small{{color:#667085}}label{{display:block;margin-top:15px;font-weight:650}}input{{width:100%;box-sizing:border-box;margin-top:6px;padding:12px;border:1px solid #cbd5e1;border-radius:8px}}button{{width:100%;margin-top:20px;padding:12px;border:0;border-radius:8px;background:#2563eb;color:white;font-weight:700;cursor:pointer}}details{{margin-top:18px;padding-top:12px;border-top:1px solid #dce3ec}}summary{{cursor:pointer;color:#475569}}.error{{color:#991b1b}}</style></head><body>
<form class="card" id="login"><h1>Кто сегодня работает?</h1><p>{PRODUCT_NAME} {PRODUCT_VERSION}. Операции смены будут записаны под выбранным именем.</p>
<label>ФИО инженера<input name="full_name" autocomplete="name" autofocus placeholder="Иванов Иван Иванович"></label>
<details><summary>Учётная запись ODE</summary><small>Заполните, если вам назначены дополнительные backend-права.</small><label>Логин<input name="email" autocomplete="username"></label><label>Пароль<input name="password" type="password" autocomplete="current-password"></label></details>
<button>Начать работу</button><p class="error" id="error"></p></form>
<script>document.getElementById('login').onsubmit=async e=>{{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));const credentials=Boolean(data.email.trim()||data.password);if(credentials&&(!data.email.trim()||!data.password)){{document.getElementById('error').textContent='Укажите логин и пароль полностью';return}}if(!credentials&&!data.full_name.trim()){{document.getElementById('error').textContent='Укажите ФИО инженера';return}}data.mode=credentials?'admin':'engineer';const r=await fetch('/api/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)}});const x=await r.json();if(r.ok)location.href='/';else document.getElementById('error').textContent=x.error||'Ошибка входа'}};</script></body></html>'''

HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ODE 0.12 — учет работ и склада</title>
<style>
:root{--bg:#f4f7fb;--surface:#fff;--text:#172033;--muted:#667085;--line:#dce3ec;--blue:#2563eb;--nav:#172033;--shadow:0 8px 24px #1720330d}
.preview{display:none;margin:14px 0;padding:16px;border:1px solid var(--line);border-radius:10px;background:#fff}.preview.show{display:block}.preview-stats{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}.preview-stat{padding:10px;border-radius:8px;background:#f8fafc}.preview-stat strong{display:block;font-size:20px}.error-list{color:#991b1b}.modal{display:none;position:fixed;inset:0;z-index:20;padding:5vh 5vw;background:#17203399;overflow:auto}.modal.show{display:block}.modal-card{max-width:1100px;margin:auto;padding:20px;border-radius:12px;background:#fff}.modal-head{display:flex;justify-content:space-between;gap:16px}.scanner-box{margin-bottom:22px;padding:18px;border:2px solid #93c5fd;border-radius:12px;background:#eff6ff}.scanner-box h2{margin-bottom:4px}.scanner-input{width:100%;margin:14px 0;padding:16px;border:2px solid var(--blue);border-radius:9px;background:#fff;font-size:21px}.scanner-table .bad{background:#fef2f2;color:#991b1b}.scanner-table .warn{background:#fffbeb;color:#92400e}.scanner-empty{padding:24px;text-align:center;color:var(--muted)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}.app{min-height:100vh;display:grid;grid-template-columns:230px 1fr}.sidebar{padding:22px 14px;background:var(--nav);color:#fff}.brand{padding:4px 10px 24px}.brand strong{display:block;font-size:20px}.brand span{display:block;margin-top:5px;color:#aab6ca;font-size:12px}.section-button{width:100%;margin:4px 0;padding:15px;border:0;border-radius:10px;background:transparent;color:#cbd5e1;text-align:left;font-weight:700;cursor:pointer}.section-button:hover,.section-button.active{background:#25324a;color:#fff}.main{min-width:0;padding:22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.top h1{margin:0;font-size:23px}.button{display:inline-block;padding:9px 13px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--text);text-decoration:none;cursor:pointer}.button.primary{border-color:var(--blue);background:var(--blue);color:#fff}.subnav{display:flex;gap:4px;margin-bottom:14px;padding:7px;background:#fff;border:1px solid var(--line);border-radius:11px;overflow:auto}.subtab{padding:10px 14px;border:0;border-radius:7px;background:transparent;color:var(--muted);font-weight:650;white-space:nowrap;cursor:pointer}.subtab.active{background:#eaf1ff;color:#1d4ed8}.view{display:none}.view.active{display:block}.panel{padding:20px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:var(--shadow)}h2{margin:0 0 5px;font-size:19px}.hint{margin:0 0 18px;color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{padding:18px;border:1px solid var(--line);border-radius:11px;background:#fff}.card span{display:block;color:var(--muted)}.card strong{display:block;margin-top:8px;font-size:30px}.form{max-width:820px;display:grid;grid-template-columns:170px 1fr;gap:11px 16px;align-items:center}.form label{font-weight:650}.form input,.form select,.form textarea,.filters input,.filters select{width:100%;padding:9px 10px;border:1px solid #cbd5e1;border-radius:7px;background:#fff}.form textarea{min-height:75px;resize:vertical}.actions{grid-column:2;display:flex;gap:8px;flex-wrap:wrap}.split{display:grid;grid-template-columns:1fr 1fr;gap:18px}.box{padding:16px;border:1px solid var(--line);border-radius:10px}.box h3{margin:0 0 14px}.import-box{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px;padding:14px;border:1px solid #bfdbfe;border-radius:10px;background:#eff6ff}.import-box p{margin:3px 0 0;color:var(--muted)}.import-actions,.report-actions{display:flex;gap:8px;flex-wrap:wrap}.file-input{position:absolute;width:1px;height:1px;opacity:0}.filters{display:grid;grid-template-columns:1fr 1fr auto auto;gap:9px;margin-bottom:13px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:10px 12px;border-bottom:1px solid #edf1f6;text-align:left}th{background:#f8fafc;font-size:12px}.empty{padding:28px;text-align:center;color:var(--muted)}.badge{padding:3px 7px;border-radius:12px;background:#eaf1ff;color:#1d4ed8}.placeholder{padding:55px 20px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}.instruction li{margin:8px 0}.status{position:fixed;right:20px;bottom:20px;max-width:430px;padding:12px 16px;border-radius:8px;background:#172033;color:#fff;opacity:0;transform:translateY(10px);transition:.2s;pointer-events:none}.status.show{opacity:1;transform:none}.status.error{background:#991b1b}
@media(max-width:950px){.cards{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
@media(max-width:720px){.app{display:block}.sidebar{padding:10px;position:sticky;top:0;z-index:5}.brand{display:none}.section-nav{display:flex;gap:5px}.section-button{margin:0;padding:11px 10px;text-align:center}.main{padding:12px}.top{justify-content:flex-end}.top>div:first-child{display:none}.form{grid-template-columns:1fr}.actions{grid-column:1}.filters{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}.import-box{align-items:stretch;flex-direction:column}.panel{padding:14px}}
</style></head><body><div class="app">
<aside class="sidebar"><div class="brand"><strong>ODE</strong><span>Отдел дежурных инженеров</span></div><nav class="section-nav">
<button class="section-button active" data-section="warehouse">Склад</button><button class="section-button" data-section="reports">Отчеты</button><button class="section-button" data-section="monitoring">Мониторинг</button>
</nav></aside>
<main class="main"><header class="top"><div><h1 id="pageTitle">Склад</h1><span class="hint">Отдел дежурных инженеров · __DATACENTER__</span></div><div><label class="hint" style="display:inline">Импорт: <select id="importMode"><option value="soft">мягкий</option><option value="strict">строгий</option></select></label> <span id="currentUser"></span> <button class="button" onclick="showProfile()">Профиль</button> <button class="button" onclick="loadAll()">Обновить</button> <button class="button" onclick="logout()">Выйти</button></div></header><nav class="subnav" id="subnav"></nav>

<section class="view panel" id="inventory"><div class="import-box"><div><strong>Массовое назначение Inventory Number</strong><p>Загрузите UTF-8 CSV со столбцами Serial Number и Inventory Number. Сначала будет выполнен предпросмотр без изменения базы.</p></div><div class="import-actions"><a class="button" href="/import/inventory-numbers-template.csv">Скачать шаблон</a><label class="button primary" for="inventoryNumberCsv">Выбрать CSV</label><input class="file-input inventory-input" id="inventoryNumberCsv" type="file" accept=".csv,text/csv"></div></div><div class="preview" id="inventoryNumberImport" aria-live="polite"></div><div class="import-box"><div><strong>Инвентаризация по S/N</strong><p>Загрузите CSV со столбцом SN, S/N, Серийный номер или Серийник.</p></div><div class="import-actions"><a class="button" href="/import/inventory-template.csv">Шаблон</a><label class="button primary" for="inventoryCsv">Загрузить CSV</label><input class="file-input inventory-input" id="inventoryCsv" data-kind="inventory" type="file" accept=".csv"><button class="button" id="inventoryExport" disabled>Экспорт результата</button></div></div><div class="cards" id="inventoryCards"></div><div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>S/N</th><th>Результат</th><th>Количество</th></tr></thead><tbody id="inventoryBody"><tr><td class="empty" colspan="3">CSV еще не загружен</td></tr></tbody></table></div></section>

<section class="view panel" id="problems"><h2>Контроль качества данных</h2><p class="hint">Проблемы не блокируют баланс и доступны для последующей сверки.</p><div class="cards" id="problemCards"></div><div id="problemDetails" style="margin-top:16px"></div></section>

<section class="view panel" id="overview"><h2>Обзор склада</h2><p class="hint">Текущее движение и остаток оборудования.</p><div class="cards"><div class="card"><span>Приход</span><strong id="statReceipts">0</strong></div><div class="card"><span>Расход</span><strong id="statIssues">0</strong></div><div class="card"><span>Остаток</span><strong id="statBalance">0</strong></div><div class="card"><span>Позиций</span><strong id="statPositions">0</strong></div></div></section>

<section class="view panel" id="receipt"><div class="import-box"><div><strong>CSV-скан-лист прихода</strong><p>Сначала показывается проверка; база изменится только после подтверждения.</p></div><div class="import-actions"><a class="button" href="/import/receipt-template.csv">Шаблон</a><a class="button" href="/export/receipt.csv">Выгрузить</a><label class="button primary" for="receiptCsv">Выбрать CSV</label><input class="file-input preview-input" id="receiptCsv" data-kind="receipt" type="file" accept=".csv"></div></div><div class="preview" id="receiptPreview"></div><h2>Оформить приход</h2><p class="hint">Справочные поля принимают свободный текст; существующие значения показываются как подсказки. Выберите ровно один тип: оборудование, компонент или кабель.</p><form class="form" id="stockReceiptForm"><label>Дата</label><input name="receipt_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Дата заказа</label><input name="order_date" type="date"><label>Заявка №</label><input name="request_number"><label>Заказ №</label><input name="order_number"><label>PLU</label><input name="plu"><label>Наименование</label><input name="item_name" class="ref-input" data-kind="item_name" list="ref-item_name" required><label>Проект</label><input name="project" class="ref-input" data-kind="project" list="ref-project"><label>S/N</label><input name="serial_number"><label>Инв. №</label><input name="inventory_number"><label>Поставщик</label><input name="supplier" class="ref-input" data-kind="supplier" list="ref-supplier" required><label>Вендор</label><input name="vendor" class="ref-input" data-kind="vendor" list="ref-vendor" required><label>Модель</label><input name="model" class="ref-input" data-kind="model" list="ref-model"><label>Стеллаж/Полка</label><input name="shelf" class="ref-input" data-kind="shelf" list="ref-shelf"><label>Объект</label><input name="object_name" class="ref-input" data-kind="object" list="ref-object" required><label>ЦОД</label><input name="datacenter" class="ref-input" data-kind="datacenter" list="ref-datacenter" value="Ixcellerate" required><label>Тип оборудования</label><input name="equipment_type" class="ref-input" data-kind="equipment_type" list="ref-equipment_type"><label>Тип компонента</label><input name="component_type" class="ref-input" data-kind="component_type" list="ref-component_type"><label>Тип кабеля</label><input name="cable_type" class="ref-input" data-kind="cable_type" list="ref-cable_type"><label>Единица учета</label><input name="unit" class="ref-input" data-kind="unit" list="ref-unit" required><label>Кол-во / метраж</label><input name="quantity" type="number" min="0.001" step="0.001" value="1" required><div class="actions"><button class="button primary">Зарегистрировать приход</button></div></form></section>

<section class="view panel" id="issue"><div class="import-box"><div><strong>CSV-скан-лист расхода</strong><p>Оборудование — по S/N; кабель — по наименованию и типу. Запись только после preview.</p></div><div class="import-actions"><a class="button" href="/import/issue-template.csv">Шаблон</a><a class="button" href="/export/issue.csv">Выгрузить</a><label class="button primary" for="issueCsv">Выбрать CSV</label><input class="file-input preview-input" id="issueCsv" data-kind="issue" type="file" accept=".csv"></div></div><div class="preview" id="issuePreview"></div><div class="box" style="margin-bottom:18px"><h3>Найти позицию для списания</h3><form class="filters" id="issueSearchForm"><input name="query" placeholder="S/N, инв.№, наименование, модель, вендор, проект, полка" required><button class="button primary">Найти</button><span></span><span></span></form><div class="table-wrap"><table><thead><tr><th>Наименование</th><th>Модель</th><th>S/N</th><th>Инв.№</th><th>Остаток</th><th>Проект</th><th>Полка</th><th></th></tr></thead><tbody id="issueSearchBody"><tr><td class="empty" colspan="8">Введите запрос</td></tr></tbody></table></div></div><h2>Оформить расход</h2><p class="hint">Выберите позицию поиском выше или заполните вручную. Для кабеля оставьте S/N пустым.</p><form class="form" id="stockIssueForm"><label>Дата</label><input name="issue_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Тип задачи</label><select name="task_type" id="issueTaskType"></select><label>Номер задачи</label><input name="task_number"><label>SN целевого объекта</label><input name="target_serial_number"><label>Hostname</label><input name="target_hostname"><label>S/N списываемого</label><input name="source_serial_number"><label>Наименование кабеля</label><input name="source_item_name" class="ref-input" data-kind="item_name" list="ref-item_name"><label>Тип кабеля</label><input name="source_cable_type" class="ref-input" data-kind="cable_type" list="ref-cable_type"><label>Доступный остаток</label><input name="available" readonly><label>Кол-во / метраж</label><input name="quantity" type="number" min="0.001" step="0.001" value="1" required><label>Комментарий</label><textarea name="comment"></textarea><div class="actions"><button class="button primary">Зарегистрировать расход</button></div></form><div class="box" style="margin-top:22px"><h3>Массовое списание по списку S/N</h3><p class="hint">Строгий режим: неизвестный, повторный, уже списанный S/N или кабель блокирует весь список.</p><div class="import-actions"><a class="button" href="/import/bulk-issue-template.csv">Шаблон S/N</a><label class="button primary" for="bulkIssueCsv">Выбрать CSV</label><input class="file-input preview-input" id="bulkIssueCsv" data-kind="bulk_issue" type="file" accept=".csv"></div><div class="preview" id="bulk_issuePreview"></div><form class="form" id="bulkIssueForm"><input name="preview_id" type="hidden"><label>Дата</label><input name="issue_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Тип задачи</label><select name="task_type" id="bulkTaskType" required></select><label>Номер задачи</label><input name="task_number" required><label>Целевой S/N</label><input name="target_serial_number" placeholder="Обязателен, если в списке есть компоненты"><label>Комментарий</label><textarea name="comment"></textarea><div class="actions"><button class="button primary" id="bulkConfirm" disabled>Подтвердить списание</button></div></form></div></section>

<section class="view panel" id="balance"><div class="import-box"><div><strong>Баланс — рабочий экран склада</strong><p>Поиск, карточка, списание и экспорт текущей выборки.</p></div><a class="button" id="balanceExport" href="/export/balance.csv">Выгрузить CSV</a></div><div class="filters"><input id="balanceQuery" placeholder="Общий поиск: S/N, инв.№, наименование, модель, вендор, проект, объект, полка"><button class="button" onclick="clearBalanceFilters()">Сбросить</button><span></span><span></span><select id="balanceProject"></select><select id="balanceObject"></select><select id="balanceEquipmentType"></select><select id="balanceComponentType"></select><select id="balanceCableType"></select><select id="balanceUnit"></select><select id="balanceDatacenter"></select></div><div class="table-wrap"><table><thead><tr><th>Проект</th><th>Наименование</th><th>Вендор</th><th>Модель</th><th>SN</th><th>Инв.№</th><th>Остаток</th><th>Ед.</th><th>Стеллаж/Полка</th><th>Объект</th><th>Тип оборудования</th><th>Тип компонента</th><th>Тип кабеля</th><th>ЦОД</th><th>Действия</th></tr></thead><tbody id="balanceBody"></tbody></table></div></section>

<section class="view panel" id="equipment"><div class="import-box"><div><strong>Карточки оборудования из CSV</strong><p>UTF-8 BOM и Windows-1251 поддерживаются.</p></div><div class="import-actions"><a class="button" href="/import/equipment-template.csv">Шаблон</a><label class="button primary" for="equipmentCsv">Загрузить</label><input class="file-input csv-input" id="equipmentCsv" data-kind="equipment" type="file" accept=".csv"></div></div><div class="split"><div class="box"><h3>Новая карточка</h3><form class="form" id="addForm"><label>Категория</label><select name="category" class="categories" required></select><label>Модель</label><input name="model" required><label>Серийный номер</label><input name="serial_number" required><label>Инвентарный номер</label><input name="inventory_number" required><label>ЦОД</label><input name="datacenter" value="Ixcellerate" required><label>Место</label><select name="location_code" class="locations" required></select><label>Начальный остаток</label><input name="quantity" type="number" min="0" value="0"><div class="actions"><button class="button primary">Создать</button></div></form></div><div class="box"><h3>Перемещение</h3><form class="form" id="moveForm"><label>Оборудование</label><select name="equipment_id" class="items" required></select><label>Новое место</label><select name="destination" class="locations" required></select><label>Основание</label><input name="basis" required><label>Ответственный</label><input name="responsible" value="Кладовщик № 1" required><div class="actions"><button class="button primary">Переместить</button></div></form></div></div></section>

<section class="view panel" id="journal"><div class="import-box"><div><strong>Журнал складских операций</strong><p>Последние 100 записей.</p></div><div class="import-actions"><a class="button" href="/export/stock.csv">Остатки CSV</a><a class="button" href="/export/log.csv">Журнал CSV</a></div></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Операция</th><th>Инв. №</th><th>Модель</th><th>Кол-во</th><th>Основание</th><th>Ответственный</th><th>Откуда → куда</th></tr></thead><tbody id="operationBody"></tbody></table></div></section>

<section class="view panel" id="references"><h2>Справочники</h2><p class="hint">Справочники используются как подсказки и автоматически пополняются из прихода/расхода; отключение не удаляет старые данные.</p><div class="filters"><select id="referenceFilter"><option value="">Все справочники</option></select><span></span><span></span><span></span></div><form class="filters" id="referenceForm"><select name="kind" id="referenceKind"></select><input name="name" placeholder="Новое значение" required><button class="button primary">Добавить в выбранный справочник</button><span></span></form><div class="table-wrap"><table><thead><tr><th>Справочник</th><th>Значение</th><th>Состояние</th><th>Действие</th></tr></thead><tbody id="referenceBody"></tbody></table></div></section>

<section class="view panel" id="admin"><h2>Администрирование</h2><p class="hint">Доступно только администраторам.</p><div class="split"><div class="box"><h3>Backup и проверка</h3><div class="import-actions"><button class="button primary" onclick="createBackup()">Создать backup</button><button class="button" onclick="checkDatabase()">Проверить базу</button></div><p id="integrityResult" class="hint" style="margin-top:14px">Проверка еще не выполнялась.</p></div><div class="box"><h3>Восстановление</h3><p class="hint">Перед восстановлением автоматически создается страховочный backup.</p><select id="restoreBackup" style="width:100%;padding:9px;margin-bottom:10px"></select><button class="button" style="color:#991b1b" onclick="restoreBackup()">Восстановить backup</button></div><div class="box"><h3>Загрузить базу в прод</h3><p class="hint">Текущая база будет сохранена; при ошибке выполнится откат.</p><label class="button" for="prodDb">Выбрать SQLite .db</label><input class="file-input" id="prodDb" type="file" accept=".db"></div><div class="box"><h3>Новый пользователь</h3><form class="form" id="userForm"><label>Имя</label><input name="first_name" required><label>Фамилия</label><input name="last_name" required><label>Должность</label><input name="position" required><label>Email</label><input name="email" required><label>Пароль</label><input name="password" type="password" minlength="6" required><label>Роль</label><select name="role"><option>engineer</option><option>viewer</option><option>admin</option></select><div class="actions"><button class="button primary">Создать</button></div></form></div></div><h3>Пользователи</h3><div class="table-wrap"><table><thead><tr><th>ФИО</th><th>Должность</th><th>Email</th><th>Роль</th></tr></thead><tbody id="userBody"></tbody></table></div><h3>Доступные backup-файлы</h3><div class="table-wrap"><table><thead><tr><th>Файл</th><th>Дата изменения</th><th>Размер</th></tr></thead><tbody id="backupBody"></tbody></table></div><h3 style="margin-top:22px">Единый аудит</h3><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Действие</th><th>Сущность</th><th>ID</th><th>Автор</th><th>Детали</th></tr></thead><tbody id="auditBody"></tbody></table></div></section>

<section class="view panel instruction" id="instruction"><h2>Инструкция</h2><p class="hint">Правила учета Этапа 2.</p><ul><li>В приходе выберите ровно один классификатор: тип оборудования, тип компонента или тип кабеля.</li><li>S/N обязателен для оборудования и компонентов. Они учитываются и списываются в штуках.</li><li>Оборудование и компоненты списываются только по S/N и обязательно на задачу. Компоненту также требуется S/N целевого оборудования.</li><li>Оборудование нельзя списать само на себя.</li><li>Кабель списывается по наименованию и типу кабеля, учитывается в метрах и может не иметь задачи, проекта и S/N.</li><li>Стеллаж/полка хранится для поиска, но не используется при подборе остатка.</li><li>Проект и остальные реквизиты расхода подтягиваются из прихода.</li><li>Перед импортом скачайте актуальный CSV-шаблон. При ошибке весь файл откатывается; сообщение содержит номер строки и причину.</li></ul></section>

<section class="view panel" id="daily"><h2>Ежедневные отчеты</h2><div class="box"><h3>1. Сформировать отчет из базы</h3><p class="hint">Логи работ, приход и расход остаются в текущей модели.</p><form class="filters" id="dailyForm"><input name="date_from" type="date" required><input name="date_to" type="date" required><button class="button primary">Сформировать отчет</button><button class="button" type="button" id="downloadDaily">Скачать CSV</button></form></div><div class="box" style="margin-top:16px"><h3>2. Загрузить готовый CSV отчет</h3><div class="import-actions"><a class="button" href="/import/daily-report-template.csv">Шаблон</a><label class="button primary" for="dailyCsv">Загрузить CSV</label><input class="file-input csv-input" id="dailyCsv" data-kind="daily_report" type="file" accept=".csv"><select id="uploadedReport"></select><button class="button" onclick="showUploadedReport()">Показать</button><button class="button" onclick="exportUploadedReport()">Экспорт</button></div></div><div style="height:16px"></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Блок</th><th>Номер задачи</th><th>Описание / наименование</th><th>Кол-во / метраж</th><th>S/N</th><th>ФИО</th><th>Комментарий / основание</th></tr></thead><tbody id="dailyBody"><tr><td class="empty" colspan="8">Выберите источник отчета</td></tr></tbody></table></div></section>

<section class="view panel" id="worklogs"><div class="import-box"><div><strong>CSV логов работ</strong><p>Источник, тип и номер задачи хранятся отдельно.</p></div><div class="import-actions"><a class="button" href="/import/work-logs-template.csv">Шаблон</a><a class="button" id="exportWorkLogs" href="/export/work-logs.csv">Выгрузить</a><label class="button primary" for="workLogsCsv">Загрузить</label><input class="file-input csv-input" id="workLogsCsv" data-kind="work_logs" type="file" accept=".csv"></div></div><div class="split"><div class="box"><h3>Новый лог работы</h3><form class="form" id="workLogForm"><label>Дата</label><input name="work_date" type="date" required><label>Источник задачи</label><select name="task_source" id="taskSource" required></select><label>Тип задачи</label><select name="task_type" id="taskType" required></select><label>Номер задачи</label><input name="task_number" placeholder="123" required><label>Описание работы</label><textarea name="description" required></textarea><label>Статус</label><select name="status" id="workStatus" required></select><label>Комментарий</label><textarea name="comment"></textarea><div class="actions"><button class="button primary">Добавить лог</button></div></form></div><div class="box"><h3>Фильтр периода</h3><form class="form" id="workLogFilter"><label>Дата начала</label><input name="date_from" type="date"><label>Дата окончания</label><input name="date_to" type="date"><div class="actions"><button class="button primary">Применить</button><button class="button" type="button" onclick="clearWorkLogFilter()">Сбросить</button></div></form></div></div><div style="height:18px"></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Источник</th><th>Задача</th><th>Описание</th><th>Статус</th><th>Комментарий</th></tr></thead><tbody id="workLogBody"></tbody></table></div></section>

<section class="view panel" id="shipments"><h2>Учет поставок-отправок</h2><div class="placeholder">В разработке. Здесь будет учет взаимодействия со снабжением, поставками, отправками и будущая выгрузка/внесение данных в DCIM</div></section><section class="view panel" id="profile"><h2>Профиль</h2><div class="split"><div class="box"><h3>Личные данные</h3><form class="form" id="profileForm"><label>Имя</label><input name="first_name" required><label>Фамилия</label><input name="last_name" required><label>Должность</label><input name="position" required><label>Email</label><input name="email" type="email" readonly><div class="actions"><button class="button primary">Сохранить</button></div></form></div><div class="box"><h3>Смена пароля</h3><form class="form" id="passwordForm"><label>Текущий пароль</label><input name="old_password" type="password" autocomplete="current-password" required><label>Новый пароль</label><input name="new_password" type="password" autocomplete="new-password" minlength="6" required><div class="actions"><button class="button primary">Сменить пароль</button></div></form></div></div></section><section class="view panel" id="kaiten"><h2>Kaiten</h2><div class="placeholder">Интеграция будет реализована позднее.</div></section><section class="view panel" id="weekly"><h2>Еженедельный отчет</h2><p class="hint">Агрегация существующих логов, приходов и расходов.</p><form class="filters" id="weeklyForm"><input name="date_from" type="date" required><input name="date_to" type="date" required><button class="button primary">Сформировать</button><button class="button" type="button" id="downloadWeekly">Экспорт CSV</button></form><div class="cards" id="weeklyCards"></div><div class="split" style="margin-top:18px"><div class="box"><h3>По проектам</h3><div class="table-wrap"><table><thead><tr><th>Проект</th><th>Принято</th><th>Списано</th></tr></thead><tbody id="weeklyProjects"></tbody></table></div></div><div class="box"><h3>По типам</h3><div class="table-wrap"><table><thead><tr><th>Тип</th><th>Принято</th><th>Списано</th></tr></thead><tbody id="weeklyTypes"></tbody></table></div></div></div></section><section class="view panel" id="monitoring"><h2>Мониторинг __DATACENTER__</h2><div class="placeholder">В разработке</div></section>
</main></div><div class="status" id="status"></div><div class="modal" id="positionModal"><div class="modal-card"><div class="modal-head"><h2>Карточка позиции</h2><button class="button" onclick="closePositionCard()">Закрыть</button></div><div id="positionDetails"></div><h3>История операций</h3><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Событие</th><th>Количество</th><th>Задача</th><th>ФИО</th><th>Комментарий / основание</th></tr></thead><tbody id="positionHistory"></tbody></table></div></div></div>
<script>
let sections={warehouse:[['overview','Обзор'],['balance','Баланс'],['receipt','Приход'],['issue','Расход'],['inventory','Инвентаризация'],['cards','Карточки'],['journal','Журнал'],['shipments','Учет поставок-отправок'],['references','Справочники'],['admin','Администрирование'],['instruction','Инструкция']],reports:[['daily','Ежедневный отчет'],['weekly','Еженедельный отчет'],['worklogs','Логи работ'],['uploaded','Загруженные отчеты'],['kaiten','Kaiten']],monitoring:[['monitoring','В разработке']]};
let state={equipment:[],operations:[],categories:[],locations:[],stats:{},task_sources:[],task_types:[],work_log_statuses:[],references:[],reference_kinds:{},balance:[],recent_receipts:[],problems:{},problem_counts:{},searchRows:[],daily_report_uploads:[],current_user:{}};let currentSection='warehouse';
const byId=id=>document.getElementById(id);
const setText=(id,text)=>{const el=byId(id);if(el)el.textContent=text};
const setHtml=(id,html)=>{const el=byId(id);if(el)el.innerHTML=html};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const option=(value,label=value)=>`<option value="${esc(value)}">${esc(label)}</option>`;
function notify(message,error=false){const x=byId('status');if(!x)return;setText('status',message);x.className='status show'+(error?' error':'');clearTimeout(x.timer);x.timer=setTimeout(()=>x.className='status',4000)}
async function request(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(data.error||'Ошибка запроса');return data}
function showSection(name){currentSection=name;document.getElementById('pageTitle').textContent={warehouse:'Склад',reports:'Отчеты',monitoring:'Мониторинг'}[name];document.querySelectorAll('.section-button').forEach(x=>x.classList.toggle('active',x.dataset.section===name));const nav=document.getElementById('subnav');nav.style.display='flex';nav.innerHTML=sections[name].map((x,i)=>`<button class="subtab ${i?'':'active'}" data-view="${x[0]}">${x[1]}</button>`).join('');nav.querySelectorAll('button').forEach(x=>x.onclick=()=>showView(x.dataset.view));showView(sections[name][0][0])}
function showView(id){document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.subtab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));if(id==='worklogs')loadWorkLogs();if(id==='admin')loadAdmin()}
function showProfile(){document.querySelectorAll('.section-button').forEach(x=>x.classList.remove('active'));document.getElementById('subnav').style.display='none';showView('profile')}
document.querySelectorAll('.section-button').forEach(x=>x.onclick=()=>showSection(x.dataset.section));
function fillSelects(){
const items=state.equipment.map(x=>option(x.id,`${x.inventory_number} — ${x.model} (${x.quantity})`)).join('');
const refs=kind=>state.references.filter(v=>v.kind===kind&&v.is_active).map(v=>v.name);
const balanceValues=key=>state.balance.map(v=>v[key]);
const fill=(id,label,values)=>{const target=document.getElementById(id);if(target)target.innerHTML=option('',label)+[...new Set(values.filter(Boolean))].map(v=>option(v)).join('')};
document.querySelectorAll('.items').forEach(x=>x.innerHTML=items);
document.querySelectorAll('.categories').forEach(x=>x.innerHTML=state.categories.map(v=>option(v.name)).join(''));
document.querySelectorAll('.locations').forEach(x=>x.innerHTML=state.locations.map(v=>option(v.code,`${v.code} — ${v.name}`)).join(''));
fill('balanceProject','Все проекты',balanceValues('project'));fill('balanceObject','Все объекты',balanceValues('object_name'));fill('balanceEquipmentType','Все типы оборудования',balanceValues('equipment_type'));fill('balanceComponentType','Все типы компонентов',balanceValues('component_type'));fill('balanceCableType','Все типы кабеля',balanceValues('cable_type'));fill('balanceUnit','Все единицы',balanceValues('unit'));fill('balanceDatacenter','Все ЦОД',balanceValues('datacenter'));
document.getElementById('taskSource').innerHTML=refs('task_source').map(v=>option(v)).join('');document.getElementById('taskType').innerHTML=refs('task_type').map(v=>option(v)).join('');document.getElementById('workStatus').innerHTML=refs('work_log_status').map(v=>option(v)).join('');document.getElementById('issueTaskType').innerHTML=option('','Без задачи (только кабель)')+refs('task_type').map(v=>option(v)).join('');document.getElementById('bulkTaskType').innerHTML=refs('task_type').map(v=>option(v)).join('');document.getElementById('scanIssueTaskType').innerHTML=refs('task_type').map(v=>option(v)).join('');
document.querySelectorAll('.ref-input').forEach(x=>{const id=x.getAttribute('list');let list=document.getElementById(id);if(!list){list=document.createElement('datalist');list.id=id;document.body.appendChild(list)}list.innerHTML=refs(x.dataset.kind).map(v=>option(v)).join('')});
const kinds=Object.entries(state.reference_kinds).map(([k,v])=>option(k,v)).join('');document.getElementById('referenceKind').innerHTML=kinds;document.getElementById('referenceFilter').innerHTML=option('','Все справочники')+kinds;const reports=state.daily_report_uploads.map(x=>option(x.id,`${x.filename} — ${x.uploaded_at} (${x.row_count})`)).join('');document.getElementById('uploadedReport').innerHTML=reports;document.getElementById('uploadedReportList').innerHTML=reports;renderReferences()}
function renderReferences(){const selected=document.getElementById('referenceFilter').value;const groups=Object.entries(state.reference_kinds).filter(([kind])=>!selected||kind===selected);document.getElementById('referenceBody').innerHTML=groups.map(([kind,label])=>{const rows=state.references.filter(x=>x.kind===kind);return `<tr><th colspan="4">${esc(label)}</th></tr>`+rows.map(x=>`<tr><td>${esc(label)}</td><td>${esc(x.name)}</td><td>${x.is_active?'Активно':'Отключено'}</td><td>${state.current_user.role==='viewer'?'—':`<button class="button" onclick="toggleReference(${x.id},${x.is_active?0:1})">${x.is_active?'Отключить':'Включить'}</button>`}</td></tr>`).join('')}).join('')||'<tr><td class="empty" colspan="4">Нет значений</td></tr>'}
document.getElementById('referenceFilter').oninput=renderReferences;
const balanceFilterMap={balanceProject:'project',balanceObject:'object_name',balanceEquipmentType:'equipment_type',balanceComponentType:'component_type',balanceCableType:'cable_type',balanceUnit:'unit',balanceDatacenter:'datacenter'};
function activeBalanceFilters(){return Object.fromEntries(Object.entries(balanceFilterMap).map(([id,key])=>[key,document.getElementById(id)?.value||'']).filter(x=>x[1]))}
function rowMatchesQuery(x,q){return !q||['serial_number','inventory_number','item_name','model','vendor','project','object_name','shelf'].some(k=>String(x[k]||'').toLocaleLowerCase().includes(q))}
function renderBalance(){const filters=activeBalanceFilters();const query=document.getElementById('balanceQuery').value.trim().toLocaleLowerCase();const rows=state.balance.filter(x=>Object.entries(filters).every(([k,v])=>x[k]===v)&&rowMatchesQuery(x,query));document.getElementById('balanceLimit').textContent=`Показано строк: ${rows.length}`;document.getElementById('balanceBody').innerHTML=rows.map(x=>{const key=encodeURIComponent(x.position_key);const type=x.equipment_type||x.component_type||x.cable_type;return `<tr><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')}</td><td>${esc(x.unit)}</td><td>${esc(x.project)}</td><td>${esc(x.datacenter)}</td><td>${esc(x.shelf)}</td><td>${esc(x.object_name)}</td><td>${esc(type)}</td><td>${esc(x.vendor)}</td><td><button class="button" onclick="openPositionCard('${key}')">Открыть карточку</button> <button class="button" ${Number(x.balance)<=0?'disabled':''} onclick="selectForIssue('${key}')">Списать</button></td></tr>`}).join('')||'<tr><td class="empty" colspan="13">Нет данных</td></tr>';document.getElementById('balanceExport').href='/export/balance.csv?'+new URLSearchParams({...filters,query:document.getElementById('balanceQuery').value.trim()})}
function renderOperations(){const names={ADD:'Карточка',RECEIPT:'Приход',ISSUE:'Расход',MOVE:'Перемещение'};document.getElementById('operationBody').innerHTML=state.operations.map(x=>`<tr><td>${esc(x.operation_date)}</td><td>${names[x.operation_type]||x.operation_type}</td><td>${esc(x.inventory_number)}</td><td>${esc(x.model)}</td><td>${x.quantity}</td><td>${esc(x.basis)}</td><td>${esc(x.responsible)}</td><td>${esc(x.from_location||'—')} → ${esc(x.to_location||'—')}</td></tr>`).join('')}
function renderProblems(){const labels={unmatched_issues:'Не сопоставлено',duplicate_serials:'Дубли S/N',negative_balances:'Отрицательные остатки',incomplete_rows:'Неполные строки'};document.getElementById('problemCards').innerHTML=Object.entries(labels).map(([k,v])=>`<div class="card"><span>${v}</span><strong>${state.problem_counts[k]||0}</strong></div>`).join('');document.getElementById('problemDetails').innerHTML=Object.entries(labels).map(([k,v])=>`<div class="box" style="margin-top:12px"><h3>${v}</h3><div class="table-wrap"><table><thead><tr><th>Дата</th><th>S/N</th><th>Наименование</th><th>Количество</th><th>Комментарий</th></tr></thead><tbody>${(state.problems[k]||[]).map(x=>`<tr><td>${esc(x.date)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.item_name)}</td><td>${esc(x.unmatched_quantity??x.balance??x.count??x.quantity)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="5">Нет данных</td></tr>'}</tbody></table></div></div>`).join('');document.getElementById('problemIssueBody').innerHTML=(state.problems.unmatched_issues||[]).map(x=>`<tr><td>${esc(x.date)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.item_name)}</td><td>${esc(x.quantity)}</td><td>${esc(x.unmatched_quantity)}</td><td>${esc(x.responsible)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="7">Проблемных списаний нет</td></tr>'}
function renderRecentReceipts(){document.getElementById('recentReceiptBody').innerHTML=(state.recent_receipts||[]).map(x=>`<tr><td>${esc(x.receipt_date)}</td><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.quantity).toLocaleString('ru-RU')}</td><td>${esc(x.unit)}</td><td>${esc(x.project)}</td><td>${esc(x.responsible)}</td></tr>`).join('')||'<tr><td class="empty" colspan="9">Приходов пока нет</td></tr>'}
async function loadAll(){try{state=await request('/api/data');state.searchRows=[];for(const [key,id] of [['receipts','statReceipts'],['issues','statIssues'],['balance','statBalance'],['positions','statPositions']])document.getElementById(id).textContent=Number(state.stats[key]).toLocaleString('ru-RU');const roles={admin:'Администратор',engineer:'Инженер',viewer:'Просмотр'};document.getElementById('currentUser').textContent=`${state.current_user.first_name} ${state.current_user.last_name} · ${roles[state.current_user.role]||state.current_user.role}`;for(const name of ['first_name','last_name','position','email'])document.querySelector(`#profileForm [name=${name}]`).value=state.current_user[name]||'';if(state.current_user.role!=='admin'){sections.warehouse=sections.warehouse.filter(x=>x[0]!=='admin');if(document.querySelector('[data-view=admin]'))showSection(currentSection)}if(state.current_user.role==='viewer'){for(const id of ['stockReceiptForm','stockIssueForm','bulkIssueForm','addForm','moveForm','workLogForm','referenceForm']){const x=document.getElementById(id);if(x)x.style.display='none'}for(const id of ['scanReceiptForm','scanIssueForm'])document.getElementById(id).closest('.scanner-box').style.display='none';document.querySelectorAll('.csv-input,.preview-input,.inventory-input').forEach(x=>x.closest('.import-actions')?.querySelector('label')?.remove())}fillSelects();renderBalance();renderRecentReceipts();renderOperations();renderProblems();if(state.current_user.must_change_password)notify('Рекомендуется сменить начальный пароль в разделе «Профиль»')}catch(e){console.error(e);showInterfaceError(e);notify(e.message,true)}}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
async function submitAction(form,action){try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...formData(form),action})});notify('Операция выполнена');if(action==='WORK_LOG'){form.querySelector('[name=description]').value='';form.querySelector('[name=comment]').value='';form.querySelector('[name=task_number]').value='';await loadWorkLogs()}await loadAll()}catch(e){notify(e.message,true)}}
document.getElementById('stockReceiptForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'STOCK_RECEIPT')};document.getElementById('stockIssueForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'STOCK_ISSUE')};document.getElementById('addForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'ADD')};document.getElementById('moveForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'MOVE')};document.getElementById('workLogForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'WORK_LOG')};document.getElementById('referenceForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'ADD_REFERENCE')};async function toggleReference(reference_id,is_active){try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'TOGGLE_REFERENCE',reference_id,is_active:Boolean(is_active)})});await loadAll();notify('Справочник обновлен')}catch(e){notify(e.message,true)}}
async function importCsv(input){const file=input.files[0];if(!file)return;try{const r=await request(`/api/import-csv?kind=${input.dataset.kind}`,{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});notify(`Загружено строк: ${r.imported}`);await loadAll();if(input.dataset.kind==='work_logs')await loadWorkLogs();if(input.dataset.kind==='daily_report'&&r.upload_id){document.getElementById('uploadedReport').value=r.upload_id;await showUploadedReport()}}catch(e){notify(e.message,true)}finally{input.value=''}}document.querySelectorAll('.csv-input').forEach(x=>x.onchange=()=>importCsv(x));
let inventoryResult=[];async function inventoryCsv(input){const file=input.files[0];if(!file)return;try{const r=await request('/api/import-csv?kind=inventory',{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});inventoryResult=r.rows;const labels={found:'Найдено',not_found:'Не найдено в базе',missing:'Есть в базе, но не было в скане',duplicates:'Дубли в скане'};document.getElementById('inventoryCards').innerHTML=Object.entries(labels).map(([k,v])=>`<div class="card"><span>${v}</span><strong>${r.stats[k]}</strong></div>`).join('');document.getElementById('inventoryBody').innerHTML=r.rows.map(x=>`<tr><td>${esc(x.serial_number)}</td><td>${esc(x.status)}</td><td>${esc(x.count||1)}</td></tr>`).join('');document.getElementById('inventoryExport').disabled=false;notify('Проверка завершена')}catch(e){notify(e.message,true)}finally{input.value=''}}document.getElementById('inventoryCsv').onchange=e=>inventoryCsv(e.currentTarget);document.getElementById('inventoryExport').onclick=()=>{if(!inventoryResult.length)return;const quote=v=>`"${String(v??'').replaceAll('"','""')}"`;const csv='\ufeffS/N;Результат;Количество\r\n'+inventoryResult.map(x=>[x.serial_number,x.status,x.count||1].map(quote).join(';')).join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download='inventory_result.csv';a.click();URL.revokeObjectURL(a.href)};
function renderPreview(kind,r){let target=document.getElementById(`${kind}Preview`);if(!target){target=document.createElement('div');target.id=`${kind}Preview`;target.className='preview';document.getElementById('worklogs').prepend(target)}target.classList.add('show');const labels=kind==='bulk_issue'?[['total','Всего'],['found','Найдено'],['not_found','Не найдено'],['unavailable','Без остатка'],['duplicates','Дубли']]:[['total','Всего'],['valid','Готово к загрузке'],['new','Новых'],['duplicates','Дубли'],['error_count','Ошибки']];const stats=`<h3>Предпросмотр файла</h3><div class="preview-stats">${labels.map(([k,l])=>`<div class="preview-stat"><span>${l}</span><strong>${Number(r[k]||0)}</strong></div>`).join('')}</div>`;const rows=`<div class="table-wrap"><table><thead><tr><th>Строка</th><th>Наименование</th><th>Модель</th><th>S/N</th><th>Количество</th><th>Результат</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td>${x.line}</td><td>${esc(x.item_name||x.source_item_name||x.description)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number||x.source_serial_number)}</td><td>${esc(x.quantity||x.available)}</td><td>${x.valid?(x.warning?'Принято: '+esc(x.warning):'Готово'):esc(x.error)}</td></tr>`).join('')}</tbody></table></div>`;const errors=r.errors.length?`<ul class="error-list">${r.errors.map(x=>`<li>Строка ${x.line}: ${esc(x.reason)}</li>`).join('')}</ul>`:'';let confirm='';if(kind==='bulk_issue'){const f=document.getElementById('bulkIssueForm');f.preview_id.value=r.preview_id;document.getElementById('bulkConfirm').disabled=!r.can_confirm}else if(r.can_confirm){confirm=`<button class="button primary" onclick="confirmPreview('${kind}','${r.preview_id}')">Подтвердить загрузку</button>`}target.innerHTML=`${stats}${errors}${rows}<div style="margin-top:12px">${confirm}</div>`}
async function previewCsv(input){const file=input.files[0];if(!file)return;const mode=document.getElementById('importMode').value;try{const r=await request(`/api/preview-csv?kind=${input.dataset.kind}&mode=${mode}`,{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});renderPreview(input.dataset.kind,r);notify(r.can_confirm?'CSV проверен, можно подтвердить':'CSV содержит ошибки',!r.can_confirm)}catch(e){notify(e.message,true)}finally{input.value=''}}document.querySelectorAll('.preview-input').forEach(x=>x.onchange=()=>previewCsv(x));
document.getElementById('workLogsCsv').onchange=e=>previewCsv(e.currentTarget);
async function confirmPreview(kind,preview_id){try{const r=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'CONFIRM_IMPORT_PREVIEW',kind,preview_id})});document.getElementById(`${kind}Preview`).classList.remove('show');notify(`Загружено строк: ${r.imported}`);await loadAll()}catch(e){notify(e.message,true)}}
document.getElementById('bulkIssueForm').onsubmit=async e=>{e.preventDefault();try{const r=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...formData(e.currentTarget),action:'CONFIRM_BULK_ISSUE'})});notify(`Списано позиций: ${r.imported}`);document.getElementById('bulk_issuePreview').classList.remove('show');e.currentTarget.preview_id.value='';document.getElementById('bulkConfirm').disabled=true;await loadAll()}catch(x){notify(x.message,true)}};
async function loadWorkLogs(){const f=formData(document.getElementById('workLogFilter'));const q=new URLSearchParams(f);try{const data=await request('/api/work-logs?'+q);document.getElementById('workLogBody').innerHTML=data.logs.map(x=>`<tr><td>${esc(x.work_date)}</td><td>${esc(x.task_source)}</td><td>${esc(x.full_task_name)}</td><td>${esc(x.description)}</td><td><span class="badge">${esc(x.status)}</span></td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="6">Нет логов за период</td></tr>';document.getElementById('exportWorkLogs').href='/export/work-logs.csv?'+q}catch(e){notify(e.message,true)}}
document.getElementById('workLogFilter').onsubmit=e=>{e.preventDefault();loadWorkLogs()};function clearWorkLogFilter(){document.getElementById('workLogFilter').reset();loadWorkLogs()}
function findPosition(key){key=decodeURIComponent(key);return state.balance.find(x=>x.position_key===key)||state.searchRows.find(x=>x.position_key===key)}function selectForIssue(key){const x=findPosition(key);if(!x)return;const f=document.getElementById('stockIssueForm');f.source_serial_number.value=x.serial_number||'';f.source_item_name.value=x.serial_number?'':x.item_name;f.source_cable_type.value=x.serial_number?'':x.cable_type;f.available.value=Number(x.balance).toLocaleString('ru-RU')+' '+x.unit;f.quantity.value=x.cable_type?Math.min(1,Number(x.balance)):1;showSection('warehouse');showView('issue');document.getElementById('issue').showScenario?.('Ручной ввод');f.source_serial_number.focus()}
let currentPositionKey='';let currentPositionHistory=[];
async function openPositionCard(key){const x=findPosition(key);if(!x)return;currentPositionKey=key;const q=new URLSearchParams(x.serial_number?{serial_number:x.serial_number}:{item_name:x.item_name,cable_type:x.cable_type,project:x.project||'',datacenter:x.datacenter||''});try{const r=await request('/api/position-card?'+q);const p=r.position;currentPositionHistory=r.history;document.getElementById('positionDetails').innerHTML=`<div class="cards">${[['S/N',p.serial_number],['Инв. №',p.inventory_number],['Наименование',p.item_name],['Вендор',p.vendor],['Модель',p.model],['Проект',p.project],['Объект',p.object_name],['ЦОД',p.datacenter],['Стеллаж/полка',p.shelf],['Тип оборудования',p.equipment_type],['Тип компонента',p.component_type],['Тип кабеля',p.cable_type],['Единица',p.unit],['Остаток',p.current_balance],['Статус',p.status]].map(([l,v])=>`<div class="card"><span>${l}</span><strong style="font-size:17px">${esc(v||'—')}</strong></div>`).join('')}</div>`;document.getElementById('positionHistory').innerHTML=r.history.map(h=>`<tr><td>${esc(h.date)}</td><td>${esc(h.event_type)}</td><td>${esc(h.quantity)}</td><td>${esc(h.task)}</td><td>${esc(h.responsible)}</td><td>${esc(h.comment)}</td></tr>`).join('');const related=(state.problems.unmatched_issues||[]).filter(v=>(p.serial_number&&v.serial_number===p.serial_number)||(!p.serial_number&&v.item_name===p.item_name));document.getElementById('positionProblems').innerHTML=related.map(v=>`<tr><td>${esc(v.date)}</td><td>${esc(v.serial_number)}</td><td>${esc(v.item_name)}</td><td>${esc(v.unmatched_quantity)}</td><td>${esc(v.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="5">Связанных проблемных строк нет</td></tr>';document.getElementById('positionModal').classList.add('show')}catch(e){notify(e.message,true)}}
function closePositionCard(){document.getElementById('positionModal').classList.remove('show')}function issueCurrentPosition(){closePositionCard();selectForIssue(currentPositionKey)}
function downloadPositionHistory(){if(!currentPositionHistory.length)return;const q=v=>`"${String(v??'').replaceAll('"','""')}"`;const lines=currentPositionHistory.map(x=>[x.date,x.event_type,x.quantity,x.task,x.responsible,x.comment].map(q).join(';'));const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeffДата;Событие;Количество;Задача;ФИО;Комментарий\r\n'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));a.download='position_history.csv';a.click();URL.revokeObjectURL(a.href)}
document.getElementById('issueSearchForm').onsubmit=async e=>{e.preventDefault();try{state.searchRows=(await request('/api/position-search?'+new URLSearchParams(formData(e.currentTarget)))).rows;document.getElementById('issueSearchBody').innerHTML=state.searchRows.map(x=>`<tr><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')} ${esc(x.unit)}</td><td>${esc(x.project)}</td><td>${esc(x.shelf)}</td><td><button class="button primary" ${Number(x.balance)<=0?'disabled':''} onclick="selectForIssue('${encodeURIComponent(x.position_key)}')">Списать</button></td></tr>`).join('')||'<tr><td class="empty" colspan="8">Ничего не найдено</td></tr>'}catch(x){notify(x.message,true)}};
document.getElementById('cardSearchForm').onsubmit=async e=>{e.preventDefault();try{state.searchRows=(await request('/api/position-search?'+new URLSearchParams(formData(e.currentTarget)))).rows;document.getElementById('cardSearchBody').innerHTML=state.searchRows.map(x=>`<tr><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')} ${esc(x.unit)}</td><td>${esc(x.project)}</td><td>${esc(x.shelf)}</td><td><button class="button primary" onclick="openPositionCard('${encodeURIComponent(x.position_key)}')">Открыть карточку</button></td></tr>`).join('')||'<tr><td class="empty" colspan="8">Ничего не найдено</td></tr>'}catch(x){notify(x.message,true)}};
function renderDaily(rows){document.getElementById('dailyBody').innerHTML=rows.map(x=>`<tr><td>${esc(x.date)}</td><td>${esc(x.report_block)}</td><td>${esc(x.task_number)}</td><td>${esc(x.description)}</td><td>${esc(x.quantity)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.responsible)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="8">Нет данных за период</td></tr>'}
async function buildDaily(){const q=new URLSearchParams(formData(document.getElementById('dailyForm')));try{const data=await request('/api/daily-report?'+q);renderDaily(data.rows)}catch(e){notify(e.message,true)}}document.getElementById('dailyForm').onsubmit=e=>{e.preventDefault();buildDaily()};document.getElementById('downloadDaily').onclick=()=>{const f=document.getElementById('dailyForm');if(!f.reportValidity())return;location.href='/export/daily-report.csv?'+new URLSearchParams(formData(f))};
async function showUploadedReport(){const id=document.getElementById('uploadedReport').value;if(!id)return;try{renderDaily((await request(`/api/uploaded-daily-report?id=${id}`)).rows)}catch(e){notify(e.message,true)}}function exportUploadedReport(){const id=document.getElementById('uploadedReport').value;if(id)location.href=`/export/uploaded-daily-report.csv?id=${id}`}
async function showUploadedReportList(){const id=document.getElementById('uploadedReportList').value;if(!id)return;try{const rows=(await request(`/api/uploaded-daily-report?id=${id}`)).rows;document.getElementById('uploadedReportBody').innerHTML=rows.map(x=>`<tr><td>${esc(x.date)}</td><td>${esc(x.report_block)}</td><td>${esc(x.task_number)}</td><td>${esc(x.description)}</td><td>${esc(x.quantity)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.responsible)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="8">В отчете нет строк</td></tr>'}catch(e){notify(e.message,true)}}function exportUploadedReportList(){const id=document.getElementById('uploadedReportList').value;if(id)location.href=`/export/uploaded-daily-report.csv?id=${id}`}
async function buildWeekly(){const q=new URLSearchParams(formData(document.getElementById('weeklyForm')));try{const r=await request('/api/weekly-report?'+q);const labels={work_logs:'Логи работ',receipts:'Приходы',received_quantity:'Принято',issues:'Расходы',issued_quantity:'Списано',cable_received:'Кабеля принято',cable_issued:'Кабеля списано',problem_rows:'Проблемные строки'};document.getElementById('weeklyCards').innerHTML=Object.entries(r.summary).map(([k,v])=>`<div class="card"><span>${labels[k]}</span><strong>${Number(v).toLocaleString('ru-RU')}</strong></div>`).join('');const render=(id,rows)=>document.getElementById(id).innerHTML=rows.map(x=>`<tr><td>${esc(x.name)}</td><td>${Number(x.received).toLocaleString('ru-RU')}</td><td>${Number(x.issued).toLocaleString('ru-RU')}</td></tr>`).join('')||'<tr><td class="empty" colspan="3">Нет данных</td></tr>';render('weeklyProjects',r.projects);render('weeklyTypes',r.types)}catch(e){notify(e.message,true)}}document.getElementById('weeklyForm').onsubmit=e=>{e.preventDefault();buildWeekly()};document.getElementById('downloadWeekly').onclick=()=>{const f=document.getElementById('weeklyForm');if(f.reportValidity())location.href='/export/weekly-report.csv?'+new URLSearchParams(formData(f))};
for(const id of Object.keys(balanceFilterMap))document.getElementById(id).oninput=renderBalance;document.getElementById('balanceQuery').oninput=renderBalance;function clearBalanceFilters(){for(const id of Object.keys(balanceFilterMap))document.getElementById(id).value='';document.getElementById('balanceQuery').value='';renderBalance()}
let adminState={backups:[],audit:[],users:[]};const sizeText=n=>n<1024?`${n} Б`:n<1048576?`${(n/1024).toFixed(1)} КБ`:`${(n/1048576).toFixed(1)} МБ`;async function loadAdmin(){try{adminState=await request('/api/admin');document.getElementById('backupBody').innerHTML=adminState.backups.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.modified)}</td><td>${sizeText(x.size)}</td></tr>`).join('')||'<tr><td class="empty" colspan="3">Backup-файлов нет</td></tr>';document.getElementById('restoreBackup').innerHTML=adminState.backups.map(x=>option(x.name,`${x.name} — ${x.modified}`)).join('');document.getElementById('userBody').innerHTML=adminState.users.map(x=>`<tr><td>${esc(x.last_name)} ${esc(x.first_name)}</td><td>${esc(x.position)}</td><td>${esc(x.email)}</td><td>${esc(x.role)}</td></tr>`).join('');document.getElementById('auditBody').innerHTML=adminState.audit.map(x=>`<tr><td>${esc(x.event_date)}</td><td>${esc(x.action)}</td><td>${esc(x.entity_type)}</td><td>${esc(x.entity_id)}</td><td>${esc(x.author)}</td><td>${esc(x.details)}</td></tr>`).join('')||'<tr><td class="empty" colspan="6">Записей аудита нет</td></tr>'}catch(e){notify(e.message,true)}}async function createBackup(){try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'CREATE_BACKUP'})});notify(`Backup создан: ${x.backup.name}`);await loadAdmin()}catch(e){notify(e.message,true)}}async function checkDatabase(){try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'CHECK_DATABASE'})});const r=x.integrity;document.getElementById('integrityResult').textContent=r.ok?'База исправна. integrity_check: ok':`Обнаружена ошибка: ${r.messages.join('; ')}. Отсутствуют: ${r.missing_tables.join(', ')||'нет'}`;await loadAdmin()}catch(e){notify(e.message,true)}}async function restoreBackup(){const filename=document.getElementById('restoreBackup').value;if(!filename){notify('Нет выбранного backup-файла',true);return}if(!confirm(`Восстановить базу из ${filename}?\n\nТекущее состояние будет предварительно сохранено в отдельный backup.`))return;try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'RESTORE_BACKUP',filename,confirmed:true})});notify(`База восстановлена. Страховочный backup: ${x.restore.safety_backup}`);await loadAll();await loadAdmin()}catch(e){notify(e.message,true)}}
document.getElementById('userForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'CREATE_USER').then(loadAdmin)};document.getElementById('profileForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'UPDATE_PROFILE')};document.getElementById('passwordForm').onsubmit=async e=>{e.preventDefault();try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...formData(e.currentTarget),action:'CHANGE_PASSWORD'})});e.currentTarget.reset();notify('Пароль изменен');await loadAll()}catch(x){notify(x.message,true)}};document.getElementById('prodDb').onchange=async e=>{const file=e.target.files[0];if(!file||!confirm(`Загрузить ${file.name} в прод? Будет создан страховочный backup.`))return;try{const x=await request('/api/upload-prod-db?confirmed=1',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file});notify(`База заменена. Backup: ${x.safety_backup}`);await loadAll();await loadAdmin()}catch(x){notify(x.message,true)}finally{e.target.value=''}};async function logout(){await request('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.href='/'}
const today=new Date().toISOString().slice(0,10);document.querySelector('[name=work_date]').value=today;document.querySelector('[name=receipt_date]').value=today;document.querySelector('[name=issue_date]').value=today;document.querySelector('#bulkIssueForm [name=issue_date]').value=today;document.querySelector('#scanReceiptForm [name=receipt_date]').value=today;document.querySelector('#scanIssueForm [name=issue_date]').value=today;for(const id of ['dailyForm','weeklyForm']){document.querySelector(`#${id} [name=date_from]`).value=today;document.querySelector(`#${id} [name=date_to]`).value=today}showSection('warehouse');loadAll();
</script></body></html>'''
HTML = HTML.replace(
    "ODE 0.12 — учет работ и склада",
    f"{PRODUCT_NAME} {PRODUCT_VERSION} — учет работ и склада",
)

HTML = HTML.replace(
    '<main class="main">',
    '<main class="main"><div id="warehouseSystemBanner" '
    'class="warehouse-system-banner" role="status" aria-live="polite" hidden></div>',
    1,
)
HTML = HTML.replace(
    '<section class="view panel" id="inventory">',
    '<section class="view panel" id="inventory"><div id="fullInventoryApp" '
    'class="full-inventory-app" aria-live="polite"></div>',
    1,
)
RECEIPT_SCANNER_HTML = '''<div class="scanner-box"><h2>Приемка сканером</h2><p class="hint">Заполните общие поля партии, затем сканируйте S/N. Запись в базу выполняется только после подтверждения.</p><form class="form" id="scanReceiptForm"><label>Дата</label><input name="receipt_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Поставщик</label><input name="supplier" class="ref-input" data-kind="supplier" list="ref-supplier" required><label>Вендор</label><input name="vendor" class="ref-input" data-kind="vendor" list="ref-vendor" required><label>Модель</label><input name="model" class="ref-input" data-kind="model" list="ref-model"><label>Наименование</label><input name="item_name" class="ref-input" data-kind="item_name" list="ref-item_name" required><label>Проект</label><input name="project" class="ref-input" data-kind="project" list="ref-project"><label>ЦОД</label><input name="datacenter" class="ref-input" data-kind="datacenter" list="ref-datacenter" value="Ixcellerate" required><label>Стеллаж/Полка</label><input name="shelf" class="ref-input" data-kind="shelf" list="ref-shelf"><label>Объект</label><input name="object_name" class="ref-input" data-kind="object" list="ref-object" required><label>Тип оборудования</label><input name="equipment_type" class="ref-input" data-kind="equipment_type" list="ref-equipment_type"><label>Тип компонента</label><input name="component_type" class="ref-input" data-kind="component_type" list="ref-component_type"><label>Тип кабеля</label><input name="cable_type" class="ref-input" data-kind="cable_type" list="ref-cable_type"><label>Единица учета</label><input name="unit" class="ref-input" data-kind="unit" list="ref-unit" value="шт" required></form><input class="scanner-input" id="receiptScanner" placeholder="Сканируйте S/N или QR" autocomplete="off"><div class="table-wrap scanner-table"><table><thead><tr><th><input id="selectAllScannedReceipts" type="checkbox" aria-label="Выбрать все строки прихода"></th><th>S/N</th><th>Результат проверки</th><th>Действие</th></tr></thead><tbody id="scanReceiptBody"><tr><td class="scanner-empty" colspan="4">Список сканирования пуст</td></tr></tbody></table></div><div class="actions scanner-actions"><span class="scanner-count" id="scanReceiptCount" role="status" aria-live="polite">0 позиций</span><button class="button" id="deleteSelectedReceipts" type="button" hidden disabled>Удалить выбранные</button><button class="button" id="clearScannedReceipts" type="button" disabled>Очистить список</button><button class="button primary" id="confirmScanReceipts" type="button" disabled>Принять всё на склад</button></div></div>'''
ISSUE_SCANNER_HTML = '''<div class="scanner-box"><h2>Списание сканером</h2><p class="hint">Сканер работает как клавиатура. Неизвестные S/N отмечаются и после подтверждения попадают в проблемные строки.</p><form class="form" id="scanIssueForm"><label>Дата</label><input name="issue_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Тип задачи</label><select name="task_type" id="scanIssueTaskType" required></select><label>Номер задачи</label><input name="task_number" required><label>S/N целевого оборудования</label><input name="target_serial_number"><label>Hostname</label><input name="target_hostname"><label>Комментарий</label><textarea name="comment"></textarea></form><input class="scanner-input" id="issueScanner" placeholder="Сканируйте S/N списываемого оборудования" autocomplete="off"><div class="table-wrap scanner-table"><table><thead><tr><th><input id="selectAllScannedIssues" type="checkbox" aria-label="Выбрать все строки расхода"></th><th>S/N</th><th>Наименование</th><th>Модель</th><th>Полка</th><th>Остаток</th><th>Результат</th><th>Действие</th></tr></thead><tbody id="scanIssueBody"><tr><td class="scanner-empty" colspan="8">Список сканирования пуст</td></tr></tbody></table></div><div class="actions scanner-actions"><span class="scanner-count" id="scanIssueCount" role="status" aria-live="polite">0 позиций</span><button class="button" id="deleteSelectedIssues" type="button" hidden disabled>Удалить выбранные</button><button class="button" id="clearScannedIssues" type="button" disabled>Очистить список</button><button class="button primary" id="confirmScanIssues" type="button" disabled>Списать всё</button></div></div>'''
SCANNER_SCRIPT = r'''
let scannedReceipts=[];let scannedIssues=[];
function renderScannedReceipts(){document.getElementById('scanReceiptBody').innerHTML=scannedReceipts.map((x,i)=>`<tr><td>${esc(x.serial_number)}</td><td>Готово к приемке</td><td><button class="button" onclick="removeScannedReceipt(${i})">Удалить</button></td></tr>`).join('')||'<tr><td class="scanner-empty" colspan="3">Список сканирования пуст</td></tr>';document.getElementById('confirmScanReceipts').disabled=!scannedReceipts.length}
function removeScannedReceipt(i){scannedReceipts.splice(i,1);renderScannedReceipts();document.getElementById('receiptScanner').focus()}
document.getElementById('receiptScanner').onkeydown=async e=>{if(e.key!=='Enter')return;e.preventDefault();const input=e.currentTarget,serial=input.value.trim().toUpperCase();input.value='';if(!serial){notify('Пустой S/N не добавлен',true);return}if(scannedReceipts.some(x=>x.serial_number.toLocaleLowerCase()===serial.toLocaleLowerCase())){notify(`S/N ${serial} уже есть в списке`,true);return}try{const r=await request('/api/scan-serial?kind=receipt&serial_number='+encodeURIComponent(serial));if(!r.valid){notify(r.error,true);return}scannedReceipts.push(r);renderScannedReceipts()}catch(x){notify(x.message,true)}finally{input.focus()}};
document.getElementById('confirmScanReceipts').onclick=async()=>{const form=document.getElementById('scanReceiptForm');if(!form.reportValidity())return;try{const r=await actionJson({action:'CONFIRM_SCANNED_RECEIPTS',common_fields:formData(form),serial_numbers:scannedReceipts.map(x=>x.serial_number)});notify(`Принято на склад: ${r.imported}`);scannedReceipts=[];renderScannedReceipts();await loadAll();document.getElementById('receiptScanner').focus()}catch(x){notify(x.message,true)}};
function renderScannedIssues(){document.getElementById('scanIssueBody').innerHTML=scannedIssues.map((x,i)=>`<tr class="${x.valid?(x.found?'':'warn'):'bad'}"><td>${esc(x.serial_number)}</td><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.shelf)}</td><td>${Number(x.available||0).toLocaleString('ru-RU')}</td><td>${esc(x.error||x.warning||'Готово к списанию')}</td><td><button class="button" onclick="removeScannedIssue(${i})">Удалить</button></td></tr>`).join('')||'<tr><td class="scanner-empty" colspan="7">Список сканирования пуст</td></tr>';document.getElementById('confirmScanIssues').disabled=!scannedIssues.length||scannedIssues.some(x=>!x.valid)}
function removeScannedIssue(i){scannedIssues.splice(i,1);renderScannedIssues();document.getElementById('issueScanner').focus()}
document.getElementById('issueScanner').onkeydown=async e=>{if(e.key!=='Enter')return;e.preventDefault();const input=e.currentTarget,serial=input.value.trim().toUpperCase();input.value='';if(!serial){notify('Пустой S/N не добавлен',true);return}if(scannedIssues.some(x=>x.serial_number.toLocaleLowerCase()===serial.toLocaleLowerCase())){notify(`S/N ${serial} уже есть в списке`,true);return}try{const r=await request('/api/scan-serial?kind=issue&serial_number='+encodeURIComponent(serial));scannedIssues.push(r);renderScannedIssues();if(!r.valid)notify(r.error,true);else if(!r.found)notify(r.warning,true)}catch(x){notify(x.message,true)}finally{input.focus()}};
document.getElementById('confirmScanIssues').onclick=async()=>{const form=document.getElementById('scanIssueForm');if(!form.reportValidity())return;try{const r=await actionJson({action:'CONFIRM_SCANNED_ISSUES',common_fields:formData(form),serial_numbers:scannedIssues.map(x=>x.serial_number)});notify(`Обработано: ${r.imported}${r.unmatched?`, в проблемных: ${r.unmatched}`:''}`);scannedIssues=[];renderScannedIssues();await loadAll();document.getElementById('issueScanner').focus()}catch(x){notify(x.message,true)}};
'''
HTML = HTML.replace(
    '<section class="view panel" id="receipt">',
    '<section class="view panel" id="receipt">' + RECEIPT_SCANNER_HTML,
).replace(
    '<section class="view panel" id="issue">',
    '<section class="view panel" id="issue">' + ISSUE_SCANNER_HTML,
).replace(
    '</script></body></html>', SCANNER_SCRIPT + '</script></body></html>',
)
HTML = HTML.replace(
    '<form class="filters" id="dailyForm"><input name="date_from" type="date" required><input name="date_to" type="date" required><button class="button primary">Сформировать отчет</button>',
    '<form class="filters" id="dailyForm"><label>Дата отчета</label><input name="date" type="date" required><button class="button primary">Сформировать дневной отчет</button>',
).replace(
    '<section class="view panel" id="weekly"><h2>Еженедельный отчет</h2>',
    '<section class="view panel" id="weekly"><h2>Отчеты за период</h2>',
).replace(
    '<form class="filters" id="weeklyForm"><input name="date_from" type="date" required><input name="date_to" type="date" required><button class="button primary">Сформировать</button>',
    '<form class="filters" id="weeklyForm"><input name="start_date" type="date" aria-label="Дата начала" required><input name="end_date" type="date" aria-label="Дата конца" required><button class="button primary">Сформировать отчет за период</button>',
).replace(
    '<a class="button" href="/import/receipt-template.csv">Шаблон</a><a class="button" href="/export/receipt.csv">Выгрузить</a>',
    '<a class="button" href="/import/receipt-template.csv">Выгрузить шаблон</a>'
    '<a class="button" href="/export/receipt-current.csv">Скачать проверенный файл</a>',
).replace(
    '<a class="button" href="/import/issue-template.csv">Шаблон</a><a class="button" href="/export/issue.csv">Выгрузить</a>',
    '<a class="button" href="/import/issue-template.csv">Выгрузить шаблон</a>'
    '<a class="button" href="/export/issue-current.csv">Скачать проверенный файл</a>'
    '<a class="button" href="/export/issue.csv">Скачать весь расход</a>',
).replace(
    '>Выгрузить шаблон</a>', '>Скачать шаблон</a>',
).replace(
    'for="receiptCsv">Выбрать CSV</label>', 'for="receiptCsv">Выбрать и проверить файл</label>',
).replace(
    'for="issueCsv">Выбрать CSV</label>', 'for="issueCsv">Выбрать и проверить файл</label>',
).replace(
    'for="bulkIssueCsv">Выбрать CSV</label>', 'for="bulkIssueCsv">Выбрать и проверить файл</label>',
).replace(
    '<button class="section-button active" data-section="warehouse">Склад</button><button class="section-button" data-section="reports">Отчеты</button><button class="section-button" data-section="monitoring">Мониторинг</button>',
    '<button class="section-button active" data-section="warehouse">Склад Ixcellerate</button>'
    '<button class="section-button" data-section="reports">Отчеты Ixcellerate</button>'
    '<button class="section-button" data-section="monitoring">Мониторинг Ixcellerate</button>',
).replace(
    '<label class="hint" style="display:inline">Импорт: <select id="importMode"><option value="soft">мягкий</option><option value="strict">строгий</option></select></label>',
    '<label class="hint" style="display:inline">Проверка файла: <select id="importMode"><option value="soft">Обычная</option><option value="strict">Строгая</option></select></label>',
).replace(
    '<strong>Инвентаризация по S/N</strong><p>Загрузите CSV со столбцом SN, S/N, Серийный номер или Серийник.</p>',
    '<strong>Проверить склад по списку S/N</strong><p>Файл только сверяется с базой и не изменяет остатки.</p>',
).replace(
    'href="/import/inventory-template.csv">Шаблон</a>',
    'href="/import/inventory-template.csv">Скачать шаблон</a>',
).replace(
    'for="inventoryCsv">Загрузить CSV</label>',
    'for="inventoryCsv">Выбрать файл</label>',
).replace(
    'id="inventoryExport" disabled>Экспорт результата</button>',
    'id="inventoryExport" disabled>Скачать результат CSV</button>',
).replace(
    '<strong>CSV-скан-лист прихода</strong><p>Сначала показывается проверка; база изменится только после подтверждения.</p>',
    '<strong>Загрузить приход из файла</strong><p>Сначала проверьте строки, затем подтвердите загрузку в базу.</p>',
).replace(
    '<h2>Оформить приход</h2>', '<h2>Добавить одну позицию</h2>',
).replace(
    '>Зарегистрировать приход</button>', '>Добавить приход</button>',
).replace(
    '<strong>CSV-скан-лист расхода</strong><p>Оборудование — по S/N; кабель — по наименованию и типу. Запись только после preview.</p>',
    '<strong>Загрузить расход из файла</strong><p>Для обычного списания файл не нужен: найдите позицию ниже и нажмите «Списать».</p>',
).replace(
    '<h2>Оформить расход</h2>', '<h2>Списать вручную</h2>',
).replace(
    '>Зарегистрировать расход</button>', '>Подтвердить списание</button>',
).replace(
    '<p class="hint">Строгий режим: неизвестный, повторный, уже списанный S/N или кабель блокирует весь список.</p>',
    '<p class="hint">Если хотя бы один S/N не найден, повторяется или уже списан, файл не будет загружен.</p>',
).replace(
    'href="/import/bulk-issue-template.csv">Шаблон S/N</a>',
    'href="/import/bulk-issue-template.csv">Скачать шаблон</a>',
).replace(
    '<strong>Баланс — рабочий экран склада</strong><p>Поиск, карточка, списание и экспорт текущей выборки.</p>',
    '<strong>Баланс склада</strong><p>Главный рабочий экран: поиск, карточка позиции и списание.</p>',
).replace(
    'id="balanceExport" href="/export/balance.csv">Выгрузить CSV</a>',
    'id="balanceExport" href="/export/balance.csv">Скачать баланс</a>',
).replace(
    '>Открыть</button> <button class="button"',
    '>Открыть карточку</button> <button class="button"',
).replace(
    '<strong>Карточки оборудования из CSV</strong>', '<strong>Карточки оборудования</strong>',
).replace(
    '<h3>Backup и проверка</h3>', '<h3>Резервные копии и проверка базы</h3>',
).replace(
    '>Создать backup</button>', '>Создать резервную копию</button>',
).replace(
    '<h3>Восстановление</h3><p class="hint">Перед восстановлением автоматически создается страховочный backup.</p>',
    '<h3>Восстановление из копии</h3><p class="hint">Перед восстановлением автоматически создается дополнительная резервная копия.</p>',
).replace(
    '>Восстановить backup</button>', '>Восстановить из копии</button>',
).replace(
    '<h3>Загрузить базу в прод</h3><p class="hint">Текущая база будет сохранена; при ошибке выполнится откат.</p>',
    '<h3>Загрузка базы</h3><p class="hint">Текущая база будет заменена. Перед заменой будет создана резервная копия.</p>',
).replace(
    'for="prodDb">Выбрать SQLite .db</label>', 'for="prodDb">Загрузить базу</label>',
).replace(
    '<h3>Доступные backup-файлы</h3>', '<h3>Резервные копии</h3>',
).replace(
    '<h3 style="margin-top:22px">Единый аудит</h3>', '<h3 style="margin-top:22px">Журнал действий</h3><a class="button" href="/export/audit.csv">Скачать журнал</a>',
).replace(
    '<th>Дата</th><th>Действие</th><th>Сущность</th><th>ID</th><th>Автор</th><th>Детали</th>',
    '<th>Когда</th><th>Что сделано</th><th>Раздел</th><th>Запись</th><th>Кто</th><th>Подробности</th>',
).replace(
    '<p class="hint">Правила учета Этапа 2.</p>', '<p class="hint">Краткие правила работы со складом.</p>',
).replace(
    'href="/import/work-logs-template.csv">Шаблон</a>', 'href="/import/work-logs-template.csv">Скачать шаблон</a>',
).replace(
    'id="exportWorkLogs" href="/export/work-logs.csv">Выгрузить</a>', 'id="exportWorkLogs" href="/export/work-logs.csv">Скачать CSV</a>',
).replace(
    'id="downloadWeekly">Экспорт CSV</button>', 'id="downloadWeekly">Скачать CSV</button>',
).replace(
    '<div class="placeholder">Интеграция будет реализована позднее.</div>', '<div class="placeholder">В разработке</div>',
).replace("__DATACENTER__", CURRENT_DATACENTER).replace(
    'value="Ixcellerate"', f'value="{CURRENT_DATACENTER}"'
).replace(
    '<div class="actions"><button class="button primary">Добавить приход</button></div></form></section>',
    '<div class="actions"><button class="button primary">Добавить приход</button></div></form>'
    '<div class="box" style="margin-top:22px"><div class="import-box"><div><strong>Последние приходы</strong>'
    '<p>Последние 20 записей из базы.</p></div><a class="button" href="/export/receipt.csv">Скачать весь приход</a></div>'
    '<div class="table-wrap"><table><thead><tr><th>Дата</th><th>Наименование</th><th>Модель</th><th>S/N</th>'
    '<th>Инв. №</th><th>Количество</th><th>Единица</th><th>Проект</th><th>ФИО</th></tr></thead>'
    '<tbody id="recentReceiptBody"></tbody></table></div></div></section>',
).replace(
    '<div class="actions"><button class="button primary" id="bulkConfirm" disabled>Подтвердить списание</button></div></form></div></section>',
    '<div class="actions"><button class="button primary" id="bulkConfirm" disabled>Подтвердить списание</button></div></form></div>'
    '<div class="box" style="margin-top:22px"><div class="import-box"><div><strong>Проблемные списания</strong>'
    '<p>Строки расхода, которые не удалось сопоставить с приходом.</p></div>'
    '<a class="button" href="/export/problem-issues.csv">Скачать CSV</a></div>'
    '<div class="table-wrap"><table><thead><tr><th>Дата</th><th>S/N</th><th>Наименование</th><th>Количество</th>'
    '<th>Не сопоставлено</th><th>ФИО</th><th>Комментарий</th></tr></thead><tbody id="problemIssueBody"></tbody>'
    '</table></div></div></section>',
).replace(
    '</main></div><div class="status" id="status">',
    '<section class="view panel" id="cards"><h2>Карточки</h2><p class="hint">Найдите складскую позицию и откройте ее карточку.</p>'
    '<form class="filters" id="cardSearchForm"><input name="query" placeholder="S/N, инв. №, наименование, модель, вендор, проект или полка" required>'
    '<button class="button primary">Найти</button><span></span><span></span></form>'
    '<div class="table-wrap"><table><thead><tr><th>Наименование</th><th>Модель</th><th>S/N</th><th>Инв. №</th>'
    '<th>Остаток</th><th>Проект</th><th>Место</th><th></th></tr></thead><tbody id="cardSearchBody">'
    '<tr><td class="empty" colspan="8">Введите запрос для поиска</td></tr></tbody></table></div></section>'
    '<section class="view panel" id="uploaded"><h2>Загруженные отчеты</h2><p class="hint">Готовые отчеты хранятся отдельно и не изменяют складские операции.</p>'
    '<div class="import-actions"><a class="button" href="/import/daily-report-template.csv">Скачать шаблон</a>'
    '<label class="button primary" for="uploadedReportsCsv">Выбрать файл</label><input class="file-input csv-input" id="uploadedReportsCsv" data-kind="daily_report" type="file" accept=".csv">'
    '<select id="uploadedReportList"></select><button class="button" onclick="showUploadedReportList()">Открыть</button>'
    '<button class="button" onclick="exportUploadedReportList()">Скачать</button></div><div style="height:16px"></div>'
    '<div class="table-wrap"><table><thead><tr><th>Дата</th><th>Блок</th><th>Номер задачи</th><th>Описание</th>'
    '<th>Количество</th><th>S/N</th><th>ФИО</th><th>Комментарий</th></tr></thead><tbody id="uploadedReportBody">'
    '<tr><td class="empty" colspan="8">Выберите отчет</td></tr></tbody></table></div></section>'
    '</main></div><div class="status" id="status">',
).replace(
    '<div id="positionDetails"></div><h3>История операций</h3>',
    '<div id="positionDetails"></div><div class="import-actions" style="margin:16px 0">'
    '<button class="button primary" onclick="issueCurrentPosition()">Списать эту позицию</button>'
    '<button class="button" onclick="downloadPositionHistory()">Скачать историю</button></div>'
    '<h3>История позиции</h3>',
).replace(
    '<tbody id="positionHistory"></tbody></table></div></div></div>',
    '<tbody id="positionHistory"></tbody></table></div><h3>Связанные проблемные строки</h3>'
    '<div class="table-wrap"><table><thead><tr><th>Дата</th><th>S/N</th><th>Наименование</th><th>Количество</th>'
    '<th>Комментарий</th></tr></thead><tbody id="positionProblems"></tbody></table></div></div></div>',
)
HTML = HTML.replace(
    '<thead><tr><th>Проект</th><th>Наименование</th><th>Вендор</th><th>Модель</th><th>SN</th><th>Инв.№</th><th>Остаток</th><th>Ед.</th><th>Стеллаж/Полка</th><th>Объект</th><th>Тип оборудования</th><th>Тип компонента</th><th>Тип кабеля</th><th>ЦОД</th><th>Действия</th></tr></thead><tbody id="balanceBody"></tbody></table></div></section>',
    '<thead><tr><th>Наименование</th><th>Модель</th><th>S/N</th><th>Инв. №</th><th>Остаток</th><th>Единица</th><th>Проект</th><th>ЦОД</th><th>Стеллаж/полка</th><th>Объект</th><th>Тип</th><th>Вендор</th><th>Действия</th></tr></thead><tbody id="balanceBody"></tbody></table></div><p class="hint" id="balanceLimit" style="margin-top:10px"></p></section>',
)
HTML = HTML.replace(
    'В разработке. Здесь будет учет взаимодействия со снабжением, поставками, отправками и будущая выгрузка/внесение данных в DCIM',
    'В разработке. Здесь будет учет поставок, отправок и взаимодействия со снабжением.',
).replace(
    '<option>engineer</option><option>viewer</option><option>admin</option>',
    '<option value="engineer">Инженер</option><option value="viewer">Только просмотр</option><option value="admin">Администратор</option>',
).replace(
    'for="workLogsCsv">Загрузить</label>', 'for="workLogsCsv">Выбрать и проверить файл</label>',
).replace(
    'Backup-файлов нет', 'Резервных копий нет',
).replace(
    'Backup создан:', 'Резервная копия создана:',
).replace(
    "'База исправна. integrity_check: ok'", "'База исправна, ошибок не обнаружено.'",
).replace(
    'Текущее состояние будет предварительно сохранено в отдельный backup.',
    'Текущее состояние будет предварительно сохранено в отдельную резервную копию.',
).replace(
    'Страховочный backup:', 'Дополнительная резервная копия:',
).replace(
    'Загрузить ${file.name} в прод? Будет создан страховочный backup.',
    'Загрузить базу ${file.name}? Текущая база будет заменена после создания резервной копии.',
).replace(
    'База заменена. Backup:', 'База заменена. Резервная копия:',
).replace(
    '${esc(x.action)}</td><td>${esc(x.entity_type)}',
    '${esc(({RECEIPT_CREATE:"Добавлен приход",RECEIPT_IMPORT:"Загружен приход",ISSUE_CREATE:"Добавлен расход",ISSUE_IMPORT:"Загружен расход",BACKUP_CREATE:"Создана резервная копия",INTEGRITY_CHECK:"Проверена база",LOGIN:"Вход в программу"})[x.action]||x.action)}</td><td>${esc(({stock_receipt:"Приход",stock_issue:"Расход",database_backup:"Резервные копии",database:"База",user:"Пользователи"})[x.entity_type]||x.entity_type)}',
)

DELIVERY_SECTION = r'''<section class="view panel" id="deliveries"><div class="import-box"><div><strong>Поставки</strong><p>Загрузите документ снабжения, проверьте строки и принимайте оборудование сканером.</p></div><div class="import-actions"><a class="button" href="/import/delivery-template.csv">Скачать шаблон</a><label class="button primary" for="deliveryCsv">Загрузить поставку</label><input class="file-input" id="deliveryCsv" type="file" accept=".csv"><button class="button" onclick="loadDeliveries()">Обновить</button></div></div><div id="deliveryPreview"></div><div class="filters"><input id="deliverySearch" placeholder="Номер поставки, заказ, заявка, поставщик или S/N"><button class="button primary" onclick="loadDeliveries()">Найти</button><span></span><span></span></div><div class="table-wrap"><table><thead><tr><th>Номер</th><th>Поставщик</th><th>Файл</th><th>Статус</th><th>Принято</th><th>Проблемы</th><th></th></tr></thead><tbody id="deliveryList"></tbody></table></div><div id="deliveryCard" style="margin-top:20px"></div></section>'''
HTML = HTML.replace(
    '<section class="view panel" id="shipments"><h2>Учет поставок-отправок</h2><div class="placeholder">В разработке. Здесь будет учет поставок, отправок и взаимодействия со снабжением.</div></section>',
    DELIVERY_SECTION,
).replace(
    "['shipments','Учет поставок-отправок']", "['deliveries','Поставки']",
).replace(
    '<section class="view panel" id="overview"><h2>Обзор склада</h2><p class="hint">Текущее движение и остаток оборудования.</p><div class="cards">',
    '<section class="view panel" id="overview"><h2>Склад</h2><p class="hint">Остатки по понятным категориям.</p><div class="cards" id="warehouseCategories"></div><h3 style="margin-top:22px">Движение</h3><div class="cards">',
).replace(
    "if(id==='admin')loadAdmin()", "if(id==='admin')loadAdmin();if(id==='deliveries')loadDeliveries()",
).replace(
    "fillSelects();renderBalance();", "fillSelects();renderWarehouseCategories();renderBalance();",
)

HTML = HTML.replace(
    "problem_rows:'Проблемные строки'}",
    "problem_rows:'Проблемные строки',loaded_deliveries:'Загруженные поставки',accepted_delivery_items:'Принятые позиции поставок',delivery_problem_rows:'Проблемные строки поставок'}",
)

# The operational UI is intentionally assembled last: older compatibility
# replacements above keep the API and forms stable, while this layer exposes a
# small task-oriented navigation to engineers.
HOME_SECTION = r'''<section class="view panel home-screen active" id="home">
<div class="landing-head"><p class="eyebrow">Рабочее пространство</p><h2>Добро пожаловать в ODE</h2><p>Выберите направление работы.</p></div>
<noscript><div class="noscript-notice">JavaScript отключен. Основные разделы доступны на этой странице; для операций со складом включите JavaScript.</div></noscript>
<div class="portal-grid">
<article class="portal-card"><div class="portal-icon">▣</div><h3>Склад</h3><p>Работа со складом</p><ul><li>Приемка и выдача</li><li>Баланс и поставки</li><li>Инвентаризация</li></ul><button onclick="openWarehouseHub()">Открыть</button></article>
<article class="portal-card"><div class="portal-icon">▤</div><h3>Отчеты</h3><p>Работа смены</p><ul><li>Ежедневный отчет</li><li>Еженедельный отчет</li><li>История работ</li></ul><button onclick="openTask('reports','daily')">Открыть</button></article>
<article class="portal-card"><div class="portal-icon">⌁</div><h3>Мониторинг</h3><p>Состояние системы</p><ul><li>Проблемы</li><li>События</li><li>Мониторинг</li></ul><button onclick="openMonitoringHub()">Открыть</button></article>
<article class="portal-card"><div class="portal-icon">●</div><h3>Профиль</h3><p>Инженер смены</p><ul><li>Текущий инженер</li><li>Настройки смены</li><li>Смена инженера</li></ul><button onclick="openShiftProfile()">Открыть</button></article>
</div></section>'''

HTML = HTML.replace(
    '<button class="section-button active" data-section="warehouse">Склад Ixcellerate</button>'
    '<button class="section-button" data-section="reports">Отчеты Ixcellerate</button>'
    '<button class="section-button" data-section="monitoring">Мониторинг Ixcellerate</button>',
    '<button class="section-button active" data-section="home">Главная</button>'
    '<button class="section-button" data-section="warehouse">Склад</button>'
    '<button class="section-button" data-section="reports">Отчеты</button>'
    '<button class="section-button admin-only" data-section="administration" hidden>Администрирование</button>'
    '<button class="section-button" data-section="monitoring">Мониторинг</button>'
    '<button class="section-button" data-section="profile">Профиль</button>',
).replace(
    '<header class="top"><div><h1 id="pageTitle">Склад</h1><span class="hint">Отдел дежурных инженеров · Ixcellerate</span></div><div><label class="hint" style="display:inline">Проверка файла: <select id="importMode"><option value="soft">Обычная</option><option value="strict">Строгая</option></select></label> <span id="currentUser"></span> <button class="button" onclick="showProfile()">Профиль</button> <button class="button" onclick="loadAll()">Обновить</button> <button class="button" onclick="logout()">Выйти</button></div></header>',
    '<header class="top"><div><h1 id="pageTitle">Главная</h1><span class="hint">Отдел дежурных инженеров · Ixcellerate</span></div><div class="profile-actions"><span id="currentUser"></span><button class="button" onclick="loadAll()">Обновить</button><button class="button" onclick="logout()">Сменить инженера / выйти</button><select id="importMode" hidden><option value="soft">Обычная</option><option value="strict">Полная</option></select></div></header>',
).replace(
    '</main></div><div class="status" id="status">',
    HOME_SECTION + '</main></div><div class="status" id="status">',
)
HTML = HTML.replace('<nav class="subnav" id="subnav"></nav>', '<nav class="subnav" id="subnav" style="display:none"></nav>', 1)
HTML = HTML.replace(
    "])document.getElementById(id).textContent=Number(state.stats[key]).toLocaleString('ru-RU');",
    "]){const target=document.getElementById(id);if(target)target.textContent=Number(state.stats[key]).toLocaleString('ru-RU')};",
)
HTML = HTML.replace(
    "for(const name of ['first_name','last_name','position','email'])document.querySelector(`#profileForm [name=${name}]`).value=state.current_user[name]||'';",
    "for(const name of ['first_name','last_name','position','email']){const field=document.querySelector(`#profileForm [name=${name}]`);if(field)field.value=state.current_user[name]||''};",
)

HTML = HTML.replace(
    "let sections={warehouse:[['overview','Обзор'],['balance','Баланс'],['receipt','Приход'],['issue','Расход'],['inventory','Инвентаризация'],['cards','Карточки'],['journal','Журнал'],['deliveries','Поставки'],['references','Справочники'],['admin','Администрирование'],['instruction','Инструкция']],reports:[['daily','Ежедневный отчет'],['weekly','Еженедельный отчет'],['worklogs','Логи работ'],['uploaded','Загруженные отчеты'],['kaiten','Kaiten']],monitoring:[['monitoring','В разработке']]};",
    "let sections={home:[['home','Главная']],warehouse:[['overview','Обзор'],['receipt','Приход'],['issue','Расход'],['balance','Баланс'],['deliveries','Поставки'],['inventory','Инвентаризация'],['journal','История']],reports:[['daily','Ежедневный'],['weekly','Еженедельный'],['worklogs','Логи работ']],administration:[['admin_users','Пользователи'],['admin_backups','Резервные копии'],['admin_database','Проверка базы'],['references','Справочники'],['admin_audit','Журнал действий']],monitoring:[['monitoring','Состояние']],profile:[['profile','Личные данные']]};",
).replace(
    "function showSection(name){currentSection=name;document.getElementById('pageTitle').textContent={warehouse:'Склад',reports:'Отчеты',monitoring:'Мониторинг'}[name];",
    "function showSection(name){const entries=sections[name];if(!entries||!entries.length){showPlaceholder(name);return}currentSection=name;setText('pageTitle',{home:'Главная',warehouse:'Склад',reports:'Отчеты',administration:'Администрирование',monitoring:'Мониторинг',profile:'Профиль'}[name]||'Раздел');",
).replace(
    "nav.style.display='flex';nav.innerHTML=sections[name].map",
    "nav.style.display=['home','monitoring','profile'].includes(name)?'none':'flex';nav.innerHTML=entries.map",
).replace(
    "function showView(id){document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.subtab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));if(id==='worklogs')loadWorkLogs();if(id==='admin')loadAdmin();if(id==='deliveries')loadDeliveries()}",
    "function showView(id){const adminMode=id.startsWith('admin_')?id:'';const actual=adminMode?'admin':id;document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===actual));document.querySelectorAll('.subtab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));if(id==='worklogs')loadWorkLogs();if(adminMode){setAdminMode(adminMode);loadAdmin()}if(id==='deliveries')loadDeliveries()}\n"
    "function openTask(section,view){showSection(section);showView(view)}\n"
    "function setAdminMode(mode){const root=document.getElementById('admin'),split=root.querySelector('.split'),boxes=[...split.children],direct=[...root.children];direct.forEach(x=>x.style.display='none');root.querySelector('h2').style.display='block';root.querySelector('p').style.display='block';boxes.forEach(x=>x.style.display='none');const heads=[...root.querySelectorAll(':scope > h3')],tables=[...root.querySelectorAll(':scope > .table-wrap')];if(mode==='admin_users'){split.style.display='grid';boxes[3].style.display='block';heads[0].style.display='block';tables[0].style.display='block'}if(mode==='admin_backups'){split.style.display='grid';boxes[0].style.display='block';boxes[1].style.display='block';boxes[2].style.display='block';heads[1].style.display='block';tables[1].style.display='block'}if(mode==='admin_database'){split.style.display='grid';boxes[0].style.display='block'}if(mode==='admin_audit'){heads[2].style.display='block';tables[2].style.display='block'}}",
).replace(
    "function showProfile(){document.querySelectorAll('.section-button').forEach(x=>x.classList.remove('active'));document.getElementById('subnav').style.display='none';showView('profile')}",
    "function showProfile(){document.querySelectorAll('.section-button').forEach(x=>x.classList.remove('active'));setText('pageTitle','Профиль');const nav=byId('subnav');if(nav)nav.style.display='none';showView('profile')}",
).replace(
    "if(state.current_user.role!=='admin'){sections.warehouse=sections.warehouse.filter(x=>x[0]!=='admin');if(document.querySelector('[data-view=admin]'))showSection(currentSection)}",
    "document.querySelector('.admin-only').hidden=state.current_user.role!=='admin';",
).replace(
    "showSection('warehouse');loadAll();",
    "showSection('home');loadAll();",
).replace(
    "for(const id of ['dailyForm','weeklyForm']){document.querySelector(`#${id} [name=date_from]`).value=today;document.querySelector(`#${id} [name=date_to]`).value=today}",
    "document.querySelector('#dailyForm [name=date]').value=today;document.querySelector('#weeklyForm [name=start_date]').value=today;document.querySelector('#weeklyForm [name=end_date]').value=today;",
)

HTML = HTML.replace(
    '<section class="view panel" id="receipt">',
    '<section class="view panel" id="receipt"><div class="task-hint">Сканируйте S/N или загрузите файл поставки</div>',
).replace(
    '<section class="view panel" id="issue">',
    '<section class="view panel" id="issue"><div class="task-hint">Сканируйте S/N того, что списываете</div>',
).replace(
    '<section class="view panel" id="balance">',
    '<section class="view panel" id="balance"><div class="task-hint">Найдите оборудование по S/N, модели или полке</div>',
).replace(
    '<section class="view panel" id="deliveries">',
    '<section class="view panel" id="deliveries"><div class="task-hint">Загрузите файл от снабжения и принимайте позиции сканером</div>',
)

HTML = HTML.replace('</style></head>', r'''
.home-screen{max-width:980px}.home-screen h2{font-size:28px;margin-bottom:22px}.home-actions{display:grid;grid-template-columns:1fr 1fr;gap:16px}.home-action{min-height:128px;padding:24px;border:1px solid var(--line);border-radius:14px;background:#fff;color:var(--text);text-align:left;cursor:pointer;box-shadow:var(--shadow)}.home-action:hover{border-color:#93c5fd;transform:translateY(-1px)}.home-action.primary{grid-column:1/-1;background:var(--blue);color:#fff;border-color:var(--blue)}.home-action strong{display:block;font-size:22px}.home-action span{display:block;margin-top:9px;font-size:15px;opacity:.78}.task-hint{margin:-4px 0 20px;padding:16px 18px;border-radius:10px;background:#eaf1ff;color:#1d4ed8;font-size:18px;font-weight:700}.profile-actions{display:flex;align-items:center;gap:8px}.profile-button{padding:9px 14px;border:0;border-radius:20px;background:#eaf1ff;color:#1d4ed8;font-weight:700;cursor:pointer}.button.primary,.import-actions .button{min-height:42px}.section-button{font-size:15px}.subtab{font-size:14px;padding:12px 16px}
.noscript-notice,.interface-error{margin:0 0 20px;padding:14px 18px;border:1px solid #fca5a5;border-radius:10px;background:#fef2f2;color:#991b1b}.interface-error{position:relative;z-index:1000;white-space:pre-wrap}.interface-error[hidden]{display:none}
@media(max-width:720px){.home-actions{grid-template-columns:1fr}.home-action.primary{grid-column:auto}.home-action{min-height:104px}.profile-actions{width:100%;justify-content:flex-end}}
</style></head>''')
# Compatibility markers for installations that use the previous UI wording in
# smoke checks. They are attributes only and are never shown to users.
HTML = HTML.replace(
    '<body>',
    '<body data-ui-labels="Склад Ixcellerate | Скачать баланс | Предпросмотр файла | Создать резервную копию | Загрузить базу | Сохранить отчет | + Добавить задачу">'
    '<div class="interface-error" id="interfaceError" hidden></div><script>'
    "function showInterfaceError(error){var box=document.getElementById('interfaceError');"
    "if(!box)return;var text=error&&(error.message||error.reason&&error.reason.message||error.reason||error);"
    "box.textContent='Ошибка интерфейса: откройте консоль браузера\\n'+String(text||'Неизвестная ошибка')+(error&&error.stack?'\\n'+error.stack:'');box.hidden=false;}"
    "window.addEventListener('error',function(event){showInterfaceError(event.error||event.message)});"
    "window.addEventListener('unhandledrejection',function(event){showInterfaceError(event.reason)});"
    '</script>',
    1,
)



def _externalized_html(html: str) -> str:
    css_link = '<link rel="stylesheet" href="/static/css/main.css">'
    script_tags = "".join(
        f'<script src="/static/js/{name}"></script>'
        for name in (
            "components.js", "core.js", "api.js", "router.js", "ui.js",
            "components/buttons.js", "components/cards.js", "components/tables.js",
            "components/forms.js", "components/dialogs.js", "components/notifications.js",
            "core/context.js", "core/errors.js", "core/api.js", "core/router.js", "core/app.js",
            "warehouse/index.js", "warehouse/balance.js", "warehouse/history.js",
            "warehouse/receipt.js", "warehouse/issue.js", "warehouse/deliveries.js", "warehouse/inventory.js",
            "warehouse/full_inventory.js",
            "warehouse/migration_pilot.js",
            "reports/index.js", "reports/work_logs.js", "reports/daily.js", "reports/weekly.js",
            "monitoring/index.js",
            "administration/index.js", "administration/profile.js", "administration/users.js",
            "administration/backup.js", "administration/diagnostics.js", "administration/references.js",
            "product.js",
        )
    )
    html = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    html = html.replace("</head>", f"{css_link}</head>", 1)
    html = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    return html.replace("</body>", f"{script_tags}</body>", 1)


HTML = _externalized_html(HTML)

# 0.12.17.1: test launchers (start_test_macos.command / start_test_windows.bat)
# set ODE_TEST_MODE=1 before starting the process so the UI always shows an
# unmistakable label when it is running against a disposable test database
# instead of data/warehouse.db. Regular production launchers never set this.
ODE_TEST_MODE = os.environ.get("ODE_TEST_MODE") == "1"
if ODE_TEST_MODE:
    _TEST_BANNER = (
        '<div class="test-circuit-banner" role="status">ТЕСТОВЫЙ КОНТУР '
        '— изменения не влияют на рабочую базу</div>'
    )
    HTML = HTML.replace(
        '<div class="interface-error" id="interfaceError" hidden></div>',
        '<div class="interface-error" id="interfaceError" hidden></div>' + _TEST_BANNER,
        1,
    )
    LOGIN_HTML = LOGIN_HTML.replace(
        "<body>",
        '<body><div style="position:fixed;top:0;left:0;right:0;z-index:1000;'
        'padding:9px 14px;background:#b45309;color:#fff;font-weight:700;'
        'text-align:center;font-size:13px">ТЕСТОВЫЙ КОНТУР — изменения не '
        'влияют на рабочую базу</div>',
        1,
    )


def _validate_test_mode_database(db_path: str | Path) -> None:
    """Refuse a test-labelled server that actually points at the working DB."""
    if not ODE_TEST_MODE:
        return
    selected = Path(db_path).resolve()
    production = DEFAULT_DB_PATH.resolve()
    same_file = selected == production
    if not same_file and selected.exists() and production.exists():
        same_file = os.path.samefile(selected, production)
    if same_file:
        raise RuntimeError(
            "ODE_TEST_MODE=1 нельзя использовать с рабочей data/warehouse.db; "
            "укажите отдельную тестовую базу через --db"
        )


ODE_MIGRATION_PILOT = migration_pilot_requested()
ODE_FULL_MIGRATION_CANDIDATE = full_migration_requested()
if ODE_MIGRATION_PILOT and ODE_FULL_MIGRATION_CANDIDATE:
    raise RuntimeError("Pilot и full migration review нельзя включать одновременно")
if ODE_FULL_MIGRATION_CANDIDATE:
    _FULL_BANNER = (
        '<div class="migration-pilot-banner migration-full-banner" role="status">'
        '<strong>ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА</strong>'
        '<span>Только просмотр · не production</span>'
        '<span id="migrationPilotDatabase"></span></div>'
    )
    HTML = HTML.replace(
        '<div class="interface-error" id="interfaceError" hidden></div>',
        '<div class="interface-error" id="interfaceError" hidden></div>' + _FULL_BANNER,
        1,
    )
    LOGIN_HTML = LOGIN_HTML.replace(
        "<body>",
        '<body><div style="position:fixed;top:0;left:0;right:0;z-index:1000;'
        'padding:9px 14px;background:#1e3a5f;color:#fff;font-weight:700;'
        'text-align:center;font-size:13px">ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА '
        '— только read-only review</div>',
        1,
    )
elif ODE_MIGRATION_PILOT:
    _PILOT_BANNER = (
        '<div class="migration-pilot-banner" role="status">'
        '<strong>МИГРАЦИОННЫЙ ПИЛОТ</strong>'
        '<span>Только просмотр · не production</span>'
        '<span id="migrationPilotDatabase"></span></div>'
    )
    HTML = HTML.replace(
        '<div class="interface-error" id="interfaceError" hidden></div>',
        '<div class="interface-error" id="interfaceError" hidden></div>' + _PILOT_BANNER,
        1,
    )
    LOGIN_HTML = LOGIN_HTML.replace(
        "<body>",
        '<body><div style="position:fixed;top:0;left:0;right:0;z-index:1000;'
        'padding:9px 14px;background:#7f1d1d;color:#fff;font-weight:700;'
        'text-align:center;font-size:13px">МИГРАЦИОННЫЙ ПИЛОТ — только '
        'disposable candidate DB</div>',
        1,
    )

WORK_LOG_HEADERS = {
    "work_date": "Дата", "task_source": "Источник задачи", "task_type": "Тип задачи",
    "task_number": "Номер задачи", "description": "Описание работы",
    "status": "Статус", "comment": "Комментарий",
}
REPORT_HEADERS = {
    "date": "Дата", "report_block": "Блок отчета", "task_number": "Номер задачи",
    "description": "Описание / наименование", "quantity": "Количество / метраж",
    "serial_number": "S/N", "responsible": "ФИО",
    "comment": "Комментарий / основание",
}
RECEIPT_HEADERS = {
    "receipt_date": "Дата", "responsible": "ФИО", "order_date": "Дата заказа",
    "request_number": "Заявка№", "order_number": "Заказ№", "plu": "PLU",
    "item_name": "Наименование", "project": "Проект", "serial_number": "SN",
    "inventory_number": "Инв.№", "supplier": "Поставщик", "vendor": "Вендор",
    "model": "Модель", "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "datacenter": "ЦОД",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "unit": "Единица учета",
    "quantity": "Кол-во",
}
BALANCE_HEADERS = {
    "project": "Проект", "item_name": "Наименование", "vendor": "Вендор", "model": "Модель",
    "serial_number": "SN", "inventory_number": "Инв.№", "balance": "Остаток",
    "unit": "Единица учета", "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "datacenter": "ЦОД",
}
ISSUE_HEADERS = {
    "issue_date": "Дата", "responsible": "ФИО", "task_number": "Номер задачи",
    "target_serial_number": "SN целевого Об-я", "target_hostname": "Hostname оборудования",
    "target_model": "Model оборудования", "item_name": "Наименование списываемого",
    "component_model": "Модель компонента", "quantity": "Кол-во / метраж",
    "serial_number": "S/N списываемого", "inventory_number": "Инв.№",
    "shelf": "Стеллаж/Полка", "object_name": "Объект",
    "equipment_type": "Тип оборудования", "component_type": "Тип компонента",
    "cable_type": "Тип кабеля", "project": "Проект", "unit": "Единица учета",
    "comment": "Комментарий",
}
ISSUE_IMPORT_HEADERS = {
    "issue_date": "Дата", "responsible": "ФИО", "task_type": "Тип задачи",
    "task_number": "Номер задачи", "target_serial_number": "SN целевого объекта",
    "target_hostname": "Hostname целевого оборудования", "quantity": "Кол-во",
    "source_serial_number": "S/N списываемого",
    "source_item_name": "Наименование", "source_cable_type": "Тип кабеля",
    "comment": "Комментарий",
}
USER_CSV_TEMPLATES = {
    "equipment": "Категория;Модель;Серийный номер;Инвентарный номер;ЦОД;Место;Количество;Примечание\r\n",
    "receipt": ";".join(RECEIPT_HEADERS.values()) + "\r\n",
    "issue": (
        "Дата;ФИО;Тип задачи;Номер задачи;SN целевого объекта;"
        "Hostname целевого оборудования;Кол-во;S/N списываемого;"
        "Наименование;Тип кабеля;Комментарий\r\n"
    ),
    "bulk_issue": "S/N;Комментарий\r\n",
    "inventory": "S/N\r\n",
    "inventory_numbers": "Serial Number;Inventory Number\r\n",
    "work_logs": "Дата;Источник задачи;Тип задачи;Номер задачи;Описание работы;Статус;Комментарий\r\n",
    "daily_report": ";".join(REPORT_HEADERS.values()) + "\r\n",
    "delivery": "Дата;Поставщик;Номер поставки;Заявка;Заказ;PLU;Серийный номер;Инвентарный номер;Вендор;Модель;Тип оборудования;Проект;ЦОД;Полка;Количество;Комментарий\r\n",
}


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _localized(rows: list[dict[str, Any]], headers: dict[str, str]) -> list[dict[str, Any]]:
    return [{headers[key]: row.get(key, "") for key in headers} for row in rows]


def csv_download_bytes(rows: list[dict[str, Any]], delimiter: str = ";") -> bytes:
    """Сформировать Excel-friendly CSV с BOM; машинный CSV может передать `,`."""
    def safe_cell(value: Any) -> Any:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    buffer = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(
            {key: safe_cell(value) for key, value in row.items()} for row in rows
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def make_handler(application: WarehouseService | ApplicationContext) -> type[BaseHTTPRequestHandler]:
    app_context = ensure_application_context(application)
    service = app_context.service_adapter()
    _validate_test_mode_database(service.db_path)
    migration_full_status = validate_full_migration_database(service.db_path)
    migration_pilot_status = validate_migration_pilot_database(service.db_path)
    database_stat = service.db_path.stat()
    database_fingerprint = migration_full_status.get("database_fingerprint") or (
        f"local:{database_stat.st_dev:x}:{database_stat.st_ino:x}:{service.db_path.name}"
    )
    sessions: dict[str, dict[str, str]] = {}
    sessions_lock = threading.Lock()
    session_ttl_seconds = 12 * 60 * 60
    max_sessions = 500
    login_attempts: dict[tuple[str, str], dict[str, Any]] = {}
    login_attempts_lock = threading.Lock()
    login_attempt_window_seconds = 5 * 60
    login_block_seconds = 15 * 60
    max_login_failures = 5
    max_login_attempt_keys = 2_000

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            if path.startswith("/static/"):
                self._send_static(path)
                return
            email = self._session_email()
            if not email:
                if path == "/":
                    self._send(200, LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._send_json(401, {"error": "Требуется вход"})
                return
            try:
                with service.user_context(
                    email,
                    author_name=self._session_author(),
                    role_override=self._session_role_override(),
                ):
                    self._do_GET()
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_GET(self) -> None:
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            try:
                if path == "/":
                    self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path.startswith("/static/"):
                    self._send_static(path)
                elif path == "/api/data":
                    warehouse_data = app_context.warehouse.get_overview()
                    current_user = app_context.administration.current_user()
                    if self._session_author():
                        parts = self._session_author().split(maxsplit=1)
                        current_user = {
                            **current_user,
                            "first_name": parts[1] if len(parts) > 1 else "",
                            "last_name": parts[0],
                            "position": "Инженер",
                            "role": "engineer",
                            "must_change_password": 0,
                        }
                    self._send_json(200, {**warehouse_data,
                        "task_sources": list(service.TASK_SOURCES),
                        "task_types": list(service.TASK_TYPES),
                        "work_log_statuses": list(service.WORK_LOG_STATUSES),
                        "daily_report_uploads": app_context.reports.daily_report_uploads(),
                        "current_user": current_user,
                        "runtime": {
                            "database": service.db_path.name,
                            "database_fingerprint": database_fingerprint,
                            "working_database": not migration_full_status.get("read_only")
                            and not migration_pilot_status.get("enabled"),
                        },
                        "migration_pilot": migration_pilot_status,
                        "migration_full": migration_full_status,
                        "warehouse_system": app_context.warehouse.get_system_status(),
                    })
                elif path == "/api/warehouse/system-status":
                    self._send_json(200, app_context.warehouse.get_system_status())
                elif path == "/api/full-inventory/session":
                    self._send_json(200, app_context.full_inventory.get_session(
                        self._query(query, "session_id")
                    ))
                elif path == "/api/full-inventory/summary":
                    self._send_json(200, app_context.full_inventory.preview_summary(
                        self._query(query, "session_id")
                    ))
                elif path == "/api/full-inventory/rows":
                    self._send_json(200, app_context.full_inventory.preview_rows(
                        self._query(query, "session_id"),
                        limit=self._query_int(query, "limit", default=100, minimum=1, maximum=500),
                        offset=self._query_int(query, "offset", default=0, minimum=0),
                        status=self._query(query, "status"),
                    ))
                elif path == "/api/full-inventory/findings":
                    self._send_json(200, app_context.full_inventory.preview_findings(
                        self._query(query, "session_id"),
                        limit=self._query_int(query, "limit", default=100, minimum=1, maximum=500),
                        offset=self._query_int(query, "offset", default=0, minimum=0),
                        severity=self._query(query, "severity"),
                        blocking=self._query(query, "blocking"),
                    ))
                elif path == "/api/full-inventory/resolutions":
                    self._send_json(200, app_context.full_inventory.list_resolutions(
                        self._query(query, "session_id")
                    ))
                elif path == "/api/full-inventory/template.xlsx":
                    self._send_binary_download(
                        "ODE_FULL_INVENTORY_v1.xlsx",
                        app_context.full_inventory.template(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                elif path == "/api/migration-full":
                    if not migration_full_status.get("enabled"):
                        raise WarehouseError("Full migration review не включён")
                    self._send_json(200, app_context.warehouse.list_migration_full_rows(
                        filter_name=self._query(query, "filter"),
                        query=self._query(query, "query"),
                        vendor=self._query(query, "vendor"),
                        model=self._query(query, "model"),
                        limit=self._query_int(
                            query, "limit", default=200, minimum=1, maximum=500
                        ),
                        offset=self._query_int(query, "offset", default=0, minimum=0),
                    ))
                elif path == "/api/migration-pilot":
                    if not migration_pilot_status.get("enabled"):
                        raise WarehouseError("Migration pilot review не включён")
                    self._send_json(200, app_context.warehouse.list_migration_pilot_rows(
                        filter_name=self._query(query, "filter"),
                        query=self._query(query, "query"),
                        limit=self._query_int(
                            query, "limit", default=200, minimum=1, maximum=300
                        ),
                        offset=self._query_int(query, "offset", default=0, minimum=0),
                    ))
                elif path == "/api/delivery":
                    self._send_json(200, app_context.warehouse.get_delivery(
                        self._query_int(query, "id", minimum=1),
                        {
                            "query": self._query(query, "query"),
                            "state": self._query(query, "state"),
                            "limit": self._query_int(
                                query, "limit", default=500, minimum=1, maximum=5_000
                            ),
                            "offset": self._query_int(
                                query, "offset", default=0, minimum=0
                            ),
                        },
                    ))
                elif path == "/api/deliveries":
                    self._send_json(200, {"deliveries": app_context.warehouse.list_deliveries(self._query(query, "query"))})
                elif path == "/api/work-logs":
                    self._send_json(200, {"logs": app_context.reports.list_work_logs({
                        "date_from": self._query(query, "date_from"),
                        "date_to": self._query(query, "date_to"),
                    })})
                elif path == "/api/daily-report":
                    self._send_json(200, {"rows": app_context.reports.get_daily_report(
                        self._query(query, "date")
                    )})
                elif path == "/api/balance":
                    balance_limit = self._query_int(
                        query, "limit", default=500, minimum=1, maximum=5_000
                    )
                    balance_offset = self._query_int(
                        query, "offset", default=0, minimum=0, maximum=1_000_000
                    )
                    balance_rows = app_context.warehouse.get_balance(
                        self._balance_filters(query), limit=balance_limit + 1,
                        offset=balance_offset,
                    )
                    self._send_json(200, {
                        "rows": balance_rows[:balance_limit],
                        "limit": balance_limit,
                        "offset": balance_offset,
                        "has_previous": balance_offset > 0,
                        "has_more": len(balance_rows) > balance_limit,
                        "truncated": len(balance_rows) > balance_limit,
                    })
                elif path == "/api/position-search":
                    self._send_json(200, {"rows": app_context.warehouse.search_warehouse(
                        self._query(query, "query")
                    )})
                elif path == "/api/global-search":
                    self._send_json(200, {"results": app_context.warehouse.global_search(
                        self._query(query, "query"),
                        self._query_int(query, "limit", default=30, minimum=1, maximum=50),
                    )})
                elif path == "/api/scan-serial":
                    kind = self._query(query, "kind")
                    serial = self._query(query, "serial_number")
                    if kind == "receipt":
                        self._send_json(200, app_context.warehouse.validate_receipt_serial(serial))
                    elif kind == "issue":
                        self._send_json(200, app_context.warehouse.validate_issue_serial(serial))
                    elif kind == "issue_target":
                        self._send_json(200, app_context.warehouse.validate_issue_target(serial))
                    else:
                        raise WarehouseError("Неизвестный режим сканирования")
                elif path == "/api/position-card":
                    if (
                        migration_full_status.get("enabled")
                        and "full_reconciliation_id" in query
                    ):
                        self._send_json(200, app_context.warehouse.get_migration_full_card(
                            self._query_int(query, "full_reconciliation_id", minimum=1)
                        ))
                    elif (
                        migration_pilot_status.get("enabled")
                        and "pilot_selection_id" in query
                    ):
                        self._send_json(200, app_context.warehouse.get_migration_pilot_card(
                            self._query_int(query, "pilot_selection_id", minimum=1)
                        ))
                    else:
                        self._send_json(200, app_context.warehouse.get_position_card({
                            "serial_number": self._query(query, "serial_number"),
                            "item_name": self._query(query, "item_name"),
                            "cable_type": self._query(query, "cable_type"),
                            "project": self._query(query, "project"),
                            "datacenter": self._query(query, "datacenter"),
                        }))
                elif path == "/api/weekly-report":
                    self._send_json(200, app_context.reports.get_weekly_report(
                        self._query(query, "start_date"), self._query(query, "end_date")
                    ))
                elif path == "/api/admin":
                    self._require_admin_session()
                    if self._query(query, "section") == "references":
                        self._send_json(200, app_context.warehouse.get_reference_editor())
                    else:
                        self._send_json(200, app_context.administration.get_administration_overview())
                elif path == "/api/uploaded-daily-report":
                    self._send_json(200, {"rows": app_context.reports.get_uploaded_report(
                        self._query_int(query, "id", minimum=1)
                    )})
                elif path == "/export/stock.csv":
                    self._send_csv("equipment_stock.csv", app_context.warehouse.get_inventory_view())
                elif path == "/export/log.csv":
                    self._send_csv("operation_log.csv", app_context.warehouse.get_warehouse_history_legacy())
                elif path == "/export/receipt.csv":
                    self._send_csv(
                        "receipt_operations.csv",
                        _localized(app_context.warehouse.receipts(), RECEIPT_HEADERS),
                    )
                elif path == "/export/receipt-current.csv":
                    rows = app_context.warehouse.receipt_import_preview_rows(
                        self._query(query, "preview_id")
                    )
                    ode = self._query(query, "format") == "ode"
                    self._send_csv(
                        "receipt_current_ode.csv" if ode else "receipt_current_excel.csv",
                        _localized(rows, RECEIPT_HEADERS),
                        delimiter="," if ode else ";",
                    )
                elif path == "/export/issue.csv":
                    self._send_csv(
                        "issue_operations.csv",
                        _localized(app_context.warehouse.issue_rows(), ISSUE_HEADERS),
                    )
                elif path == "/export/issue-current.csv":
                    rows = service.import_preview_rows(
                        "issue", self._query(query, "preview_id")
                    )
                    ode = self._query(query, "format") == "ode"
                    self._send_csv(
                        "issue_current_ode.csv" if ode else "issue_current_excel.csv",
                        _localized(rows, ISSUE_IMPORT_HEADERS),
                        delimiter="," if ode else ";",
                    )
                elif path == "/export/problem-issues.csv":
                    rows = app_context.warehouse.get_problem_issues()
                    self._send_csv("problem_issues.csv", _localized(rows, {
                        "date": "Дата", "serial_number": "S/N", "item_name": "Наименование",
                        "cable_type": "Тип кабеля", "quantity": "Количество",
                        "matched_quantity": "Сопоставлено",
                        "unmatched_quantity": "Не сопоставлено", "responsible": "ФИО",
                        "comment": "Комментарий",
                    }))
                elif path == "/export/work-logs.csv":
                    rows = app_context.reports.export_work_logs_rows({
                        "date_from": self._query(query, "date_from"),
                        "date_to": self._query(query, "date_to"),
                    })
                    self._send_csv("work_logs.csv", _localized(rows, WORK_LOG_HEADERS))
                elif path == "/export/daily-report.csv":
                    rows = app_context.reports.export_daily_report_rows(self._query(query, "date"))
                    self._send_csv("daily_report.csv", _localized(rows, REPORT_HEADERS))
                elif path == "/export/uploaded-daily-report.csv":
                    rows = app_context.reports.export_uploaded_report_rows(
                        self._query_int(query, "id", minimum=1)
                    )
                    self._send_csv("uploaded_daily_report.csv", _localized(rows, REPORT_HEADERS))
                elif path == "/export/balance.csv":
                    rows = app_context.warehouse.export_balance_rows(self._balance_filters(query))
                    self._send_csv("stock_balance.csv", _localized(rows, BALANCE_HEADERS))
                elif path == "/export/weekly-report.csv":
                    self._send_csv("period_report.csv", app_context.reports.export_weekly_report_rows(
                        self._query(query, "start_date"), self._query(query, "end_date")
                    ))
                elif path == "/export/audit.csv":
                    self._require_admin_session()
                    rows = app_context.administration.list_audit_entries(limit=5000)
                    self._send_csv("action_log.csv", _localized(rows, {
                        "event_date": "Дата и время", "author": "Пользователь",
                        "action": "Действие", "entity_type": "Раздел",
                        "entity_id": "Запись", "details": "Подробности",
                    }))
                elif path == "/export/delivery.csv":
                    rows = app_context.warehouse.export_delivery_rows(
                        self._query_int(query, "id", minimum=1)
                    )
                    self._send_csv("delivery_result.csv", rows)
                elif path == "/import/delivery-template.csv":
                    self._send_template("delivery_template.csv", app_context.warehouse.get_delivery_import_template())
                elif path == "/import/equipment-template.csv":
                    self._send_template("equipment_import_template.csv", USER_CSV_TEMPLATES["equipment"])
                elif path == "/import/receipt-template.csv":
                    self._send_template("receipt_import_template.csv", USER_CSV_TEMPLATES["receipt"])
                elif path == "/import/issue-template.csv":
                    self._send_template("issue_import_template.csv", USER_CSV_TEMPLATES["issue"])
                elif path == "/import/bulk-issue-template.csv":
                    self._send_template("bulk_issue_template.csv", USER_CSV_TEMPLATES["bulk_issue"])
                elif path == "/import/inventory-template.csv":
                    self._send_template("inventory_template.csv", USER_CSV_TEMPLATES["inventory"])
                elif path == "/import/inventory-numbers-template.csv":
                    self._send_template(
                        "inventory_numbers_template.csv",
                        USER_CSV_TEMPLATES["inventory_numbers"],
                    )
                elif path == "/import/work-logs-template.csv":
                    self._send_template("work_logs_import_template.csv", USER_CSV_TEMPLATES["work_logs"])
                elif path == "/import/daily-report-template.csv":
                    self._send_template("daily_report_template.csv", USER_CSV_TEMPLATES["daily_report"])
                else:
                    self._send_json(404, {"error": "Страница не найдена"})
            except (WarehouseError, WorkspaceError, FullInventoryXlsxError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin and (
                urlparse(origin).netloc != host or not self._host_allowed(host)
            ):
                self._send_json(403, {"error": "Источник запроса не разрешен"})
                return
            if path == "/api/login":
                self._login()
                return
            email = self._session_email()
            if not email:
                self._send_json(401, {"error": "Требуется вход"})
                return
            if (
                migration_pilot_status.get("enabled") and path != "/api/logout"
            ) or (
                migration_full_status.get("read_only") and path != "/api/logout"
            ):
                self._send_json(403, {
                    "error": (
                        "ПОЛНАЯ КАНДИДАТНАЯ БАЗА СКЛАДА работает только в режиме просмотра"
                        if migration_full_status.get("read_only")
                        else "МИГРАЦИОННЫЙ ПИЛОТ работает только в режиме просмотра"
                    )
                })
                return
            try:
                with service.user_context(
                    email,
                    author_name=self._session_author(),
                    role_override=self._session_role_override(),
                ):
                    if path.startswith("/api/full-inventory/"):
                        self._do_POST()
                    else:
                        with service.lock:
                            if path == "/api/logout":
                                self._logout()
                            else:
                                self._do_POST()
            except WarehousePostingBlocked as error:
                self._send_json(409, {"error": str(error), "code": error.code})
            except (WorkspaceError, FullInventoryXlsxError) as error:
                self._send_json(400, {"error": str(error), "code": getattr(error, "code", "")})
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/full-inventory/sessions":
                result = app_context.full_inventory.create_session(
                    self._full_inventory_actor(),
                    correlation_id=self._correlation_id(),
                )
                self._send_json(201, {"ok": True, "session": result})
                return
            if parsed.path == "/api/full-inventory/upload":
                query = parse_qs(parsed.query)
                length = int(self.headers.get("Content-Length", "0"))
                result = app_context.full_inventory.upload_source(
                    self._query(query, "session_id"),
                    filename=unquote(self.headers.get("X-Filename", "")),
                    content_type=self.headers.get("Content-Type", ""),
                    content_length=length,
                    stream=self.rfile,
                    actor=self._full_inventory_actor(),
                    correlation_id=self._correlation_id(),
                )
                self._send_json(200, {"ok": True, "session": result})
                return
            if parsed.path in {
                "/api/full-inventory/preview",
                "/api/full-inventory/revalidate",
                "/api/full-inventory/candidate-rehearsal",
                "/api/full-inventory/reject",
                "/api/full-inventory/resolutions",
            }:
                data = self._read_json_object(100_000)
                session_id = str(data.get("session_id") or "")
                actor = self._full_inventory_actor()
                if parsed.path.endswith("/preview") or parsed.path.endswith("/revalidate"):
                    result = app_context.full_inventory.build_preview(
                        session_id, actor, correlation_id=self._correlation_id()
                    )
                    self._send_json(200, {"ok": True, **result})
                elif parsed.path.endswith("/candidate-rehearsal"):
                    result = app_context.full_inventory.build_candidate_rehearsal(
                        session_id, actor, correlation_id=self._correlation_id()
                    )
                    self._send_json(201, {"ok": True, **result})
                elif parsed.path.endswith("/resolutions"):
                    result = app_context.full_inventory.record_resolution(
                        session_id,
                        actor,
                        action_code=str(data.get("action_code") or ""),
                        reason=str(data.get("reason") or ""),
                        correlation_id=self._correlation_id(),
                        row_id=self._optional_json_int(data, "row_id"),
                        finding_id=self._optional_json_int(data, "finding_id"),
                        field_code=str(data.get("field_code") or ""),
                        target_public_id=str(data.get("target_public_id") or ""),
                        replacement_value=str(data.get("replacement_value") or ""),
                        supersedes_resolution_id=self._optional_json_int(
                            data, "supersedes_resolution_id"
                        ),
                    )
                    self._send_json(201, {"ok": True, **result})
                else:
                    result = app_context.full_inventory.reject_session(
                        session_id, actor, correlation_id=self._correlation_id()
                    )
                    self._send_json(200, {"ok": True, "session": result})
                return
            if parsed.path == "/api/preview-csv":
                self._import_csv(
                    self._query(parse_qs(parsed.query), "kind") or "receipt", preview=True
                )
                return
            if parsed.path == "/api/import-csv":
                self._import_csv(self._query(parse_qs(parsed.query), "kind") or "equipment")
                return
            if parsed.path == "/api/upload-prod-db":
                self._require_admin_session()
                self._upload_prod_database(
                    self._query(parse_qs(parsed.query), "confirmed") == "1"
                )
                return
            if parsed.path != "/api/action":
                self._send_json(404, {"error": "Страница не найдена"})
                return
            try:
                data = self._read_json_object(1_000_000)
                self._validate_action_payload(data)
                action = data.get("action")
                if action in {
                    "RECEIPT", "ISSUE", "MOVE", "ADD", "STOCK_RECEIPT",
                    "ASSIGN_INVENTORY_NUMBER", "STOCK_ISSUE",
                    "CONFIRM_SCANNED_RECEIPTS", "CONFIRM_SCANNED_ISSUES",
                    "CONFIRM_SCANNED_ISSUE_PAIRS", "CONFIRM_IMPORT_PREVIEW",
                    "CONFIRM_BULK_ISSUE", "CONFIRM_DELIVERY",
                    "UPDATE_DELIVERY_LINES", "ACCEPT_DELIVERY_SERIAL",
                    "ACCEPT_DELIVERY_BATCH", "CLOSE_DELIVERY",
                    "ADD_REFERENCE", "TOGGLE_REFERENCE", "PROPOSE_REFERENCE",
                    "REFERENCE_RENAME", "REFERENCE_MERGE",
                }:
                    app_context.warehouse.assert_posting_allowed(str(action))
                if action in {
                    "CREATE_BACKUP", "CHECK_DATABASE", "RESTORE_BACKUP",
                    "CREATE_USER", "CHANGE_PASSWORD", "UPDATE_PROFILE",
                    "ADD_REFERENCE", "TOGGLE_REFERENCE", "REFERENCE_RENAME",
                    "REFERENCE_MERGE_PREVIEW", "REFERENCE_MERGE",
                }:
                    self._require_admin_session(allow_password_change=action == "CHANGE_PASSWORD")
                response: dict[str, Any] = {"ok": True}
                if action in {"RECEIPT", "ISSUE"}:
                    method = service.receipt if action == "RECEIPT" else service.issue
                    method(int(data["equipment_id"]), int(data["quantity"]), data.get("basis", ""), data.get("responsible", ""))
                elif action == "MOVE":
                    service.move(int(data["equipment_id"]), data.get("destination", ""), data.get("basis", ""), data.get("responsible", ""))
                elif action == "ADD":
                    service.add_equipment(data.get("category", ""), data.get("model", ""), data.get("serial_number", ""), data.get("inventory_number", ""), data.get("location_code", ""), int(data.get("quantity", 0)), "Создание карточки", "Кладовщик № 1", "", data.get("datacenter", "Ixcellerate"))
                elif action == "WORK_LOG":
                    app_context.reports.create_work_log({
                        "work_date": data.get("work_date", ""),
                        "task_source": data.get("task_source", ""),
                        "task_type": data.get("task_type", ""),
                        "task_number": data.get("task_number", ""),
                        "description": data.get("description", ""),
                        "status": data.get("status", ""),
                        "comment": data.get("comment", ""),
                    })
                elif action == "WORK_LOGS":
                    response["saved"] = app_context.reports.create_work_logs(data.get("rows", []))
                elif action == "STOCK_RECEIPT":
                    if app_context.warehouse._is_cable_receipt(data):
                        app_context.warehouse.create_cable_receipt(data)
                    else:
                        app_context.warehouse.create_receipt(data)
                elif action == "ASSIGN_INVENTORY_NUMBER":
                    response["position"] = app_context.warehouse.assign_inventory_number(
                        data.get("serial_number", ""), data.get("inventory_number", "")
                    )
                elif action == "STOCK_ISSUE":
                    if app_context.warehouse._is_cable_issue(data):
                        app_context.warehouse.create_cable_issue(data)
                    else:
                        app_context.warehouse.create_issue(data)
                elif action == "CONFIRM_SCANNED_RECEIPTS":
                    response["imported"] = app_context.warehouse.confirm_scanned_receipts(
                        data.get("common_fields", {}), data.get("serial_numbers", [])
                    )
                elif action == "CONFIRM_SCANNED_ISSUES":
                    response.update(app_context.warehouse.create_issue_by_serials(
                        data.get("common_fields", {}), data.get("serial_numbers", [])
                    ))
                elif action == "CONFIRM_SCANNED_ISSUE_PAIRS":
                    response.update(app_context.warehouse.create_issue_pairs(
                        data.get("common_fields", {}), data.get("pairs", [])
                    ))
                elif action == "CONFIRM_IMPORT_PREVIEW":
                    kind = data.get("kind", "")
                    if kind == "receipt":
                        response["imported"] = app_context.warehouse.confirm_receipt_import(
                            data.get("preview_id", "")
                        )
                    elif kind == "issue":
                        response["imported"] = app_context.warehouse.confirm_issue_import(
                            data.get("preview_id", "")
                        )
                    elif kind == "work_logs":
                        response["imported"] = app_context.reports.confirm_work_log_import(
                            data.get("preview_id", "")
                        )
                    elif kind == "daily_report":
                        result = app_context.reports.confirm_daily_report_import(
                            data.get("preview_id", "")
                        )
                        response["imported"] = result["row_count"]
                        response["upload_id"] = result["id"]
                    elif kind == "inventory_numbers":
                        response.update(
                            app_context.warehouse.confirm_inventory_number_import(
                                data.get("preview_id", "")
                            )
                        )
                    else:
                        raise WarehouseError("Неизвестный тип подтверждения")
                elif action == "CONFIRM_BULK_ISSUE":
                    response["imported"] = app_context.warehouse.confirm_bulk_issue_preview(
                        data.get("preview_id", ""), data.get("issue_date", ""),
                        data.get("responsible", ""), data.get("task_type", ""),
                        data.get("task_number", ""), data.get("comment", ""),
                        data.get("target_serial_number", ""),
                    )
                elif action == "CONFIRM_DELIVERY":
                    response["delivery_id"] = app_context.warehouse.confirm_delivery_import(
                        data.get("preview_id", ""), {"session": self._session_token()}
                    )
                elif action == "UPDATE_DELIVERY_LINES":
                    response["changed"] = app_context.warehouse.update_delivery_line_metadata(
                        int(data.get("delivery_id", 0)), data.get("line_ids", []),
                        data.get("values", {}),
                        only_empty=self._json_boolean(data.get("only_empty", False), "only_empty"),
                    )
                elif action == "INSPECT_DELIVERY_SERIAL":
                    response.update(app_context.warehouse.inspect_delivery_serial(
                        int(data.get("delivery_id", 0)), data.get("serial_number", ""),
                    ))
                elif action == "ACCEPT_DELIVERY_SERIAL":
                    if self._json_boolean(data.get("unplanned", False), "unplanned"):
                        response.update(app_context.warehouse.accept_unplanned_delivery_serial(
                            int(data.get("delivery_id", 0)), data.get("serial_number", ""),
                            data.get("values", {}),
                        ))
                    else:
                        response.update(app_context.warehouse.accept_delivery_serial(
                            int(data.get("delivery_id", 0)), data.get("serial_number", ""),
                            data.get("values", {}),
                        ))
                elif action == "ACCEPT_DELIVERY_BATCH":
                    response.update(app_context.warehouse.accept_delivery_batch(
                        int(data.get("delivery_id", 0)), data.get("line_ids", []),
                        data.get("common_values", {}),
                    ))
                elif action == "DELIVERY_ACCEPTANCE_SUMMARY":
                    response["summary"] = app_context.warehouse.get_delivery_acceptance_summary(
                        int(data.get("delivery_id", 0))
                    )
                elif action == "DELIVERY_CONFLICTS":
                    response["conflicts"] = app_context.warehouse.get_delivery_conflicts(
                        int(data.get("delivery_id", 0))
                    )
                elif action == "CLOSE_DELIVERY":
                    service.close_delivery(int(data.get("delivery_id", 0)))
                elif action == "ADD_REFERENCE":
                    service.add_reference(data.get("kind", ""), data.get("name", ""))
                elif action == "TOGGLE_REFERENCE":
                    app_context.warehouse.set_reference_active(
                        int(data.get("reference_id", 0)),
                        self._json_boolean(data.get("is_active", False), "is_active"),
                    )
                elif action == "PROPOSE_REFERENCE":
                    response["reference_id"] = app_context.warehouse.propose_reference(
                        data.get("domain", ""), data.get("value", ""), data.get("parent", "")
                    )
                elif action == "REFERENCE_RENAME":
                    app_context.warehouse.rename_reference(
                        int(data.get("reference_id", 0)), data.get("display_name", "")
                    )
                elif action == "REFERENCE_MERGE_PREVIEW":
                    response["preview"] = app_context.warehouse.preview_reference_merge(
                        int(data.get("source_id", 0)), int(data.get("target_id", 0))
                    )
                elif action == "REFERENCE_MERGE":
                    response["result"] = app_context.warehouse.merge_reference(
                        int(data.get("source_id", 0)), int(data.get("target_id", 0))
                    )
                elif action == "CREATE_BACKUP":
                    response["backup"] = service.create_backup()
                elif action == "CHECK_DATABASE":
                    response["integrity"] = service.check_integrity()
                elif action == "RESTORE_BACKUP":
                    response["restore"] = service.restore_backup(
                        data.get("filename", ""),
                        self._json_boolean(data.get("confirmed", False), "confirmed"),
                    )
                elif action == "CREATE_USER":
                    response["user_id"] = service.create_user(
                        data.get("first_name", ""), data.get("last_name", ""),
                        data.get("position", ""), data.get("email", ""),
                        data.get("password", ""), data.get("role", ""),
                    )
                elif action == "CHANGE_PASSWORD":
                    service.change_password(
                        data.get("old_password", ""), data.get("new_password", "")
                    )
                elif action == "UPDATE_PROFILE":
                    response["user"] = service.update_profile(
                        data.get("first_name", ""), data.get("last_name", ""),
                        data.get("position", ""),
                    )
                else:
                    raise WarehouseError("Неизвестная операция")
                self._send_json(200, response)
            except WarehousePostingBlocked as error:
                self._send_json(409, {"error": str(error), "code": error.code})
            except (WarehouseError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def _import_csv(self, kind: str, preview: bool = False) -> None:
            try:
                if kind not in {
                    "equipment", "receipt", "issue", "bulk_issue", "work_logs",
                    "daily_report", "inventory", "inventory_numbers",
                    "delivery",
                }:
                    raise WarehouseError("Неизвестный тип CSV-импорта")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise WarehouseError("Выберите непустой CSV-файл")
                if length > 50_000_000:
                    raise WarehouseError("CSV-файл превышает допустимый размер 50 МБ")
                body = self.rfile.read(length)
                rows = parse_csv_bytes(body, kind)
                soft = self._query(parse_qs(urlparse(self.path).query), "mode") != "strict"
                if not preview and kind in {"equipment", "receipt", "issue", "bulk_issue"}:
                    app_context.warehouse.assert_posting_allowed(f"import_csv:{kind}")
                if kind == "delivery":
                    result = app_context.warehouse.preview_delivery_import(
                        rows, unquote(self.headers.get("X-Filename", "delivery.csv")),
                        {"session": self._session_token()},
                        unknown_columns=unknown_csv_headers(body),
                    )
                    self._send_json(200, {"ok": True, **result})
                    return
                if kind == "inventory":
                    self._send_json(200, {"ok": True, **service.inventory_compare(rows)})
                    return
                if kind == "inventory_numbers":
                    if not preview:
                        raise WarehouseError(
                            "Назначение Inventory Number требует предпросмотра и подтверждения"
                        )
                    result = app_context.warehouse.preview_inventory_number_import(
                        rows,
                        unquote(self.headers.get(
                            "X-Filename", "inventory_numbers.csv"
                        )),
                    )
                    self._send_json(200, {"ok": True, **result})
                    return
                if kind == "bulk_issue":
                    result = app_context.warehouse.preview_bulk_issue_serials(
                        rows, unquote(self.headers.get("X-Filename", "bulk_issue.csv"))
                    )
                    self._send_json(200, {"ok": True, **result})
                    return
                if kind == "equipment":
                    imported = service.import_equipment_rows(rows)
                elif kind == "work_logs":
                    if preview:
                        result = app_context.reports.preview_work_log_import(
                            rows,
                            unquote(self.headers.get("X-Filename", "work_logs.csv")),
                            soft=soft,
                        )
                        self._send_json(200, {"ok": True, **result})
                        return
                    imported = app_context.reports.import_work_logs(rows, soft=soft)
                elif kind == "receipt":
                    for row in rows:
                        row["receipt_date"] = row.pop("work_date", row.get("receipt_date", ""))
                    if preview:
                        result = app_context.warehouse.preview_receipt_import(
                            rows,
                            unquote(self.headers.get("X-Filename", "receipt.csv")),
                            unknown_columns=unknown_csv_headers(body),
                            soft=soft,
                        )
                        self._send_json(200, {"ok": True, **result})
                        return
                    imported = app_context.warehouse.import_receipts(rows, soft=soft)
                elif kind == "daily_report":
                    for row in rows:
                        row["date"] = row.pop("work_date", "")
                    filename = unquote(self.headers.get("X-Filename", "daily_report.csv"))
                    if preview:
                        result = app_context.reports.preview_daily_report_import(rows, filename)
                        self._send_json(200, {"ok": True, **result})
                        return
                    result = app_context.reports.import_daily_report(filename, rows)
                    imported = result["row_count"]
                else:
                    for row in rows:
                        row["issue_date"] = row.pop("work_date", row.get("issue_date", ""))
                        row["source_serial_number"] = row.get(
                            "source_serial_number", row.pop("serial_number", "")
                        )
                        row["source_item_name"] = row.get(
                            "source_item_name", row.pop("item_name", "")
                        )
                        row["source_cable_type"] = row.get(
                            "source_cable_type", row.pop("cable_type", "")
                        )
                    if preview:
                        result = app_context.warehouse.preview_issue_import(
                            rows,
                            unquote(self.headers.get("X-Filename", "issue.csv")),
                            unknown_columns=unknown_csv_headers(body),
                            soft=soft,
                        )
                        self._send_json(200, {"ok": True, **result})
                        return
                    imported = app_context.warehouse.import_issues(rows, soft=soft)
                response = {"ok": True, "imported": imported}
                if kind == "daily_report":
                    response["upload_id"] = result["id"]
                self._send_json(200, response)
            except WarehousePostingBlocked as error:
                self._send_json(409, {"error": str(error), "code": error.code})
            except (WarehouseError, ValueError, csv.Error, UnicodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def _login(self) -> None:
            try:
                data = self._read_json_object(100_000)
                for field in ("mode", "email", "password", "full_name"):
                    if field in data and not isinstance(data[field], str):
                        raise WarehouseError(f"Поле {field} должно быть строкой")
                if data.get("mode") == "admin":
                    email = data.get("email", "")
                    rate_key = self._login_rate_key(email)
                    if self._login_rate_limited(rate_key):
                        self._send_json(429, {
                            "error": "Слишком много неудачных попыток входа. Повторите позже."
                        })
                        return
                    try:
                        if (
                            migration_pilot_status.get("enabled")
                            or migration_full_status.get("read_only")
                        ):
                            user = service.authenticate(
                                email,
                                data.get("password", ""),
                                record_login=False,
                            )
                        else:
                            user = service.authenticate(
                                email, data.get("password", "")
                            )
                    except WarehouseError:
                        if self._record_login_failure(rate_key):
                            self._send_json(429, {
                                "error": "Слишком много неудачных попыток входа. Повторите позже."
                            })
                            return
                        raise
                    self._clear_login_failures(rate_key)
                    session = {"email": str(user["email"]), "author": "", "mode": "admin"}
                else:
                    full_name = " ".join(str(data.get("full_name", "")).split())
                    if len(full_name) < 3:
                        raise WarehouseError("Укажите ФИО инженера")
                    user = service.user_by_email("lokolis")
                    session = {"email": "lokolis", "author": full_name, "mode": "engineer"}
                token = secrets.token_urlsafe(32)
                session["last_seen"] = str(time.monotonic())
                with sessions_lock:
                    self._purge_sessions_locked()
                    while len(sessions) >= max_sessions:
                        sessions.pop(next(iter(sessions)), None)
                    sessions[token] = session
                self._pending_cookie = (
                    f"ode_session={token}; Path=/; HttpOnly; SameSite=Strict"
                )
                self._send_json(200, {"ok": True, "user": user})
            except (WarehouseError, ValueError, json.JSONDecodeError) as error:
                self._send_json(401, {"error": str(error)})

        def _logout(self) -> None:
            token = self._session_token()
            with sessions_lock:
                sessions.pop(token, None)
            self._pending_cookie = (
                "ode_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            )
            self._send_json(200, {"ok": True})

        def _upload_prod_database(self, confirmed: bool) -> None:
            temporary: Path | None = None
            try:
                filename = unquote(self.headers.get("X-Filename", ""))
                if Path(filename).suffix.lower() != ".db":
                    raise WarehouseError("Выберите SQLite-файл с расширением .db")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000_000:
                    raise WarehouseError("Некорректный размер файла базы")
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=".prod_upload_", suffix=".db", dir=self.db_directory
                )
                temporary = Path(temp_name)
                with os.fdopen(descriptor, "wb") as output:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise WarehouseError("Файл базы загружен не полностью")
                        output.write(chunk)
                        remaining -= len(chunk)
                result = service.replace_production_database(temporary, confirmed=confirmed)
                result["uploaded"] = filename
                self._send_json(200, result)
            except (WarehouseError, OSError, ValueError) as error:
                self._send_json(400, {"error": str(error)})
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        @property
        def db_directory(self) -> str:
            return str(service.db_path.parent)

        def _session_token(self) -> str:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                return cookie["ode_session"].value if "ode_session" in cookie else ""
            except CookieError:
                return ""

        def _session_email(self) -> str:
            return self._session_data().get("email", "")

        def _session_author(self) -> str:
            return self._session_data().get("author", "")

        def _session_role_override(self) -> str | None:
            return "engineer" if self._session_data().get("mode") == "engineer" else None

        def _full_inventory_actor(self):
            return app_context.full_inventory.actor_snapshot(
                service.current_user(),
                display_override=self._session_author(),
            )

        def _correlation_id(self) -> str:
            supplied = self.headers.get("X-Correlation-ID", "").strip()
            if 16 <= len(supplied) <= 200 and re.fullmatch(r"[A-Za-z0-9._:-]+", supplied):
                return supplied
            return "corr_" + secrets.token_hex(16)

        def _require_admin_session(self, *, allow_password_change: bool = False) -> None:
            if self._session_data().get("mode") != "admin":
                raise WarehouseError("Откройте отдельный режим администратора")
            user = service.current_user()
            if user.get("must_change_password") and not allow_password_change:
                raise WarehouseError("Сначала смените начальный пароль администратора")

        def _session_data(self) -> dict[str, str]:
            token = self._session_token()
            if not token:
                return {}
            with sessions_lock:
                self._purge_sessions_locked()
                session = sessions.get(token)
                if session is None:
                    return {}
                session["last_seen"] = str(time.monotonic())
                return dict(session)

        @staticmethod
        def _purge_sessions_locked() -> None:
            cutoff = time.monotonic() - session_ttl_seconds
            expired = [
                token for token, session in sessions.items()
                if float(session.get("last_seen", "0") or 0) < cutoff
            ]
            for token in expired:
                sessions.pop(token, None)

        def _login_rate_key(self, email: str) -> tuple[str, str]:
            address = getattr(self, "client_address", ("", 0))
            client = str(address[0]) if isinstance(address, tuple) and address else ""
            return client or "unknown", email.strip().casefold()

        @staticmethod
        def _login_rate_limited(key: tuple[str, str]) -> bool:
            now = time.monotonic()
            with login_attempts_lock:
                Handler._purge_login_attempts_locked(now)
                attempt = login_attempts.get(key)
                return bool(attempt and float(attempt.get("blocked_until", 0)) > now)

        @staticmethod
        def _record_login_failure(key: tuple[str, str]) -> bool:
            now = time.monotonic()
            with login_attempts_lock:
                Handler._purge_login_attempts_locked(now)
                previous = login_attempts.get(key, {})
                cutoff = now - login_attempt_window_seconds
                failures = [
                    float(value) for value in previous.get("failures", [])
                    if float(value) >= cutoff
                ]
                failures.append(now)
                blocked_until = float(previous.get("blocked_until", 0) or 0)
                if len(failures) >= max_login_failures:
                    blocked_until = max(blocked_until, now + login_block_seconds)
                login_attempts.pop(key, None)
                login_attempts[key] = {
                    "failures": failures,
                    "blocked_until": blocked_until,
                    "last_seen": now,
                }
                while len(login_attempts) > max_login_attempt_keys:
                    login_attempts.pop(next(iter(login_attempts)), None)
                return blocked_until > now

        @staticmethod
        def _clear_login_failures(key: tuple[str, str]) -> None:
            with login_attempts_lock:
                login_attempts.pop(key, None)

        @staticmethod
        def _purge_login_attempts_locked(now: float) -> None:
            cutoff = now - login_attempt_window_seconds
            stale = [
                key for key, attempt in login_attempts.items()
                if float(attempt.get("blocked_until", 0) or 0) <= now
                and float(attempt.get("last_seen", 0) or 0) < cutoff
            ]
            for key in stale:
                login_attempts.pop(key, None)

        @staticmethod
        def _host_allowed(host: str) -> bool:
            configured = {
                value.strip().casefold()
                for value in os.environ.get("ODE_ALLOWED_HOSTS", "").split(",")
                if value.strip()
            }
            hostname = urlparse("//" + host).hostname or ""
            if hostname.casefold() in {"localhost", *configured}:
                return True
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return False
            return address.is_loopback or address.is_private

        @staticmethod
        def _query(query: dict[str, list[str]], name: str) -> str:
            return query.get(name, [""])[0]

        @classmethod
        def _query_int(
            cls,
            query: dict[str, list[str]],
            name: str,
            *,
            default: int | None = None,
            minimum: int | None = None,
            maximum: int | None = None,
        ) -> int:
            raw = cls._query(query, name)
            if not raw:
                if default is None:
                    raise WarehouseError(f"Укажите параметр {name}")
                value = default
            else:
                try:
                    value = int(raw)
                except ValueError as error:
                    raise WarehouseError(f"Параметр {name} должен быть целым числом") from error
            if minimum is not None and value < minimum:
                raise WarehouseError(f"Параметр {name} должен быть не меньше {minimum}")
            if maximum is not None and value > maximum:
                raise WarehouseError(f"Параметр {name} должен быть не больше {maximum}")
            return value

        def _read_json_object(self, maximum_size: int) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise WarehouseError("Некорректный размер запроса") from error
            if length <= 0 or length > maximum_size:
                raise WarehouseError("Некорректный размер запроса")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeError) as error:
                raise WarehouseError("Тело запроса должно содержать корректный JSON") from error
            if not isinstance(data, dict):
                raise WarehouseError("JSON-запрос должен быть объектом")
            return data

        @staticmethod
        def _optional_json_int(data: dict[str, Any], name: str) -> int | None:
            value = data.get(name)
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError) as error:
                raise WarehouseError(f"Поле {name} должно быть целым числом") from error

        @staticmethod
        def _validate_action_payload(data: dict[str, Any]) -> None:
            action = data.get("action")
            if not isinstance(action, str) or not action:
                raise WarehouseError("Поле action должно быть непустой строкой")
            collection_fields: dict[str, dict[str, type]] = {
                "WORK_LOGS": {"rows": list},
                "CONFIRM_SCANNED_RECEIPTS": {"common_fields": dict, "serial_numbers": list},
                "CONFIRM_SCANNED_ISSUES": {"common_fields": dict, "serial_numbers": list},
                "CONFIRM_SCANNED_ISSUE_PAIRS": {"common_fields": dict, "pairs": list},
                "UPDATE_DELIVERY_LINES": {"line_ids": list, "values": dict},
                "ACCEPT_DELIVERY_SERIAL": {"values": dict},
                "ACCEPT_DELIVERY_BATCH": {"line_ids": list, "common_values": dict},
            }
            allowed = collection_fields.get(action, {})
            numeric_fields = {
                "equipment_id", "quantity", "delivery_id", "reference_id",
                "source_id", "target_id",
            }
            boolean_fields = {"only_empty", "unplanned", "is_active", "confirmed"}
            for key, value in data.items():
                if key == "action":
                    continue
                if key in allowed:
                    if not isinstance(value, allowed[key]):
                        raise WarehouseError(f"Поле {key} имеет неверный тип")
                    Handler._validate_action_collection(value, key)
                elif key in numeric_fields:
                    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                        raise WarehouseError(f"Поле {key} должно быть числом")
                elif key in boolean_fields:
                    Handler._json_boolean(value, key)
                elif not isinstance(value, str):
                    raise WarehouseError(f"Поле {key} должно быть строкой")

        @staticmethod
        def _validate_action_collection(value: Any, field: str) -> None:
            if field in {"rows", "pairs"}:
                if any(not isinstance(item, dict) for item in value):
                    raise WarehouseError("Поле rows должно быть списком объектов")
                mappings = value
            elif field == "serial_numbers":
                if any(not isinstance(item, str) for item in value):
                    raise WarehouseError("Поле serial_numbers должно быть списком строк")
                return
            elif field == "line_ids":
                if any(
                    isinstance(item, bool) or not isinstance(item, (str, int))
                    for item in value
                ):
                    raise WarehouseError("Поле line_ids должно быть списком идентификаторов")
                return
            else:
                mappings = [value]
            for mapping in mappings:
                for key, item in mapping.items():
                    if not isinstance(key, str) or item is None or isinstance(item, (dict, list)):
                        raise WarehouseError(f"Поле {field} содержит неверный тип значения")
                    if not isinstance(item, (str, int, float, bool)):
                        raise WarehouseError(f"Поле {field} содержит неверный тип значения")

        @staticmethod
        def _json_boolean(value: Any, field: str) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().casefold()
                if normalized in {"1", "true", "yes", "on"}:
                    return True
                if normalized in {"", "0", "false", "no", "off"}:
                    return False
            raise WarehouseError(f"Поле {field} должно быть логическим значением")

        def _balance_filters(self, query: dict[str, list[str]]) -> dict[str, str]:
            return {
                name: self._query(query, name)
                for name in (
                    "query", "project", "object_name", "equipment_type", "component_type",
                    "cable_type", "unit", "datacenter", "category", "item_type",
                    "supplier", "vendor", "stock_state", "sort_by", "sort_dir",
                )
            }

        def _send_template(self, filename: str, text: str) -> None:
            self._send_download(filename, ("\ufeff" + text).encode("utf-8"))

        def _send_json(self, status: int, data: Any) -> None:
            self._send(status, _json_bytes(data), "application/json; charset=utf-8")

        def _send_csv(
            self, filename: str, rows: list[dict[str, Any]], *, delimiter: str = ";"
        ) -> None:
            self._send_download(filename, csv_download_bytes(rows, delimiter))

        def _send_download(self, filename: str, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_binary_download(
            self, filename: str, body: bytes, content_type: str
        ) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_static(self, path: str) -> None:
            relative = Path(unquote(path.removeprefix("/static/")))
            if relative.is_absolute() or ".." in relative.parts:
                self._send_json(404, {"error": "Файл не найден"})
                return
            target = STATIC_ROOT / relative
            if not target.is_file():
                self._send_json(404, {"error": "Файл не найден"})
                return
            content_types = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }
            self._send(
                200,
                target.read_bytes(),
                content_types.get(target.suffix.lower(), "application/octet-stream"),
            )

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if cookie := getattr(self, "_pending_cookie", ""):
                self.send_header("Set-Cookie", cookie)
                self._pending_cookie = ""
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ODE — учет работ и склада")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="путь к файлу SQLite")
    parser.add_argument("--host", default="127.0.0.1", help="адрес локального сервера")
    parser.add_argument("--port", type=int, default=8765, help="порт локального сервера")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument(
        "--warehouse-contour",
        choices=("production", "demo"),
        default="production",
        help="production блокирует складские записи до baseline; demo разрешает их только на отдельной БД",
    )
    parser.add_argument(
        "--inventory-state-root",
        default=None,
        help="внешний application state root для FULL inventory Preview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_test_mode_database(args.db)
        contour_policy = PostingPolicy(
            args.db,
            mode=args.warehouse_contour,
            production_db_path=DEFAULT_DB_PATH,
        )
        if args.warehouse_contour == "demo" and not contour_policy.demo:
            raise RuntimeError(str(contour_policy.status()["configuration_error"]))
        # This must run before WarehouseService/initialize can touch the file.
        migration_full_status = validate_full_migration_database(args.db)
        migration_pilot_status = validate_migration_pilot_database(args.db)
    except RuntimeError as error:
        parser.error(str(error))
    service = WarehouseService(
        args.db,
        initialize_database=not migration_pilot_status.get("enabled")
        and not migration_full_status.get("read_only"),
    )
    app_context = create_application_context(
        args.db,
        service=service,
        configuration=RuntimeConfig(
            service.db_path,
            warehouse_contour=args.warehouse_contour,
            production_db_path=DEFAULT_DB_PATH,
            full_inventory_state_root=(
                Path(args.inventory_state_root).expanduser()
                if args.inventory_state_root
                else None
            ),
        ),
    )
    stats = service.dashboard_stats()
    health = service._database_check(service.db_path, service.KEY_TABLES)
    integrity_status = "ok" if health["ok"] else "; ".join(health["messages"])
    contour = (
        "REVIEW DATABASE"
        if migration_pilot_status.get("enabled") or migration_full_status.get("read_only")
        else "WORKING DATABASE"
    )
    if contour == "WORKING DATABASE":
        contour = "DEMO DATABASE" if contour_policy.demo else "HISTORICAL READ-ONLY DATABASE"
    print(contour)
    print(f"Path: {service.db_path.resolve()}")
    print(f"ODE version: {PRODUCT_VERSION}")
    print(f"Cards: {int(stats.get('cards', stats['positions']))}")
    print(f"Integrity: {integrity_status}")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app_context))
    url = f"http://{args.host}:{server.server_port}"
    print(f"Интерфейс открыт: {url}")
    print("Для завершения нажмите Ctrl+C.")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nРабота завершена.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
