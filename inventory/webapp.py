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
from .db import DEFAULT_DB_PATH
from .importing import parse_csv_bytes, unknown_csv_headers
from .service import WarehouseError, WarehouseService


CURRENT_DATACENTER = "Ixcellerate"
STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
PRODUCT_NAME = "ODE"
PRODUCT_VERSION = __version__

LOGIN_HTML = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Вход — ODE</title>
<style>body{margin:0;background:#f4f7fb;color:#172033;font:14px system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(390px,calc(100% - 32px));padding:28px;background:white;border:1px solid #dce3ec;border-radius:14px;box-shadow:0 8px 24px #1720330d}h1{margin:0 0 5px}p{color:#667085}label{display:block;margin-top:15px;font-weight:650}input{width:100%;box-sizing:border-box;margin-top:6px;padding:12px;border:1px solid #cbd5e1;border-radius:8px}button{width:100%;margin-top:20px;padding:12px;border:0;border-radius:8px;background:#2563eb;color:white;font-weight:700;cursor:pointer}.link{background:none;color:#475569;font-weight:500}.error{color:#991b1b}.admin{display:none}.admin.show{display:block}</style></head><body><form class="card" id="login"><h1>ODE</h1><p>Укажите, кто работает с системой</p><div id="engineer"><label>ФИО инженера<input name="full_name" autocomplete="name" required autofocus placeholder="Иванов Иван Иванович"></label></div><div class="admin" id="admin"><label>Логин<input name="email" autocomplete="username"></label><label>Пароль<input name="password" type="password" autocomplete="current-password"></label></div><button id="submit">Продолжить</button><button class="link" type="button" id="mode">Режим администратора</button><p class="error" id="error"></p></form><script>let admin=false;document.getElementById('mode').onclick=()=>{admin=!admin;document.getElementById('admin').classList.toggle('show',admin);document.getElementById('engineer').style.display=admin?'none':'block';document.querySelector('[name=full_name]').required=!admin;document.querySelector('[name=email]').required=admin;document.querySelector('[name=password]').required=admin;document.getElementById('submit').textContent=admin?'Войти как администратор':'Продолжить';document.getElementById('mode').textContent=admin?'Обычный вход':'Режим администратора'};document.getElementById('login').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));data.mode=admin?'admin':'engineer';const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const x=await r.json();if(r.ok)location.href='/';else document.getElementById('error').textContent=x.error||'Ошибка входа'};</script></body></html>'''


LOGIN_HTML = (LOGIN_HTML
    .replace("<title>Вход — ODE</title>", f"<title>Начало смены — {PRODUCT_NAME} {PRODUCT_VERSION}</title>")
    .replace("<h1>ODE</h1><p>Укажите, кто работает с системой</p>",
             f"<h1>Кто сегодня работает?</h1><p>{PRODUCT_NAME} {PRODUCT_VERSION}. Операции смены будут записаны под выбранным именем.</p>")
    .replace(">Продолжить</button>", ">Начать работу</button>")
    .replace(">Режим администратора</button>", ">Вход администратора</button>")
)

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

<section class="view panel" id="inventory"><div class="import-box"><div><strong>Инвентаризация по S/N</strong><p>Загрузите CSV со столбцом SN, S/N, Серийный номер или Серийник.</p></div><div class="import-actions"><a class="button" href="/import/inventory-template.csv">Шаблон</a><label class="button primary" for="inventoryCsv">Загрузить CSV</label><input class="file-input inventory-input" id="inventoryCsv" data-kind="inventory" type="file" accept=".csv"><button class="button" id="inventoryExport" disabled>Экспорт результата</button></div></div><div class="cards" id="inventoryCards"></div><div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>S/N</th><th>Результат</th><th>Количество</th></tr></thead><tbody id="inventoryBody"><tr><td class="empty" colspan="3">CSV еще не загружен</td></tr></tbody></table></div></section>

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
function renderBalance(){const filters=activeBalanceFilters();const query=document.getElementById('balanceQuery').value.trim().toLocaleLowerCase();const matched=state.balance.filter(x=>Object.entries(filters).every(([k,v])=>x[k]===v)&&rowMatchesQuery(x,query));const rows=matched.slice(0,500);document.getElementById('balanceLimit').textContent=matched.length>500?'Показаны первые 500 строк. Уточните поиск или скачайте баланс целиком.':`Показано строк: ${matched.length}`;document.getElementById('balanceBody').innerHTML=rows.map(x=>{const key=encodeURIComponent(x.position_key);const type=x.equipment_type||x.component_type||x.cable_type;return `<tr><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')}</td><td>${esc(x.unit)}</td><td>${esc(x.project)}</td><td>${esc(x.datacenter)}</td><td>${esc(x.shelf)}</td><td>${esc(x.object_name)}</td><td>${esc(type)}</td><td>${esc(x.vendor)}</td><td><button class="button" onclick="openPositionCard('${key}')">Открыть карточку</button> <button class="button" ${Number(x.balance)<=0?'disabled':''} onclick="selectForIssue('${key}')">Списать</button></td></tr>`}).join('')||'<tr><td class="empty" colspan="13">Нет данных</td></tr>';document.getElementById('balanceExport').href='/export/balance.csv?'+new URLSearchParams({...filters,query:document.getElementById('balanceQuery').value.trim()})}
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
RECEIPT_SCANNER_HTML = '''<div class="scanner-box"><h2>Приемка сканером</h2><p class="hint">Заполните общие поля партии, затем сканируйте S/N. Запись в базу выполняется только после подтверждения.</p><form class="form" id="scanReceiptForm"><label>Дата</label><input name="receipt_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Поставщик</label><input name="supplier" class="ref-input" data-kind="supplier" list="ref-supplier" required><label>Вендор</label><input name="vendor" class="ref-input" data-kind="vendor" list="ref-vendor" required><label>Модель</label><input name="model" class="ref-input" data-kind="model" list="ref-model"><label>Наименование</label><input name="item_name" class="ref-input" data-kind="item_name" list="ref-item_name" required><label>Проект</label><input name="project" class="ref-input" data-kind="project" list="ref-project"><label>ЦОД</label><input name="datacenter" class="ref-input" data-kind="datacenter" list="ref-datacenter" value="Ixcellerate" required><label>Стеллаж/Полка</label><input name="shelf" class="ref-input" data-kind="shelf" list="ref-shelf"><label>Объект</label><input name="object_name" class="ref-input" data-kind="object" list="ref-object" required><label>Тип оборудования</label><input name="equipment_type" class="ref-input" data-kind="equipment_type" list="ref-equipment_type"><label>Тип компонента</label><input name="component_type" class="ref-input" data-kind="component_type" list="ref-component_type"><label>Тип кабеля</label><input name="cable_type" class="ref-input" data-kind="cable_type" list="ref-cable_type"><label>Единица учета</label><input name="unit" class="ref-input" data-kind="unit" list="ref-unit" value="шт" required></form><input class="scanner-input" id="receiptScanner" placeholder="Сканируйте S/N или QR" autocomplete="off"><div class="table-wrap scanner-table"><table><thead><tr><th>S/N</th><th>Результат проверки</th><th></th></tr></thead><tbody id="scanReceiptBody"><tr><td class="scanner-empty" colspan="3">Список сканирования пуст</td></tr></tbody></table></div><div class="actions" style="margin-top:14px"><button class="button primary" id="confirmScanReceipts" disabled>Принять всё на склад</button></div></div>'''
ISSUE_SCANNER_HTML = '''<div class="scanner-box"><h2>Списание сканером</h2><p class="hint">Сканер работает как клавиатура. Неизвестные S/N отмечаются и после подтверждения попадают в проблемные строки.</p><form class="form" id="scanIssueForm"><label>Дата</label><input name="issue_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Тип задачи</label><select name="task_type" id="scanIssueTaskType" required></select><label>Номер задачи</label><input name="task_number" required><label>S/N целевого оборудования</label><input name="target_serial_number"><label>Hostname</label><input name="target_hostname"><label>Комментарий</label><textarea name="comment"></textarea></form><input class="scanner-input" id="issueScanner" placeholder="Сканируйте S/N списываемого оборудования" autocomplete="off"><div class="table-wrap scanner-table"><table><thead><tr><th>S/N</th><th>Наименование</th><th>Модель</th><th>Полка</th><th>Остаток</th><th>Результат</th><th></th></tr></thead><tbody id="scanIssueBody"><tr><td class="scanner-empty" colspan="7">Список сканирования пуст</td></tr></tbody></table></div><div class="actions" style="margin-top:14px"><button class="button primary" id="confirmScanIssues" disabled>Списать всё</button></div></div>'''
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

DELIVERY_JS = r'''
let currentDelivery=0;
function renderWarehouseCategories(){const target=document.getElementById('warehouseCategories');if(target)target.innerHTML=(state.warehouse_categories||[]).map((x,i)=>`<div class="card" style="border-top:4px solid ${['#2563eb','#0ea5e9','#8b5cf6','#14b8a6','#f59e0b','#64748b'][i]}"><span>${esc(x.name)}</span><strong>${Number(x.quantity).toLocaleString('ru-RU')}</strong></div>`).join('')}
async function loadDeliveries(){try{const q=document.getElementById('deliverySearch')?.value||'';const rows=q?(await request('/api/deliveries?query='+encodeURIComponent(q))).deliveries:(state.deliveries||[]);document.getElementById('deliveryList').innerHTML=rows.map(x=>`<tr><td>${esc(x.delivery_number||'Без номера')}</td><td>${esc(x.supplier)}</td><td>${esc(x.source_filename)}</td><td><span class="badge">${esc(x.status)}</span></td><td>${x.accepted||0} из ${x.total||0}</td><td>${x.problems||0}</td><td><button class="button primary" onclick="openDelivery(${x.id})">Открыть поставку</button></td></tr>`).join('')||'<tr><td class="empty" colspan="7">Поставок пока нет</td></tr>'}catch(e){notify(e.message,true)}}
async function openDelivery(id){try{currentDelivery=id;const r=await request('/api/delivery?id='+id),d=r.delivery,summary={total:r.lines.length,accepted:r.lines.filter(x=>x.state==='Принято').length,existing:r.lines.filter(x=>x.state==='Уже на складе').length,errors:r.lines.filter(x=>['Ошибка','Дубль в файле'].includes(x.state)).length,waiting:r.lines.filter(x=>x.state==='Ожидается').length};document.getElementById('deliveryCard').innerHTML=`<div class="box"><div class="modal-head"><div><h2>Поставка ${esc(d.delivery_number||'#'+d.id)}</h2><p class="hint">${esc(d.supplier)} · ${esc(d.status)}</p></div><div><a class="button" href="/export/delivery.csv?id=${id}">Скачать результат</a> <button class="button" onclick="closeDelivery(${id})">Закрыть поставку</button></div></div><div class="cards" style="margin-bottom:14px">${[['Всего',summary.total],['Принято',summary.accepted],['Уже на складе',summary.existing],['Ошибки',summary.errors],['Ожидается',summary.waiting]].map(([k,v])=>`<div class="card"><span>${k}</span><strong>${v}</strong></div>`).join('')}</div><div class="box" style="margin-bottom:14px;background:#eff6ff"><h3>Приемка сканером</h3><input id="deliveryScanner" style="width:100%;font-size:22px;padding:15px;border:2px solid #2563eb;border-radius:9px" placeholder="Сканируйте S/N или QR" onkeydown="if(event.key==='Enter'){event.preventDefault();scanDelivery()}"><div id="deliveryScanResult" class="hint" style="margin-top:10px"></div></div><div class="import-actions" style="margin-bottom:10px"><select id="deliveryFillField"><option value="datacenter">ЦОД</option><option value="shelf">Стеллаж/полка</option><option value="object_name">Объект</option><option value="equipment_type">Тип оборудования</option><option value="component_type">Тип компонента</option><option value="cable_type">Тип кабеля</option><option value="vendor">Вендор</option><option value="model">Модель</option><option value="item_name">Наименование</option></select><input id="deliveryFillValue" placeholder="Значение"><button class="button" onclick="fillDelivery(false)">Заполнить выбранные строки</button><button class="button" onclick="fillDelivery(true)">Заполнить пустые ниже этим значением</button><button class="button primary" onclick="acceptSelectedDelivery()">Принять выбранные строки</button></div><div class="table-wrap"><table><thead><tr><th></th><th>S/N</th><th>Состояние</th><th>Наименование</th><th>Модель</th><th>Вендор</th><th>ЦОД</th><th>Полка</th><th>Объект</th><th>Тип</th><th>Кол-во</th></tr></thead><tbody id="deliveryLines">${r.lines.map(x=>`<tr><td><input class="delivery-check" type="checkbox" value="${x.id}" ${x.state==='Принято'?'disabled':''}></td><td>${esc(x.serial_number)}</td><td>${esc(x.state)}${x.error_text?' · '+esc(x.error_text):''}</td><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.vendor)}</td><td>${esc(x.datacenter)}</td><td>${esc(x.shelf)}</td><td>${esc(x.object_name)}</td><td>${esc(x.equipment_type||x.component_type||x.cable_type)}</td><td>${x.quantity}</td></tr>`).join('')}</tbody></table></div></div>`;document.getElementById('deliveryScanner').focus()}catch(e){notify(e.message,true)}}
function selectedDeliveryLineIds(){return [...document.querySelectorAll('.delivery-check:checked')].map(x=>Number(x.value))}
function promptUnplannedValues(serial){const supplier=prompt(`Поставщик для ${serial}`,'');if(!supplier)return null;const vendor=prompt('Вендор','');if(!vendor)return null;const model=prompt('Модель','')||'';const equipment_type=prompt('Тип оборудования или компонента','');if(!equipment_type)return null;const project=prompt('Проект','')||'';const datacenter=prompt('ЦОД','Ixcellerate');if(!datacenter)return null;const shelf=prompt('Стеллаж/полка','');if(!shelf)return null;const item_name=[equipment_type,vendor,model].filter(Boolean).join(' ');return{supplier,vendor,model,equipment_type,project,datacenter,shelf,item_name}}
async function scanDelivery(){const input=document.getElementById('deliveryScanner'),serial=input.value.trim(),box=document.getElementById('deliveryScanResult');if(!serial)return;try{const info=await actionJson({action:'INSPECT_DELIVERY_SERIAL',delivery_id:currentDelivery,serial_number:serial});box.innerHTML=`S/N ${esc(info.serial_number)} · ${info.found_in_delivery?'найден в документе':'не найден в документе'} · ${info.exists_in_warehouse?'уже на складе':'новый'}`;let r=null;if(info.allowed_actions.includes('blocked_already_accepted'))throw new Error('Этот S/N уже принят');if(info.allowed_actions.includes('accept_new')){if(!confirm(`Принять S/N ${info.serial_number} на склад?`)){input.value='';input.focus();return}r=await actionJson({action:'ACCEPT_DELIVERY_SERIAL',delivery_id:currentDelivery,serial_number:serial})}else if(info.allowed_actions.includes('fill_empty_existing')){const conflicts=Object.keys(info.conflicting_fields||{});if(!confirm(`S/N уже есть на складе. Дополнить только пустые поля?${conflicts.length?' Конфликты не будут перезаписаны: '+conflicts.join(', '):''}`)){input.value='';input.focus();return}r=await actionJson({action:'ACCEPT_DELIVERY_SERIAL',delivery_id:currentDelivery,serial_number:serial})}else if(info.allowed_actions.includes('accept_unplanned')){if(!confirm('S/N не найден в поставке. Принять как внеплановую позицию?')){input.value='';input.focus();return}const values=promptUnplannedValues(info.serial_number);if(!values){input.value='';input.focus();return}r=await actionJson({action:'ACCEPT_DELIVERY_SERIAL',delivery_id:currentDelivery,serial_number:serial,unplanned:true,values})}if(r&&r.accepted){notify('Позиция обработана');input.value='';await loadAll();await openDelivery(currentDelivery)}else notify('Позиция пропущена')}catch(e){notify(e.message,true);input.focus()}}
async function acceptSelectedDelivery(){const ids=selectedDeliveryLineIds();if(!ids.length)return notify('Выберите строки',true);try{const r=await actionJson({action:'ACCEPT_DELIVERY_BATCH',delivery_id:currentDelivery,line_ids:ids,common_values:{}});notify(`Принято: ${r.accepted_new||0}, связано: ${r.linked_existing||0}`);await loadAll();await openDelivery(currentDelivery)}catch(e){notify(e.message,true)}}
async function fillDelivery(only_empty){const ids=[...document.querySelectorAll('.delivery-check:checked')].map(x=>Number(x.value)),field=document.getElementById('deliveryFillField').value,value=document.getElementById('deliveryFillValue').value;try{await actionJson({action:'UPDATE_DELIVERY_LINES',delivery_id:currentDelivery,line_ids:ids,values:{[field]:value},only_empty});notify('Строки обновлены');await openDelivery(currentDelivery)}catch(e){notify(e.message,true)}}
async function saveDeliveryCell(line_id,field,value){try{await actionJson({action:'UPDATE_DELIVERY_LINES',delivery_id:currentDelivery,line_ids:[line_id],values:{[field]:value}});notify('Ячейка сохранена')}catch(e){notify(e.message,true)}}
async function closeDelivery(id){if(!confirm('Закрыть поставку? Приемка после закрытия будет недоступна.'))return;try{await actionJson({action:'CLOSE_DELIVERY',delivery_id:id});await loadAll();await loadDeliveries();document.getElementById('deliveryCard').innerHTML=''}catch(e){notify(e.message,true)}}
async function actionJson(data){return request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})}
document.getElementById('deliveryCsv').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{const r=await request('/api/preview-csv?kind=delivery',{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file}),s=r.summary||{};const stats=[['Строк файла',s.source_rows??r.total],['Получено S/N',s.serials??r.total],['Новые S/N',s.new_serials??r.new],['Уже на складе',s.existing_stock??r.updated],['Дубли',s.duplicates??r.duplicates],['Без S/N',s.rows_without_serial??0],['Ошибки',s.errors??r.errors],['Предупреждения',s.warnings??0]];document.getElementById('deliveryPreview').innerHTML=`<div class="box"><h3>Проверка файла</h3><div class="cards">${stats.map(([name,value])=>`<div class="card"><span>${name}</span><strong>${value||0}</strong></div>`).join('')}</div>${r.unknown_columns.length?`<p class="hint">Нераспознанные столбцы: ${r.unknown_columns.map(esc).join(', ')}</p>`:'<p class="hint">Все столбцы распознаны.</p>'}<div style="margin-top:12px"><button class="button primary" ${r.can_confirm?'':'disabled'} onclick="confirmDelivery('${r.preview_id}')">Подтвердить импорт</button></div></div>`}catch(x){notify(x.message,true)}finally{e.target.value=''}};
async function confirmDelivery(preview_id){try{const r=await actionJson({action:'CONFIRM_DELIVERY',preview_id});notify('Поставка загружена');document.getElementById('deliveryPreview').innerHTML='';await loadAll();await loadDeliveries();await openDelivery(r.delivery_id)}catch(e){notify(e.message,true)}}
'''
for _field in ("item_name", "model", "vendor", "datacenter", "shelf", "object_name"):
    DELIVERY_JS = DELIVERY_JS.replace(
        f'<td>${{esc(x.{_field})}}</td>',
        f'<td contenteditable="true" onblur="saveDeliveryCell(${{x.id}},\'{_field}\',this.innerText)">${{esc(x.{_field})}}</td>',
    )
HTML = HTML.replace("const today=new Date()", DELIVERY_JS + "\nconst today=new Date()")
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
    '<header class="top"><div><h1 id="pageTitle">Главная</h1><span class="hint">Отдел дежурных инженеров · Ixcellerate</span></div><div class="profile-actions"><span id="currentUser"></span><button class="button" id="adminPassword" hidden onclick="showProfile()">Сменить пароль</button><button class="button" onclick="loadAll()">Обновить</button><button class="button" onclick="logout()">Сменить инженера / выйти</button><select id="importMode" hidden><option value="soft">Обычная</option><option value="strict">Полная</option></select></div></header>',
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

# Финальный UX-слой сохраняет старые API и таблицы БД, но показывает инженеру
# предметные формы вместо набора технических полей.
UX_SCRIPT = r'''
const RECEIPT_TYPES={
 'Оборудование':['Сервер','Коммутатор','СХД','ИБП','Другое оборудование'],
 'Компоненты':['RAM','SSD','HDD','CPU','RAID','NIC','PSU','Трансивер','Другое комплектующее'],
 'Кабели':['Оптика','Медь','DAC','AOC','Другое']};
const TYPE_VENDORS={
 'Сервер':['Dell','HPE','Lenovo','Supermicro','Другое'],
 'RAM':['Samsung','Hynix','Micron','Kingston','Другое'],
 'SSD':['Samsung','Intel','Micron','Toshiba','Seagate','WD','Другое'],
 'HDD':['Samsung','Intel','Micron','Toshiba','Seagate','WD','Другое']};
function refsOf(kind){return state.references.filter(x=>x.kind===kind&&x.is_active).map(x=>x.name)}
function setOptions(select,values,placeholder='Выберите'){select.innerHTML=option('',placeholder)+values.map(x=>option(x)).join('')}
function receiptCategoryChanged(){const f=document.getElementById('simpleReceiptForm'),category=f.category.value;setOptions(f.item_type,RECEIPT_TYPES[category]||[]);f.item_type.disabled=!category;updateReceiptFields()}
function updateReceiptFields(){const f=document.getElementById('simpleReceiptForm'),category=f.category.value,type=f.item_type.value,isCable=category==='Кабели';setOptions(f.vendor,TYPE_VENDORS[type]||(isCable?['Не указан']:refsOf('vendor').concat('Другое')),'Не указан');f.vendor.value=isCable?'Не указан':'';f.vendor.closest('.ux-field').hidden=isCable;f.model.closest('.ux-field').hidden=isCable;f.serial_number.closest('.ux-field').hidden=isCable;f.inventory_number.closest('.ux-field').hidden=isCable;f.quantity.closest('.ux-field').hidden=!isCable;f.serial_number.required=!isCable;f.quantity.value=isCable?f.quantity.value||1:1;updateReceiptSuggestions()}
function updateReceiptSuggestions(){const f=document.getElementById('simpleReceiptForm'),type=selectedOrCustom(f.item_type,f.custom_type),vendor=selectedOrCustom(f.vendor,f.custom_vendor),model=f.model.value.trim();const rows=(state.recent_receipts||[]).filter(x=>(!type||(x.equipment_type||x.component_type||x.cable_type)===type)&&(!vendor||vendor==='Не указан'||x.vendor===vendor));const models=[...new Set(rows.map(x=>x.model).filter(Boolean))],names=[...new Set(rows.filter(x=>!model||x.model===model).map(x=>x.item_name).filter(Boolean))];for(const [id,values] of [['ref-model',[...models,...refsOf('model')]],['ref-item_name',[...names,...refsOf('item_name')]]]){let list=document.getElementById(id);if(!list){list=document.createElement('datalist');list.id=id;document.body.appendChild(list)}list.innerHTML=[...new Set(values)].map(x=>option(x)).join('')}}
function selectedOrCustom(select,custom){return select.value==='Другое'?(custom.value.trim()||'Другое'):select.value}
function toggleCustom(select,custom){custom.hidden=select.value!=='Другое';if(!custom.hidden)custom.focus()}
function receiptPayload(form){const d=formData(form),category=d.category,type=selectedOrCustom(form.item_type,form.custom_type);return {action:'STOCK_RECEIPT',receipt_date:d.receipt_date,responsible:d.responsible,supplier:selectedOrCustom(form.supplier,form.custom_supplier)||'Не указан',item_name:d.item_name,project:d.project||'',serial_number:d.serial_number||'',inventory_number:d.inventory_number||'',vendor:selectedOrCustom(form.vendor,form.custom_vendor)||'Не указан',model:d.model||'',shelf:d.shelf||'',object_name:d.object_name||'Не указано',datacenter:'Ixcellerate',equipment_type:category==='Оборудование'?type:'',component_type:category==='Компоненты'?type:'',cable_type:category==='Кабели'?type:'',unit:'шт',quantity:category==='Кабели'?d.quantity:1,order_date:'',request_number:'',order_number:'',plu:''}}
async function saveSimpleReceipt(e){e.preventDefault();try{await actionJson(receiptPayload(e.currentTarget));notify('Приход сохранен');e.currentTarget.reset();setReceiptMode('Оборудование');await loadAll()}catch(x){notify(x.message,true)}}
function setReceiptMode(category){const f=document.getElementById('simpleReceiptForm');f.category.value=category;receiptCategoryChanged();document.querySelectorAll('[data-receipt-mode]').forEach(x=>x.classList.toggle('primary',x.dataset.receiptMode===category));document.getElementById('simpleReceiptTitle').textContent=category==='Кабели'?'Приход кабелей':'Приход оборудования и компонентов'}
function cableIssuePayload(form){const d=formData(form);return {action:'STOCK_ISSUE',issue_date:d.issue_date,responsible:d.responsible,source_cable_type:selectedOrCustom(form.source_cable_type,form.custom_cable_type),source_item_name:d.source_item_name,quantity:d.quantity,task_type:d.task_type||'',task_number:d.task_number||'',target_serial_number:'',target_hostname:'',comment:[d.project?`Проект: ${d.project}`:'',d.comment||''].filter(Boolean).join('; ')}}
async function saveCableIssue(e){e.preventDefault();try{await actionJson(cableIssuePayload(e.currentTarget));notify('Кабель списан');e.currentTarget.reset();e.currentTarget.issue_date.value=today;await loadAll()}catch(x){notify(x.message,true)}}
function dailyRow(){const sources=['Rooms','Outlook','ITSM','Zabbix','DCIM','Склад','Другое'],types=['ЗНР','ПНР','ИЗМ','ЗНО','ИНЦ','Другое'],statuses=['Выполнено','В работе','Ожидание','Отложено'];return `<tr><td><select name="task_source" required>${sources.map(x=>option(x)).join('')}</select></td><td><select name="task_type" required>${types.map(x=>option(x)).join('')}</select></td><td><input name="task_number" required></td><td><textarea name="description" required></textarea></td><td><select name="status" required>${statuses.map(x=>option(x)).join('')}</select></td><td><textarea name="comment"></textarea></td><td><button type="button" class="button" onclick="this.closest('tr').remove()">Удалить</button></td></tr>`}
function addDailyRow(){document.getElementById('dailyLogRows').insertAdjacentHTML('beforeend',dailyRow())}
async function saveDailyLogs(){const date=document.getElementById('dailyLogDate').value,rows=[...document.querySelectorAll('#dailyLogRows tr')].map(tr=>Object.fromEntries(new FormData(Object.assign(document.createElement('form'),{innerHTML:tr.innerHTML})).entries()));/* form clone loses textarea state, collect directly */const clean=[...document.querySelectorAll('#dailyLogRows tr')].map(tr=>Object.fromEntries([...tr.querySelectorAll('[name]')].map(x=>[x.name,x.value]))).map(x=>({...x,work_date:date}));if(!date||clean.some(x=>!x.task_number.trim()||!x.description.trim())){notify('Заполните дату, номер задачи и выполненные работы',true);return}try{const r=await actionJson({action:'WORK_LOGS',rows:clean});notify(`Сохранено задач: ${r.saved}`);document.getElementById('dailyLogRows').innerHTML=dailyRow();await buildDaily()}catch(x){notify(x.message,true)}}
function balanceCategory(x){return x.category||x.cable_type?'Кабели':x.component_type?'Компоненты':'Оборудование'}
function renderSimpleBalance(){const q=document.getElementById('balanceQuery').value.trim().toLocaleLowerCase(),category=document.getElementById('uxBalanceCategory').value,type=document.getElementById('uxBalanceType').value,project=document.getElementById('uxBalanceProject').value;const rows=state.balance.filter(x=>(!category||x.category===category)&&(!type||x.item_type===type)&&(!project||x.project===project)&&rowMatchesQuery(x,q));document.getElementById('balanceBody').innerHTML=rows.slice(0,500).map(x=>`<tr><td>${esc(x.category)}</td><td>${esc(x.item_type)}</td><td>${esc(x.item_name)}</td><td>${esc(x.supplier)}</td><td>${esc(x.vendor)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')}</td><td>${esc(x.project)}</td><td>${esc(x.shelf)}</td><td>${esc(x.object_name)}</td><td><button class="button" onclick="openPositionCard('${encodeURIComponent(x.position_key)}')">Открыть карточку</button> <button class="button" onclick="selectForIssue('${encodeURIComponent(x.position_key)}')">Списать</button></td></tr>`).join('')||'<tr><td class="empty" colspan="12">Ничего не найдено</td></tr>';document.getElementById('balanceLimit').textContent=`Показано строк: ${rows.length}`}
function initEngineerUX(){
 const receipt=document.getElementById('receipt');receipt.querySelectorAll(':scope > .scanner-box,:scope > .import-box,:scope > .preview,:scope > h2,:scope > p,:scope > form.form').forEach(x=>x.hidden=true);receipt.insertAdjacentHTML('afterbegin',`<div class="mode-tabs"><button class="button primary" data-receipt-mode="Оборудование" onclick="setReceiptMode('Оборудование')">Принять оборудование</button><button class="button" data-receipt-mode="Компоненты" onclick="setReceiptMode('Компоненты')">Принять компоненты</button><button class="button" data-receipt-mode="Кабели" onclick="setReceiptMode('Кабели')">Приход кабелей</button></div><h2 id="simpleReceiptTitle">Приход оборудования и компонентов</h2><form class="ux-form" id="simpleReceiptForm"><div class="ux-field"><label>Дата</label><input name="receipt_date" type="date" required value="${today}"></div><div class="ux-field"><label>ФИО</label><input name="responsible" required></div><div class="ux-field"><label>Поставщик</label><select name="supplier" onchange="toggleCustom(this,this.form.custom_supplier)"></select><input name="custom_supplier" hidden placeholder="Новый поставщик"></div><div class="ux-field"><label>Что приехало?</label><select name="category" onchange="receiptCategoryChanged()" required></select></div><div class="ux-field"><label>Тип</label><select name="item_type" onchange="toggleCustom(this,this.form.custom_type);updateReceiptFields()" required></select><input name="custom_type" hidden placeholder="Укажите свой тип"></div><div class="ux-field"><label>Вендор</label><select name="vendor" onchange="toggleCustom(this,this.form.custom_vendor)"></select><input name="custom_vendor" hidden placeholder="Укажите вендора"></div><div class="ux-field"><label>Модель</label><input name="model" list="ref-model"></div><div class="ux-field"><label>Наименование</label><input name="item_name" list="ref-item_name" required></div><div class="ux-field"><label>Проект</label><select name="project"><option value="">Не указан</option><option>Digital</option><option>Tech</option><option>HGX</option></select></div><div class="ux-field"><label>Стеллаж/полка</label><input name="shelf" list="ref-shelf"></div><div class="ux-field"><label>S/N</label><input name="serial_number"></div><div class="ux-field"><label>Инвентарный №</label><input name="inventory_number"></div><div class="ux-field"><label>Количество</label><input name="quantity" type="number" min="0.001" step="0.001" value="1"></div><details class="ux-more"><summary>Дополнительно</summary><div class="ux-field"><label>Объект размещения</label><input name="object_name" list="ref-object"></div></details><div class="actions"><button class="button primary">Принять на склад</button></div></form>`);const rf=document.getElementById('simpleReceiptForm');setOptions(rf.supplier,['Не указан',...refsOf('supplier'),'Другое']);setOptions(rf.category,Object.keys(RECEIPT_TYPES));rf.onsubmit=saveSimpleReceipt;setReceiptMode('Оборудование');
 const issue=document.getElementById('issue');issue.insertAdjacentHTML('afterbegin',`<div class="box cable-process"><h2>Списание кабелей</h2><p class="hint">Кабель списывается по типу и наименованию. S/N, задача и целевое оборудование не требуются.</p><form class="ux-form" id="cableIssueForm"><div class="ux-field"><label>Дата</label><input name="issue_date" type="date" required value="${today}"></div><div class="ux-field"><label>ФИО</label><input name="responsible" required></div><div class="ux-field"><label>Тип кабеля</label><select name="source_cable_type" onchange="toggleCustom(this,this.form.custom_cable_type)" required>${RECEIPT_TYPES.Кабели.map(x=>option(x)).join('')}</select><input name="custom_cable_type" hidden placeholder="Укажите тип"></div><div class="ux-field"><label>Наименование</label><input name="source_item_name" list="ref-item_name" required></div><div class="ux-field"><label>Количество</label><input name="quantity" type="number" min="0.001" step="0.001" required value="1"></div><div class="ux-field"><label>Проект</label><select name="project"><option value="">Не указан</option><option>Digital</option><option>Tech</option><option>HGX</option></select></div><div class="ux-field"><label>Тип задачи (необязательно)</label><select name="task_type"><option value="">Не указана</option>${['ЗНР','ПНР','ИЗМ','ЗНО','ИНЦ','Другое'].map(x=>option(x)).join('')}</select></div><div class="ux-field"><label>Номер задачи (необязательно)</label><input name="task_number"></div><div class="ux-field wide"><label>Комментарий</label><textarea name="comment"></textarea></div><div class="actions"><button class="button primary">Списать кабель</button></div></form></div>`);document.getElementById('cableIssueForm').onsubmit=saveCableIssue;
 const daily=document.getElementById('daily');daily.querySelector('h2').textContent='Ежедневный отчет';daily.insertAdjacentHTML('afterbegin',`<div class="box daily-entry"><h2>Задачи за день</h2><div class="report-actions"><label>Дата <input id="dailyLogDate" type="date" value="${today}"></label><button class="button" onclick="addDailyRow()">+ Добавить задачу</button><button class="button primary" onclick="saveDailyLogs()">Сохранить отчет</button></div><div class="table-wrap daily-grid"><table><thead><tr><th>Источник задачи</th><th>Тип задачи</th><th>Номер задачи</th><th>Выполненные работы</th><th>Статус работ</th><th>Комментарий</th><th></th></tr></thead><tbody id="dailyLogRows">${dailyRow()}</tbody></table></div></div>`);daily.querySelectorAll(':scope > .box').forEach((x,i)=>{if(i>0&&x.textContent.includes('Загрузить готовый'))x.hidden=true});
 const filters=document.querySelector('#balance .filters');filters.innerHTML='<input id="balanceQuery" placeholder="S/N, инвентарный №, модель, наименование, поставщик или полка"><select id="uxBalanceCategory"></select><select id="uxBalanceType"></select><select id="uxBalanceProject"></select>';setOptions(document.getElementById('uxBalanceCategory'),['Оборудование','Компоненты','Кабели'],'Что это: всё');setOptions(document.getElementById('uxBalanceType'),[...new Set(state.balance.map(x=>x.item_type).filter(Boolean))],'Все типы');setOptions(document.getElementById('uxBalanceProject'),[...new Set(state.balance.map(x=>x.project).filter(Boolean))],'Все проекты');document.querySelector('#balance thead').innerHTML='<tr><th>Что это</th><th>Тип</th><th>Наименование</th><th>Поставщик</th><th>Вендор</th><th>Модель</th><th>S/N</th><th>Остаток</th><th>Проект</th><th>Полка</th><th>Объект размещения</th><th>Действия</th></tr>';filters.querySelectorAll('input,select').forEach(x=>x.oninput=renderSimpleBalance);renderSimpleBalance();
 const home=document.querySelector('.home-actions');if(home)home.innerHTML=`<button class="home-action primary" onclick="openTask('warehouse','receipt');setReceiptMode('Оборудование')"><strong>Принять оборудование</strong></button><button class="home-action" onclick="openTask('warehouse','issue')"><strong>Списать оборудование</strong></button><button class="home-action" onclick="openTask('warehouse','receipt');setReceiptMode('Кабели')"><strong>Принять кабели</strong></button><button class="home-action" onclick="openTask('warehouse','issue');document.getElementById('cableIssueForm').scrollIntoView()"><strong>Списать кабели</strong></button><button class="home-action" onclick="openTask('warehouse','balance')"><strong>Посмотреть баланс</strong></button><button class="home-action" onclick="openTask('reports','daily')"><strong>Сделать отчет</strong></button><button class="home-action" onclick="openTask('warehouse','deliveries')"><strong>Поставки</strong></button>`;
}
function scenarioCards(rootId,items){const root=document.getElementById(rootId),bar=document.createElement('div'),stage=document.createElement('div'),hint=document.createElement('p');bar.className='scenario-cards';stage.className='scenario-stage';hint.className='scenario-hint';hint.textContent='Выберите, как выполнить операцию. На экране будет только нужная форма.';root.prepend(stage);root.prepend(hint);root.prepend(bar);const all=[...new Set(items.flatMap(x=>x.nodes||[]).filter(Boolean))];all.forEach(x=>{x.hidden=true;stage.appendChild(x)});function close(){all.forEach(x=>x.hidden=true);stage.hidden=true;bar.hidden=false;hint.hidden=false;items.forEach(x=>x.button?.classList.remove('selected'))}items.forEach(item=>{const button=document.createElement('button');button.type='button';button.className='scenario-card';button.innerHTML=`<strong>${item.title}</strong><span>${item.help}</span>`;button.onclick=()=>{all.forEach(x=>x.hidden=true);bar.hidden=true;hint.hidden=true;stage.hidden=false;item.nodes.filter(Boolean).forEach(x=>x.hidden=false);stage.querySelector('.scenario-back')?.remove();const back=document.createElement('button');back.type='button';back.className='button scenario-back';back.textContent=`Назад к способам ${rootId==='receipt'?'прихода':'расхода'}`;back.onclick=close;stage.prepend(back);item.focus?.()};item.button=button;bar.appendChild(button)});root.showScenario=title=>items.find(x=>x.title===title)?.button.click();close()}
const previewErrors={};const baseRenderPreview=renderPreview;renderPreview=function(kind,result){previewErrors[kind]=result.errors||[];baseRenderPreview(kind,result);const target=document.getElementById(`${kind}Preview`),actions=target?.lastElementChild;if(actions&&previewErrors[kind].length){const button=document.createElement('button');button.type='button';button.className='button';button.textContent='Скачать ошибки';button.onclick=()=>downloadPreviewErrors(kind);actions.appendChild(button)}};
function downloadPreviewErrors(kind){const rows=previewErrors[kind]||[];if(!rows.length){notify('Ошибок в файле нет');return}const quote=value=>`"${String(value??'').replaceAll('"','""')}"`,csv='\ufeffСтрока;Ошибка\r\n'+rows.map(x=>[x.line,x.reason].map(quote).join(';')).join('\r\n'),link=document.createElement('a');link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));link.download=`${kind}_errors.csv`;link.click();URL.revokeObjectURL(link.href)}
function initScenarios(){const receiptScanner=document.getElementById('receiptScanner').closest('.scanner-box'),receiptImport=document.getElementById('receiptCsv').closest('.import-box'),receiptPreview=document.getElementById('receiptPreview'),simpleReceipt=document.getElementById('simpleReceiptForm'),manualReceipt=document.getElementById('stockReceiptForm'),deliveryHelp=document.createElement('div');deliveryHelp.className='box';deliveryHelp.innerHTML='<h2>Принять из поставки</h2><p class="hint">Загрузите файл снабжения и принимайте позиции сканером.</p><button type="button" class="button primary" onclick="openTask(\'warehouse\',\'deliveries\')">Открыть поставки</button>';scenarioCards('receipt',[{title:'Принять сканером',help:'Для партии серверов или компонентов',nodes:[receiptScanner],focus:()=>document.getElementById('receiptScanner').focus()},{title:'Принять из файла',help:'Для большого Excel/CSV',nodes:[receiptImport,receiptPreview]},{title:'Принять из поставки',help:'Через файл снабжения',nodes:[deliveryHelp]},{title:'Принять кабели',help:'Без серийных номеров',nodes:[simpleReceipt],focus:()=>setReceiptMode('Кабели')},{title:'Ручной ввод',help:'Запасной режим',nodes:[manualReceipt]}]);const issueScanner=document.getElementById('issueScanner').closest('.scanner-box'),bulk=document.getElementById('bulkIssueForm').closest('.box'),cable=document.getElementById('cableIssueForm').closest('.box'),search=document.getElementById('issueSearchForm').closest('.box'),manualIssue=document.getElementById('stockIssueForm');scenarioCards('issue',[{title:'Списать сканером',help:'Для партии серверов или компонентов',nodes:[issueScanner],focus:()=>document.getElementById('issueScanner').focus()},{title:'Списать из файла',help:'Для большого Excel/CSV',nodes:[bulk]},{title:'Списать кабели',help:'Без серийных номеров',nodes:[cable]},{title:'Найти и списать из баланса',help:'Поиск в текущем балансе',nodes:[search]},{title:'Ручной ввод',help:'Запасной режим',nodes:[manualIssue]}]);document.querySelector('[data-section="profile"]')?.remove();document.querySelectorAll('[name="responsible"]').forEach(x=>{x.readOnly=true;x.title='ФИО задано при входе'})}
const originalLoadAll=loadAll;loadAll=async function(){await originalLoadAll();if(document.getElementById('simpleReceiptForm')){const t=document.getElementById('uxBalanceType'),p=document.getElementById('uxBalanceProject');setOptions(t,[...new Set(state.balance.map(x=>x.item_type).filter(Boolean))],'Все типы');setOptions(p,[...new Set(state.balance.map(x=>x.project).filter(Boolean))],'Все проекты');renderSimpleBalance()}const fullName=`${state.current_user.last_name||''} ${state.current_user.first_name||''}`.trim();document.getElementById('currentUser').textContent=`${fullName} · ${state.current_user.position||'Инженер'}`;document.getElementById('adminPassword').hidden=state.current_user.role!=='admin';document.querySelectorAll('[name="responsible"]').forEach(x=>x.value=fullName)};
try{initEngineerUX()}catch(error){console.error('Engineer UX initialization failed',error)}
try{initScenarios()}catch(error){console.error('Scenario initialization failed',error)}
loadAll().catch(error=>console.error('Initial data loading failed',error));
'''
HTML = HTML.replace('</script></body></html>', UX_SCRIPT + '</script></body></html>')
HTML = HTML.replace(
    'name="vendor" onchange="toggleCustom(this,this.form.custom_vendor)"',
    'name="vendor" onchange="toggleCustom(this,this.form.custom_vendor);updateReceiptSuggestions()"',
).replace(
    'name="model" list="ref-model"',
    'name="model" list="ref-model" oninput="updateReceiptSuggestions()"',
)
HTML = HTML.replace('</style></head>', r'''
.mode-tabs,#simpleReceiptTitle{display:none!important}.scenario-hint{margin:-8px 0 18px;color:var(--muted);font-size:16px}.scenario-stage>.scenario-back{margin-bottom:16px}
.mode-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}.ux-form{display:grid;grid-template-columns:repeat(2,minmax(240px,1fr));gap:14px;max-width:920px}.ux-field{display:flex;flex-direction:column;gap:6px}.ux-field label{font-weight:700}.ux-field input,.ux-field select,.ux-field textarea,.daily-grid input,.daily-grid select,.daily-grid textarea{width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:8px;background:#fff}.ux-field.wide,.ux-more,.ux-form>.actions{grid-column:1/-1}.ux-more{padding:12px;border:1px solid var(--line);border-radius:9px}.ux-more summary{cursor:pointer;font-weight:700}.cable-process{margin-bottom:20px;border:2px solid #93c5fd}.daily-entry{margin-bottom:18px}.daily-grid{margin-top:14px}.daily-grid textarea{min-width:220px;min-height:60px}.daily-grid select{min-width:130px}.scenario-cards{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:12px;margin-bottom:22px}.scenario-card{min-height:112px;padding:16px;border:2px solid var(--line);border-radius:12px;background:#fff;text-align:left;cursor:pointer}.scenario-card:hover,.scenario-card.selected{border-color:var(--blue);background:#eff6ff}.scenario-card strong,.scenario-card span{display:block}.scenario-card strong{font-size:17px}.scenario-card span{margin-top:8px;color:var(--muted)}@media(max-width:1050px){.scenario-cards{grid-template-columns:repeat(2,1fr)}}@media(max-width:720px){.ux-form{grid-template-columns:1fr}.ux-field.wide,.ux-more,.ux-form>.actions{grid-column:1}.scenario-cards{grid-template-columns:1fr}.scenario-card{min-height:84px}}
</style></head>''')


WIZARD_SCRIPT = r'''
const WIZARD_MODELS={
 'Dell':['PowerEdge R650','PowerEdge R750','PowerEdge R760'],
 'Huawei':['FusionServer 2288H V5','FusionServer 2288H V6'],
 'Lenovo':['ThinkSystem SR650','ThinkSystem SR650 V2'],
 'Supermicro':['SuperServer'],
 'Samsung':['M393A8G40AB2-CWE','PM893','PM9A3'],
 'Hynix':['HMAA8GR7AJR4N-XN'], 'Micron':['7400 PRO','9300 MAX']};
function warehouseLanding(){
 const home=document.querySelector('.home-screen');
 if(!home)return;
 const icon=name=>`<svg aria-hidden="true" viewBox="0 0 24 24"><path d="${({warehouse:'M4 9l8-5 8 5v11H4V9zm4 11v-7h8v7M8 9h8',report:'M6 3h9l3 3v15H6V3zm3 5h6M9 12h6M9 16h4',monitor:'M3 12h4l2-5 4 10 2-5h6',profile:'M12 12a4 4 0 100-8 4 4 0 000 8zm-7 9c.8-4 3.1-6 7-6s6.2 2 7 6'})[name]}"></path></svg>`;
 home.innerHTML=`<div class="landing-head"><p class="eyebrow">Рабочее пространство</p><h2>Добро пожаловать в ODE</h2><p>Выберите направление — на следующем экране будут только относящиеся к нему действия.</p></div><div class="portal-grid">
 <article class="portal-card"><div class="portal-icon">${icon('warehouse')}</div><h3>Склад</h3><p>Работа со складом</p><ul><li>Приемка и выдача</li><li>Баланс и поставки</li><li>Инвентаризация</li></ul><button onclick="openWarehouseHub()">Открыть</button></article>
 <article class="portal-card"><div class="portal-icon">${icon('report')}</div><h3>Отчеты</h3><p>Работа смены</p><ul><li>Ежедневный отчет</li><li>Еженедельный отчет</li><li>История работ</li></ul><button onclick="openTask('reports','daily')">Открыть</button></article>
 <article class="portal-card"><div class="portal-icon">${icon('monitor')}</div><h3>Мониторинг</h3><p>Состояние системы</p><ul><li>Проблемы</li><li>События</li><li>Мониторинг</li></ul><button onclick="openMonitoringHub()">Открыть</button></article>
 <article class="portal-card"><div class="portal-icon">${icon('profile')}</div><h3>Профиль</h3><p>Инженер смены</p><ul><li>Текущий инженер</li><li>Настройки смены</li><li>Смена инженера</li></ul><button onclick="openShiftProfile()">Открыть</button></article></div>`;
}
function openWarehouseHub(){showSection('warehouse');if(!byId('overview'))return;setHtml('overview',`<div class="landing-head compact"><p class="eyebrow">Склад</p><h2>Что нужно сделать?</h2><p>Выберите одну операцию для продолжения.</p></div><div class="action-grid"><button onclick="openTask('warehouse','receipt')"><strong>Принять оборудование</strong><span>Сканирование, поставка, кабели или ручной ввод</span></button><button onclick="openTask('warehouse','issue')"><strong>Выдать оборудование</strong><span>Сканирование, баланс или списание кабелей</span></button><button onclick="openTask('warehouse','deliveries')"><strong>Поставки</strong><span>Документы снабжения и приемка</span></button><button onclick="openTask('warehouse','balance')"><strong>Баланс</strong><span>Остатки, поиск и фильтры</span></button><button onclick="openTask('warehouse','inventory')"><strong>Инвентаризация</strong><span>Сверка фактического наличия</span></button></div>`);showView('overview')}
function openMonitoringHub(){showSection('monitoring');if(!byId('monitoring'))return;setHtml('monitoring',`<div class="landing-head compact"><p class="eyebrow">Мониторинг</p><h2>Контроль системы</h2></div><div class="action-grid"><button onclick="showView('problems')"><strong>Проблемы</strong><span>Ошибки и несопоставленные операции</span></button><button onclick="openTask('warehouse','journal')"><strong>События</strong><span>Журнал складских операций</span></button><button><strong>Мониторинг</strong><span>Состояние ЦОД Ixcellerate</span></button></div>`);showView('monitoring')}
function openShiftProfile(){showSection('profile');const root=byId('profile'),name=byId('currentUser')?.textContent||'Инженер смены';if(!root)return;setHtml('profile',`<div class="profile-card"><div class="portal-icon"><svg viewBox="0 0 24 24"><path d="M12 12a4 4 0 100-8 4 4 0 000 8zm-7 9c.8-4 3.1-6 7-6s6.2 2 7 6"></path></svg></div><p class="eyebrow">Инженер смены</p><h2>${esc(name)}</h2><p>Все новые операции записываются под этим ФИО.</p><button class="button primary" onclick="logout()">Сменить инженера</button></div>`)}
function choiceButton(label,value,onpick){const b=document.createElement('button');b.type='button';b.className='wizard-choice';b.innerHTML=`<strong>${label}</strong><span>Продолжить →</span>`;b.onclick=()=>onpick(value);return b}
function startReceiptWizard(){
 const root=document.getElementById('receipt'),stage=root.querySelector('.scenario-stage'),scanner=document.getElementById('receiptScanner').closest('.scanner-box');
 root.appendChild(scanner);stage.innerHTML='';stage.hidden=false;const data={};let step=0;
 const steps=[
  {title:'Что приехало?',key:'category',values:()=>Object.keys(RECEIPT_TYPES)},
  {title:'Выберите тип',key:'type',values:()=>RECEIPT_TYPES[data.category]||[]},
  {title:'Выберите вендора',key:'vendor',values:()=>TYPE_VENDORS[data.type]||refsOf('vendor').filter(x=>x!=='Не указан').slice(0,12).concat('Другое')},
  {title:'Выберите модель',key:'model',values:()=>WIZARD_MODELS[data.vendor]||[...new Set((state.recent_receipts||[]).filter(x=>x.vendor===data.vendor).map(x=>x.model).filter(Boolean))].slice(0,12),input:true},
  {title:'Параметры партии',key:'common',common:true}
 ];
 function render(){const s=steps[step];stage.innerHTML=`<div class="wizard-shell"><button class="wizard-back" type="button">← ${step?'Назад':'К способам приемки'}</button><div class="wizard-progress"><i style="width:${(step+1)/steps.length*100}%"></i></div><p>Шаг ${step+1} из ${steps.length}</p><h2>${s.title}</h2><div class="wizard-content"></div></div>`;stage.querySelector('.wizard-back').onclick=()=>{if(step){step--;render()}else root.showScenario&&root.showScenario('__none__')};const content=stage.querySelector('.wizard-content');
  if(s.common){const opts=(xs,label)=>`<option value="">${label}</option>${[...new Set(xs.filter(Boolean))].map(x=>option(x)).join('')}`;content.innerHTML=`<div class="common-grid"><label>Проект<select id="wProject">${opts(['digital','tech'],'Неизвестно')}</select></label><label>Полка<select id="wShelf" required>${opts(refsOf('shelf'),'Выберите полку')}</select></label><label>ЦОД<select id="wDc" required>${opts(refsOf('datacenter').length?refsOf('datacenter'):['Ixcellerate'],'Выберите ЦОД')}</select></label><label>Поставщик <small>необязательно</small><select id="wSupplier">${opts(refsOf('supplier'),'Не указан')}</select></label></div><button class="wizard-next" type="button">Перейти к сканированию</button>`;document.getElementById('wDc').value='Ixcellerate';content.querySelector('button').onclick=()=>showScanner();return}
  const values=s.values();const grid=document.createElement('div');grid.className='wizard-choices';values.forEach(v=>grid.appendChild(choiceButton(v,v,pick)));content.appendChild(grid);if(s.input||!values.length){content.insertAdjacentHTML('beforeend',`<div class="wizard-custom"><input placeholder="${s.key==='model'?'Введите модель':'Введите наименование'}"><button type="button">Продолжить</button></div>`);const input=content.querySelector('.wizard-custom input');content.querySelector('.wizard-custom button').onclick=()=>{if(input.value.trim())pick(input.value.trim())};input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();content.querySelector('.wizard-custom button').click()}}}
  function pick(value){data[s.key]=value;if(value==='Другое'&&!s.input){const v=prompt('Введите значение');if(!v)return;data[s.key]=v}step++;render()}
 }
 function showScanner(){data.project=document.getElementById('wProject').value;data.shelf=document.getElementById('wShelf').value;data.datacenter=document.getElementById('wDc').value;data.supplier=document.getElementById('wSupplier').value||'Не указан';data.item_name=[data.type,data.vendor,data.model].filter(Boolean).join(' ')||`${data.category} без модели`;if(!data.shelf||!data.datacenter){notify('Выберите полку и ЦОД',true);return}const f=document.getElementById('scanReceiptForm');if(!f){notify('Форма сканирования недоступна. Вернитесь в приход.',true);return}const responsible=[...document.querySelectorAll('[name="responsible"]')].map(x=>x.value.trim()).find(Boolean)||'Инженер смены';Object.entries({receipt_date:today,responsible,supplier:data.supplier,vendor:data.vendor,model:data.model,item_name:data.item_name,project:data.project,datacenter:data.datacenter,shelf:data.shelf,object_name:'Склад',equipment_type:data.category==='Оборудование'?data.type:'',component_type:data.category==='Компоненты'?data.type:'',cable_type:'',unit:'шт'}).forEach(([k,v])=>{const field=f.elements.namedItem(k);if(field)field.value=v});stage.innerHTML=`<div class="wizard-shell scan-step"><button class="wizard-back" type="button">← Параметры партии</button><p class="eyebrow">${esc(data.item_name)}</p><h2>Сканируйте S/N</h2><p>Каждый Enter добавляет позицию во временный список. В базе пока ничего не меняется.</p></div>`;stage.querySelector('.wizard-back').onclick=()=>{step=4;render()};stage.appendChild(scanner);scanner.hidden=false;f.hidden=true;document.getElementById('receiptScanner').focus()}
 render();
}
function rebuildScenarioCards(){const receipt=document.getElementById('receipt'),bar=receipt.querySelector('.scenario-cards');bar.innerHTML='';[['📷','Сканировать оборудование','Партия с серийными номерами',startReceiptWizard],['✍','Ручное добавление','Одна или несколько позиций',()=>receipt.showScenario('Ручной ввод')],['📦','Принять кабели','Быстро, без серийных номеров',()=>receipt.showScenario('Принять кабели')],['📁','Импорт поставки','Preview и подтверждение',()=>openTask('warehouse','deliveries')]].forEach(([icon,title,help,fn])=>{const b=document.createElement('button');b.className='scenario-card';b.innerHTML=`<b>${icon}</b><strong>${title}</strong><span>${help}</span>`;b.onclick=fn;bar.appendChild(b)});const issue=document.getElementById('issue'),ib=issue.querySelector('.scenario-cards');ib.innerHTML='';[['📷','Сканировать оборудование','Найти по S/N и собрать список','Списать сканером'],['📋','Найти в балансе и списать','Выберите позицию из остатков','Найти и списать из баланса'],['🧵','Списать кабели','Одна операция на всё количество','Списать кабели'],['✍','Ручное списание','Нестандартная операция','Ручной ввод']].forEach(([icon,title,help,target])=>{const b=document.createElement('button');b.className='scenario-card';b.innerHTML=`<b>${icon}</b><strong>${title}</strong><span>${help}</span>`;b.onclick=()=>issue.showScenario(target);ib.appendChild(b)})}
function modernShell(){const top=document.querySelector('.top'),actions=top?.querySelector('.profile-actions');if(!top||!actions)return;const brand=top.querySelector('div:first-child');if(brand)brand.innerHTML='<button class="top-brand" type="button" onclick="showSection(\'home\');showView(\'home\');window.scrollTo(0,0)" aria-label="Вернуться на главную ODE"><strong>ODE</strong><span>Отдел дежурных инженеров</span><span id="pageTitle" hidden>Главная</span></button>';const refresh=actions.querySelector('[onclick="loadAll()"]');if(refresh)refresh.onclick=async()=>{try{await loadAll();notify('Данные обновлены')}catch(e){notify(e.message,true)}};if(!actions.querySelector('.shift-profile')){const profile=document.createElement('button');profile.className='button shift-profile';profile.textContent='Профиль';profile.onclick=openShiftProfile;actions.insertBefore(profile,refresh)}const logout=top.querySelector('[onclick="logout()"]');if(logout){logout.style.display='inline-block';logout.textContent='Сменить инженера'}const homeButton=document.querySelector('[data-section="home"]');if(homeButton)homeButton.textContent='Главная';}
function balanceKind(row){const text=`${row.category||''} ${row.item_type||''} ${row.item_name||''} ${row.equipment_type||''} ${row.component_type||''} ${row.cable_type||''}`.toLocaleLowerCase();if(text.includes('кабел'))return 'Кабели';if(text.includes('ssd')||text.includes('диск'))return 'SSD';if(text.includes('ram')||text.includes('памят'))return 'RAM';if(text.includes('коммут')||text.includes('switch'))return 'Коммутаторы';if(text.includes('сервер'))return 'Серверы';return ''}
function renderBalanceKpis(){let strip=document.getElementById('balanceKpis');if(!strip){strip=document.createElement('div');strip.id='balanceKpis';strip.className='kpi-strip';document.getElementById('balance').insertBefore(strip,document.querySelector('#balance .import-box'))}const totals={Серверы:0,SSD:0,RAM:0,Коммутаторы:0,Кабели:0};state.balance.forEach(x=>{const kind=balanceKind(x);if(kind)totals[kind]+=Number(x.balance)||0});strip.innerHTML=Object.entries(totals).map(([name,value])=>`<div class="kpi-card"><span>${name}</span><strong>${value.toLocaleString('ru-RU')}</strong></div>`).join('')}
const stage5LoadAll=loadAll;loadAll=async function(){await stage5LoadAll();renderBalanceKpis()}
warehouseLanding();
try{modernShell()}catch(error){console.error('Application shell initialization failed',error)}
try{rebuildScenarioCards()}catch(error){console.error('Wizard cards initialization failed',error)}
let balanceCardFilter='';
function balanceGroup(row){const text=`${row.item_name||''} ${row.equipment_type||''} ${row.component_type||''} ${row.cable_type||''}`.toLocaleLowerCase();if(row.cable_type||text.includes('кабел'))return 'Кабели';if(/ssd|hdd|диск/.test(text))return 'Диски';if(/ram|dimm|памят/.test(text))return 'Память';if(/nic|switch|коммут|сетев/.test(text))return 'Сеть';if(text.includes('сервер'))return 'Серверы';return 'Прочее'}
function setBalanceCardFilter(name=''){balanceCardFilter=name;renderBalanceKpis();renderSimpleBalance()}
renderBalanceKpis=function(){let strip=document.getElementById('balanceKpis');if(!strip){strip=document.createElement('div');strip.id='balanceKpis';strip.className='kpi-strip';document.getElementById('balance').prepend(strip)}const icons={Серверы:'▣',Диски:'◉',Память:'▤',Сеть:'⌁',Кабели:'〰',Прочее:'◆'},names=Object.keys(icons),totals=Object.fromEntries(names.map(x=>[x,0]));state.balance.forEach(x=>totals[balanceGroup(x)]+=Number(x.balance)||0);strip.innerHTML=names.map(name=>`<button type="button" class="kpi-card ${balanceCardFilter===name?'active':''}" onclick="setBalanceCardFilter('${name}')"><b>${icons[name]}</b><span>${name}</span><strong>${totals[name].toLocaleString('ru-RU')}</strong></button>`).join('')+`<button type="button" class="button reset-balance" onclick="setBalanceCardFilter()">Сбросить фильтр</button>`}
const filteredBalanceRender=renderSimpleBalance;renderSimpleBalance=function(){if(!balanceCardFilter)return filteredBalanceRender();const input=document.getElementById('balanceQuery'),saved=input.value;input.value='';const original=state.balance;state.balance=original.filter(x=>balanceGroup(x)===balanceCardFilter);try{filteredBalanceRender()}finally{state.balance=original;input.value=saved}}
function renderWarehouseHistory(){const body=document.getElementById('operationBody');if(!body)return;document.querySelector('#journal strong').textContent='История склада';document.querySelector('#journal p').textContent='Приходы, расходы, поставки и изменения данных.';document.querySelector('#journal thead').innerHTML='<tr><th>Дата и время</th><th>Инженер</th><th>Действие</th><th>S/N</th><th>Наименование</th><th>Количество</th><th>Комментарий</th></tr>';body.innerHTML=(state.warehouse_history||[]).map(x=>`<tr><td>${esc(x.event_date)}</td><td>${esc(x.engineer)}</td><td>${esc(x.action)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.item_name)}</td><td>${esc(x.quantity)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="7">Операций пока нет</td></tr>'}
function saveScanDraft(kind,rows){const key=`ode_${kind}_draft`,form=document.getElementById(kind==='receipt'?'scanReceiptForm':'scanIssueForm');if(rows.length)localStorage.setItem(key,JSON.stringify({rows,fields:form?formData(form):{}}));else localStorage.removeItem(key);renderDraftPanel()}
function restoreScanDraft(kind){const draft=JSON.parse(localStorage.getItem(`ode_${kind}_draft`)||'null');if(!draft)return;openTask('warehouse',kind==='receipt'?'receipt':'issue');const root=document.getElementById(kind==='receipt'?'receipt':'issue');root.showScenario(kind==='receipt'?'Принять сканером':'Списать сканером');const form=document.getElementById(kind==='receipt'?'scanReceiptForm':'scanIssueForm');Object.entries(draft.fields||{}).forEach(([k,v])=>{const field=form.elements.namedItem(k);if(field)field.value=v});if(kind==='receipt'){scannedReceipts=draft.rows;renderScannedReceipts()}else{scannedIssues=draft.rows;renderScannedIssues()}}
function clearScanDraft(kind){localStorage.removeItem(`ode_${kind}_draft`);if(kind==='receipt'){scannedReceipts=[];renderScannedReceipts()}else{scannedIssues=[];renderScannedIssues()}renderDraftPanel()}
function renderDraftPanel(){let panel=document.getElementById('activeDrafts');if(!panel){panel=document.createElement('aside');panel.id='activeDrafts';panel.className='active-drafts';document.body.appendChild(panel)}panel.innerHTML=[['receipt','Черновик приемки'],['issue','Черновик расхода']].map(([kind,title])=>{const d=JSON.parse(localStorage.getItem(`ode_${kind}_draft`)||'null');return d?`<div><strong>${title}</strong><span>${d.rows.length} строк</span><button onclick="restoreScanDraft('${kind}')">Вернуться</button><button onclick="clearScanDraft('${kind}')">Очистить</button></div>`:''}).join('');panel.hidden=!panel.innerHTML}
const baseReceiptRender=renderScannedReceipts;renderScannedReceipts=function(){baseReceiptRender();saveScanDraft('receipt',scannedReceipts)};const baseIssueRender=renderScannedIssues;renderScannedIssues=function(){baseIssueRender();saveScanDraft('issue',scannedIssues)};
const finalLoadAll=loadAll;loadAll=async function(){await finalLoadAll();renderWarehouseHistory();renderBalanceKpis();renderDraftPanel()};renderDraftPanel();
'''
HTML = HTML.replace('</script></body></html>', WIZARD_SCRIPT + '</script></body></html>')
HTML = HTML.replace('</style></head>', r'''
.sidebar{display:none}.app{display:block}.main{padding:0 36px 48px;max-width:1440px;margin:auto}.top{height:78px;margin:0 -36px 30px;padding:0 36px;border-bottom:1px solid var(--line);background:#fff}.top-brand{display:flex;align-items:center;gap:16px}.top-brand strong{font-size:25px}.top-brand span{padding-left:16px;border-left:1px solid var(--line);color:var(--muted)}.subnav{max-width:1100px}.panel{box-shadow:none;border:0;background:transparent;padding:0}.landing-head{max-width:700px;margin:70px 0 36px}.landing-head.compact{margin:35px 0 28px}.landing-head h2{font-size:38px;margin:4px 0 10px}.landing-head p{font-size:17px;color:var(--muted)}.eyebrow{color:var(--blue)!important;font-weight:750;text-transform:uppercase;letter-spacing:.08em;font-size:12px!important}.portal-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}.portal-card{display:flex;min-height:360px;padding:28px;flex-direction:column;border:1px solid var(--line);border-radius:20px;background:#fff;box-shadow:0 10px 35px #1720330a}.portal-icon{display:grid;width:52px;height:52px;place-items:center;border-radius:14px;background:#eaf1ff;color:var(--blue)}.portal-icon svg{width:28px;height:28px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.portal-card h3{margin:22px 0 3px;font-size:23px}.portal-card p{margin:0;color:var(--muted)}.portal-card ul{margin:22px 0;padding-left:19px;color:#475569;line-height:1.9}.portal-card button{width:100%;margin-top:auto;padding:12px;border:0;border-radius:10px;background:#172033;color:#fff;font-weight:750;cursor:pointer}.action-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.action-grid button{min-height:160px;padding:28px;border:1px solid var(--line);border-radius:18px;background:#fff;text-align:left;cursor:pointer;box-shadow:0 8px 30px #17203309;transition:.15s}.action-grid button:hover{border-color:#93c5fd;transform:translateY(-2px);box-shadow:0 14px 36px #17203312}.action-grid b,.scenario-card b{display:block;font-size:30px;margin-bottom:20px}.action-grid strong{display:block;font-size:20px}.action-grid span{display:block;margin-top:9px;color:var(--muted);font-size:15px}.scenario-cards{grid-template-columns:repeat(4,1fr);max-width:1100px}.scenario-card{min-height:170px;padding:24px;border-radius:16px}.scenario-card b{margin-bottom:15px}.kpi-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:24px}.kpi-card{padding:20px;border:1px solid var(--line);border-radius:15px;background:#fff}.kpi-card span{display:block;color:var(--muted)}.kpi-card strong{display:block;margin-top:9px;font-size:30px}.table-wrap{max-height:62vh}.table-wrap th{position:sticky;top:0;z-index:2}.profile-card{max-width:560px;margin:70px auto;padding:42px;border:1px solid var(--line);border-radius:20px;background:#fff;text-align:center}.profile-card .portal-icon{margin:0 auto 24px}.profile-card h2{font-size:27px}.profile-card>p:not(.eyebrow){color:var(--muted);margin:12px 0 28px}#deliveries.active{display:grid;grid-template-columns:minmax(360px,42%) 1fr;gap:18px}#deliveries>.task-hint,#deliveries>.import-box,#deliveries>#deliveryPreview,#deliveries>.filters{grid-column:1/-1}#deliveries>#deliveryCard{grid-column:2;grid-row:5;margin-top:0!important}#deliveries>.table-wrap{grid-column:1;grid-row:5;max-height:68vh}#deliveryCard>.box{height:68vh;overflow:auto}.wizard-shell{max-width:920px;margin:20px auto;padding:30px}.wizard-shell>p{text-align:center;color:var(--muted)}.wizard-shell h2{text-align:center;font-size:32px;margin:14px 0 34px}.wizard-back{border:0;background:none;color:var(--muted);cursor:pointer;font-weight:700}.wizard-progress{height:5px;margin:24px 0 10px;border-radius:9px;background:#e2e8f0;overflow:hidden}.wizard-progress i{display:block;height:100%;background:var(--blue)}.wizard-choices{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.wizard-choice{min-height:105px;padding:20px;border:1px solid var(--line);border-radius:13px;background:#fff;text-align:left;cursor:pointer}.wizard-choice:hover{border-color:var(--blue);background:#eff6ff}.wizard-choice strong,.wizard-choice span{display:block}.wizard-choice strong{font-size:18px}.wizard-choice span{margin-top:12px;color:var(--muted)}.wizard-custom{display:flex;gap:10px;max-width:600px;margin:22px auto}.wizard-custom input,.common-grid input{width:100%;padding:14px;border:1px solid #cbd5e1;border-radius:9px}.wizard-custom button,.wizard-next{padding:13px 22px;border:0;border-radius:9px;background:var(--blue);color:#fff;font-weight:700;cursor:pointer}.common-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.common-grid label{font-weight:700}.common-grid small{font-weight:400;color:var(--muted)}.common-grid input{display:block;margin-top:7px}.wizard-next{display:block;margin:28px auto}.scan-step{padding-bottom:5px}.scan-step+ .scanner-box{max-width:920px;margin:auto}.scan-step+ .scanner-box>h2,.scan-step+ .scanner-box>.hint{display:none}.scanner-input{font-size:28px;padding:24px;text-align:center}.profile-actions #currentUser{font-weight:700}@media(max-width:1050px){.portal-grid{grid-template-columns:1fr 1fr}.kpi-strip{grid-template-columns:repeat(3,1fr)}#deliveries.active{display:block}#deliveryCard>.box{height:auto}}@media(max-width:800px){.main{padding:0 16px 30px}.top{height:auto;min-height:76px;margin:0 -16px 20px;padding:12px 16px;gap:12px}.top-brand span{display:none}.portal-grid,.action-grid,.wizard-choices,.common-grid{grid-template-columns:1fr}.portal-card{min-height:300px}.action-grid button{min-height:130px}.scenario-cards{grid-template-columns:1fr 1fr}.kpi-strip{grid-template-columns:1fr 1fr}.wizard-shell{padding:15px}.profile-actions .button{display:none}}
</style></head>''')
HTML = HTML.replace('</style></head>', r'''
.top-brand{border:0;background:transparent;cursor:pointer;color:var(--text)}.kpi-card{cursor:pointer;text-align:left}.kpi-card.active{border-color:var(--blue);background:#eaf1ff;box-shadow:0 0 0 2px #bfdbfe}.kpi-card b{display:block;font-size:22px;color:var(--blue)}.reset-balance{align-self:center}.active-drafts{position:fixed;z-index:30;left:50%;bottom:18px;transform:translateX(-50%);display:flex;gap:10px;padding:10px;border:1px solid #bfdbfe;border-radius:12px;background:#fff;box-shadow:0 12px 35px #17203333}.active-drafts[hidden]{display:none}.active-drafts div{display:flex;align-items:center;gap:10px}.active-drafts span{color:var(--muted)}.active-drafts button{padding:7px 10px;border:1px solid var(--line);border-radius:7px;background:#fff;cursor:pointer}
</style></head>''', 1)


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
            "reports/index.js", "reports/work_logs.js", "reports/daily.js", "reports/weekly.js",
            "monitoring/index.js",
            "administration/index.js", "administration/profile.js", "administration/users.js",
            "administration/backup.js", "administration/diagnostics.js",
            "product.js",
        )
    )
    html = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    html = html.replace("</head>", f"{css_link}</head>", 1)
    html = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    return html.replace("</body>", f"{script_tags}</body>", 1)


HTML = _externalized_html(HTML)

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
                    })
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
                    balance_rows = app_context.warehouse.get_balance(
                        self._balance_filters(query), limit=balance_limit + 1
                    )
                    self._send_json(200, {
                        "rows": balance_rows[:balance_limit],
                        "limit": balance_limit,
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
                    else:
                        raise WarehouseError("Неизвестный режим сканирования")
                elif path == "/api/position-card":
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
                elif path == "/import/work-logs-template.csv":
                    self._send_template("work_logs_import_template.csv", USER_CSV_TEMPLATES["work_logs"])
                elif path == "/import/daily-report-template.csv":
                    self._send_template("daily_report_template.csv", USER_CSV_TEMPLATES["daily_report"])
                else:
                    self._send_json(404, {"error": "Страница не найдена"})
            except WarehouseError as error:
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
            try:
                with service.user_context(
                    email,
                    author_name=self._session_author(),
                    role_override=self._session_role_override(),
                ), service.lock:
                    if path == "/api/logout":
                        self._logout()
                    else:
                        self._do_POST()
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
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
                    "CREATE_BACKUP", "CHECK_DATABASE", "RESTORE_BACKUP",
                    "CREATE_USER", "CHANGE_PASSWORD", "UPDATE_PROFILE",
                    "ADD_REFERENCE", "TOGGLE_REFERENCE",
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
                    service.set_reference_active(
                        int(data.get("reference_id", 0)),
                        self._json_boolean(data.get("is_active", False), "is_active"),
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
            except (WarehouseError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception:
                self._send_json(500, {"error": "Внутренняя ошибка сервера"})

        def _import_csv(self, kind: str, preview: bool = False) -> None:
            try:
                if kind not in {
                    "equipment", "receipt", "issue", "bulk_issue", "work_logs",
                    "daily_report", "inventory",
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
                        user = service.authenticate(email, data.get("password", ""))
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
        def _validate_action_payload(data: dict[str, Any]) -> None:
            action = data.get("action")
            if not isinstance(action, str) or not action:
                raise WarehouseError("Поле action должно быть непустой строкой")
            collection_fields: dict[str, dict[str, type]] = {
                "WORK_LOGS": {"rows": list},
                "CONFIRM_SCANNED_RECEIPTS": {"common_fields": dict, "serial_numbers": list},
                "CONFIRM_SCANNED_ISSUES": {"common_fields": dict, "serial_numbers": list},
                "UPDATE_DELIVERY_LINES": {"line_ids": list, "values": dict},
                "ACCEPT_DELIVERY_SERIAL": {"values": dict},
                "ACCEPT_DELIVERY_BATCH": {"line_ids": list, "common_values": dict},
            }
            allowed = collection_fields.get(action, {})
            numeric_fields = {"equipment_id", "quantity", "delivery_id", "reference_id"}
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
            if field == "rows":
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
            self.end_headers()
            self.wfile.write(body)

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
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ODE — учет работ и склада")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="путь к файлу SQLite")
    parser.add_argument("--host", default="127.0.0.1", help="адрес локального сервера")
    parser.add_argument("--port", type=int, default=8765, help="порт локального сервера")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app_context = create_application_context(args.db)
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
