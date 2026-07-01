"""Локальный веб-интерфейс ODE без внешних зависимостей."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import secrets
import tempfile
import threading
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from .db import DEFAULT_DB_PATH
from .service import WarehouseError, WarehouseService


CURRENT_DATACENTER = "Ixcellerate"

LOGIN_HTML = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Вход — ODE</title>
<style>body{margin:0;background:#f4f7fb;color:#172033;font:14px system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(390px,calc(100% - 32px));padding:28px;background:white;border:1px solid #dce3ec;border-radius:14px;box-shadow:0 8px 24px #1720330d}h1{margin:0 0 5px}p{color:#667085}label{display:block;margin-top:15px;font-weight:650}input{width:100%;box-sizing:border-box;margin-top:6px;padding:10px;border:1px solid #cbd5e1;border-radius:8px}button{width:100%;margin-top:20px;padding:10px;border:0;border-radius:8px;background:#2563eb;color:white;font-weight:700}.error{color:#991b1b}</style></head><body><form class="card" id="login"><h1>ODE</h1><p>Отдел дежурных инженеров</p><label>Email<input name="email" autocomplete="username" required autofocus></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button>Войти</button><p class="error" id="error"></p></form><script>document.getElementById('login').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const x=await r.json();if(r.ok)location.href='/';else document.getElementById('error').textContent=x.error||'Ошибка входа'};</script></body></html>'''


HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ODE — учет работ и склада</title>
<style>
:root{--bg:#f4f7fb;--surface:#fff;--text:#172033;--muted:#667085;--line:#dce3ec;--blue:#2563eb;--nav:#172033;--shadow:0 8px 24px #1720330d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}.app{min-height:100vh;display:grid;grid-template-columns:230px 1fr}.sidebar{padding:22px 14px;background:var(--nav);color:#fff}.brand{padding:4px 10px 24px}.brand strong{display:block;font-size:20px}.brand span{display:block;margin-top:5px;color:#aab6ca;font-size:12px}.section-button{width:100%;margin:4px 0;padding:15px;border:0;border-radius:10px;background:transparent;color:#cbd5e1;text-align:left;font-weight:700;cursor:pointer}.section-button:hover,.section-button.active{background:#25324a;color:#fff}.main{min-width:0;padding:22px}.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.top h1{margin:0;font-size:23px}.button{display:inline-block;padding:9px 13px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--text);text-decoration:none;cursor:pointer}.button.primary{border-color:var(--blue);background:var(--blue);color:#fff}.subnav{display:flex;gap:4px;margin-bottom:14px;padding:7px;background:#fff;border:1px solid var(--line);border-radius:11px;overflow:auto}.subtab{padding:10px 14px;border:0;border-radius:7px;background:transparent;color:var(--muted);font-weight:650;white-space:nowrap;cursor:pointer}.subtab.active{background:#eaf1ff;color:#1d4ed8}.view{display:none}.view.active{display:block}.panel{padding:20px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:var(--shadow)}h2{margin:0 0 5px;font-size:19px}.hint{margin:0 0 18px;color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{padding:18px;border:1px solid var(--line);border-radius:11px;background:#fff}.card span{display:block;color:var(--muted)}.card strong{display:block;margin-top:8px;font-size:30px}.form{max-width:820px;display:grid;grid-template-columns:170px 1fr;gap:11px 16px;align-items:center}.form label{font-weight:650}.form input,.form select,.form textarea,.filters input,.filters select{width:100%;padding:9px 10px;border:1px solid #cbd5e1;border-radius:7px;background:#fff}.form textarea{min-height:75px;resize:vertical}.actions{grid-column:2;display:flex;gap:8px;flex-wrap:wrap}.split{display:grid;grid-template-columns:1fr 1fr;gap:18px}.box{padding:16px;border:1px solid var(--line);border-radius:10px}.box h3{margin:0 0 14px}.import-box{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px;padding:14px;border:1px solid #bfdbfe;border-radius:10px;background:#eff6ff}.import-box p{margin:3px 0 0;color:var(--muted)}.import-actions,.report-actions{display:flex;gap:8px;flex-wrap:wrap}.file-input{position:absolute;width:1px;height:1px;opacity:0}.filters{display:grid;grid-template-columns:1fr 1fr auto auto;gap:9px;margin-bottom:13px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:10px 12px;border-bottom:1px solid #edf1f6;text-align:left}th{background:#f8fafc;font-size:12px}.empty{padding:28px;text-align:center;color:var(--muted)}.badge{padding:3px 7px;border-radius:12px;background:#eaf1ff;color:#1d4ed8}.placeholder{padding:55px 20px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:10px}.instruction li{margin:8px 0}.status{position:fixed;right:20px;bottom:20px;max-width:430px;padding:12px 16px;border-radius:8px;background:#172033;color:#fff;opacity:0;transform:translateY(10px);transition:.2s;pointer-events:none}.status.show{opacity:1;transform:none}.status.error{background:#991b1b}
@media(max-width:950px){.cards{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
@media(max-width:720px){.app{display:block}.sidebar{padding:10px;position:sticky;top:0;z-index:5}.brand{display:none}.section-nav{display:flex;gap:5px}.section-button{margin:0;padding:11px 10px;text-align:center}.main{padding:12px}.top{display:none}.form{grid-template-columns:1fr}.actions{grid-column:1}.filters{grid-template-columns:1fr}.cards{grid-template-columns:1fr 1fr}.import-box{align-items:stretch;flex-direction:column}.panel{padding:14px}}
</style></head><body><div class="app">
<aside class="sidebar"><div class="brand"><strong>ODE</strong><span>Отдел дежурных инженеров</span></div><nav class="section-nav">
<button class="section-button active" data-section="warehouse">Склад __DATACENTER__</button><button class="section-button" data-section="reports">Отчеты __DATACENTER__</button><button class="section-button" data-section="monitoring">Мониторинг __DATACENTER__</button>
</nav></aside>
<main class="main"><header class="top"><div><h1>ODE</h1><span class="hint">Отдел дежурных инженеров · ЦОД __DATACENTER__</span></div><div><span id="currentUser"></span> <button class="button" onclick="loadAll()">Обновить</button> <button class="button" onclick="logout()">Выйти</button></div></header><nav class="subnav" id="subnav"></nav>

<section class="view panel" id="overview"><h2>Обзор склада</h2><p class="hint">Текущее движение и остаток оборудования.</p><div class="cards"><div class="card"><span>Приход</span><strong id="statReceipts">0</strong></div><div class="card"><span>Расход</span><strong id="statIssues">0</strong></div><div class="card"><span>Остаток</span><strong id="statBalance">0</strong></div><div class="card"><span>Позиций</span><strong id="statPositions">0</strong></div></div></section>

<section class="view panel" id="receipt"><div class="import-box"><div><strong>Расширенный приход из CSV</strong><p>Файл до 50 МБ проверяется и записывается одной транзакцией.</p></div><div class="import-actions"><a class="button" href="/import/receipt-template.csv">Шаблон</a><a class="button" href="/export/receipt.csv">Выгрузить</a><label class="button primary" for="receiptCsv">Загрузить</label><input class="file-input csv-input" id="receiptCsv" data-kind="receipt" type="file" accept=".csv"></div></div><h2>Оформить приход</h2><p class="hint">Выберите ровно один тип: оборудование, компонент или кабель.</p><form class="form" id="stockReceiptForm"><label>Дата</label><input name="receipt_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Дата заказа</label><input name="order_date" type="date"><label>Заявка №</label><input name="request_number"><label>Заказ №</label><input name="order_number"><label>PLU</label><input name="plu"><label>Наименование</label><input name="item_name" required><label>Проект</label><select name="project" class="ref-select" data-kind="project" data-optional="1"></select><label>S/N</label><input name="serial_number"><label>Инв. №</label><input name="inventory_number"><label>Поставщик</label><select name="supplier" class="ref-select" data-kind="supplier" required></select><label>Вендор</label><select name="vendor" class="ref-select" data-kind="vendor" required></select><label>Модель</label><input name="model"><label>Стеллаж/Полка</label><input name="shelf"><label>Объект</label><select name="object_name" class="ref-select" data-kind="object" required></select><label>ЦОД</label><input name="datacenter" value="Ixcellerate" required><label>Тип оборудования</label><select name="equipment_type" class="ref-select" data-kind="equipment_type" data-optional="1"></select><label>Тип компонента</label><select name="component_type" class="ref-select" data-kind="component_type" data-optional="1"></select><label>Тип кабеля</label><select name="cable_type" class="ref-select" data-kind="cable_type" data-optional="1"></select><label>Единица учета</label><select name="unit" class="ref-select" data-kind="unit" required></select><label>Кол-во / метраж</label><input name="quantity" type="number" min="0.001" step="0.001" value="1" required><div class="actions"><button class="button primary">Зарегистрировать приход</button></div></form></section>

<section class="view panel" id="issue"><div class="import-box"><div><strong>Расширенный расход из CSV</strong><p>Оборудование — по S/N; кабель — по наименованию и типу.</p></div><div class="import-actions"><a class="button" href="/import/issue-template.csv">Шаблон</a><a class="button" href="/export/issue.csv">Выгрузить</a><label class="button primary" for="issueCsv">Загрузить</label><input class="file-input csv-input" id="issueCsv" data-kind="issue" type="file" accept=".csv"></div></div><h2>Оформить расход</h2><p class="hint">Для кабеля оставьте S/N пустым. Тип и номер задачи для кабеля необязательны.</p><form class="form" id="stockIssueForm"><label>Дата</label><input name="issue_date" type="date" required><label>ФИО</label><input name="responsible" required><label>Тип задачи</label><select name="task_type" id="issueTaskType"></select><label>Номер задачи</label><input name="task_number"><label>SN целевого объекта</label><input name="target_serial_number"><label>Hostname</label><input name="target_hostname"><label>S/N списываемого</label><input name="source_serial_number"><label>Наименование кабеля</label><input name="source_item_name"><label>Тип кабеля</label><select name="source_cable_type" class="ref-select" data-kind="cable_type" data-optional="1"></select><label>Кол-во / метраж</label><input name="quantity" type="number" min="0.001" step="0.001" value="1" required><label>Комментарий</label><textarea name="comment"></textarea><div class="actions"><button class="button primary">Зарегистрировать расход</button></div></form></section>

<section class="view panel" id="balance"><div class="import-box"><div><strong>Баланс новой складской модели</strong><p>Приход минус расход; полка не участвует в расчете.</p></div><a class="button" id="balanceExport" href="/export/balance.csv">Выгрузить CSV</a></div><div class="filters"><select id="balanceProject"></select><select id="balanceObject"></select><select id="balanceEquipmentType"></select><select id="balanceComponentType"></select><select id="balanceCableType"></select><select id="balanceUnit"></select><select id="balanceDatacenter"></select><button class="button" onclick="clearBalanceFilters()">Сбросить</button></div><div class="table-wrap"><table><thead><tr><th>Проект</th><th>Наименование</th><th>Модель</th><th>SN</th><th>Инв.№</th><th>Остаток</th><th>Ед.</th><th>Стеллаж/Полка</th><th>Объект</th><th>Тип оборудования</th><th>Тип компонента</th><th>Тип кабеля</th><th>ЦОД</th></tr></thead><tbody id="balanceBody"></tbody></table></div></section>

<section class="view panel" id="equipment"><div class="import-box"><div><strong>Карточки оборудования из CSV</strong><p>UTF-8 BOM и Windows-1251 поддерживаются.</p></div><div class="import-actions"><a class="button" href="/import/equipment-template.csv">Шаблон</a><label class="button primary" for="equipmentCsv">Загрузить</label><input class="file-input csv-input" id="equipmentCsv" data-kind="equipment" type="file" accept=".csv"></div></div><div class="split"><div class="box"><h3>Новая карточка</h3><form class="form" id="addForm"><label>Категория</label><select name="category" class="categories" required></select><label>Модель</label><input name="model" required><label>Серийный номер</label><input name="serial_number" required><label>Инвентарный номер</label><input name="inventory_number" required><label>ЦОД</label><input name="datacenter" value="Ixcellerate" required><label>Место</label><select name="location_code" class="locations" required></select><label>Начальный остаток</label><input name="quantity" type="number" min="0" value="0"><div class="actions"><button class="button primary">Создать</button></div></form></div><div class="box"><h3>Перемещение</h3><form class="form" id="moveForm"><label>Оборудование</label><select name="equipment_id" class="items" required></select><label>Новое место</label><select name="destination" class="locations" required></select><label>Основание</label><input name="basis" required><label>Ответственный</label><input name="responsible" value="Кладовщик № 1" required><div class="actions"><button class="button primary">Переместить</button></div></form></div></div></section>

<section class="view panel" id="journal"><div class="import-box"><div><strong>Журнал складских операций</strong><p>Последние 100 записей.</p></div><div class="import-actions"><a class="button" href="/export/stock.csv">Остатки CSV</a><a class="button" href="/export/log.csv">Журнал CSV</a></div></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Операция</th><th>Инв. №</th><th>Модель</th><th>Кол-во</th><th>Основание</th><th>Ответственный</th><th>Откуда → куда</th></tr></thead><tbody id="operationBody"></tbody></table></div></section>

<section class="view panel" id="references"><h2>Справочники</h2><p class="hint">Значения сгруппированы по типу; отключение не удаляет старые данные.</p><div class="filters"><select id="referenceFilter"><option value="">Все справочники</option></select><span></span><span></span><span></span></div><form class="filters" id="referenceForm"><select name="kind" id="referenceKind"></select><input name="name" placeholder="Новое значение" required><button class="button primary">Добавить в выбранный справочник</button><span></span></form><div class="table-wrap"><table><thead><tr><th>Справочник</th><th>Значение</th><th>Состояние</th><th>Действие</th></tr></thead><tbody id="referenceBody"></tbody></table></div></section>

<section class="view panel" id="admin"><h2>Администрирование</h2><p class="hint">Доступно только администраторам.</p><div class="split"><div class="box"><h3>Backup и проверка</h3><div class="import-actions"><button class="button primary" onclick="createBackup()">Создать backup</button><button class="button" onclick="checkDatabase()">Проверить базу</button></div><p id="integrityResult" class="hint" style="margin-top:14px">Проверка еще не выполнялась.</p></div><div class="box"><h3>Восстановление</h3><p class="hint">Перед восстановлением автоматически создается страховочный backup.</p><select id="restoreBackup" style="width:100%;padding:9px;margin-bottom:10px"></select><button class="button" style="color:#991b1b" onclick="restoreBackup()">Восстановить backup</button></div><div class="box"><h3>Загрузить базу в прод</h3><p class="hint">Текущая база будет сохранена; при ошибке выполнится откат.</p><label class="button" for="prodDb">Выбрать SQLite .db</label><input class="file-input" id="prodDb" type="file" accept=".db"></div><div class="box"><h3>Новый пользователь</h3><form class="form" id="userForm"><label>Имя</label><input name="first_name" required><label>Фамилия</label><input name="last_name" required><label>Должность</label><input name="position" required><label>Email</label><input name="email" required><label>Пароль</label><input name="password" type="password" minlength="6" required><label>Роль</label><select name="role"><option>engineer</option><option>viewer</option><option>admin</option></select><div class="actions"><button class="button primary">Создать</button></div></form></div></div><h3>Пользователи</h3><div class="table-wrap"><table><thead><tr><th>ФИО</th><th>Должность</th><th>Email</th><th>Роль</th></tr></thead><tbody id="userBody"></tbody></table></div><h3>Доступные backup-файлы</h3><div class="table-wrap"><table><thead><tr><th>Файл</th><th>Дата изменения</th><th>Размер</th></tr></thead><tbody id="backupBody"></tbody></table></div><h3 style="margin-top:22px">Единый аудит</h3><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Действие</th><th>Сущность</th><th>ID</th><th>Автор</th><th>Детали</th></tr></thead><tbody id="auditBody"></tbody></table></div></section>

<section class="view panel instruction" id="instruction"><h2>Инструкция</h2><p class="hint">Правила учета Этапа 2.</p><ul><li>В приходе выберите ровно один классификатор: тип оборудования, тип компонента или тип кабеля.</li><li>S/N обязателен для оборудования и компонентов. Они учитываются и списываются в штуках.</li><li>Оборудование и компоненты списываются только по S/N и обязательно на задачу. Компоненту также требуется S/N целевого оборудования.</li><li>Оборудование нельзя списать само на себя.</li><li>Кабель списывается по наименованию и типу кабеля, учитывается в метрах и может не иметь задачи, проекта и S/N.</li><li>Стеллаж/полка хранится для поиска, но не используется при подборе остатка.</li><li>Проект и остальные реквизиты расхода подтягиваются из прихода.</li><li>Перед импортом скачайте актуальный CSV-шаблон. При ошибке весь файл откатывается; сообщение содержит номер строки и причину.</li></ul></section>

<section class="view panel" id="daily"><h2>Ежедневные отчеты</h2><div class="box"><h3>1. Сформировать отчет из базы</h3><p class="hint">Логи работ, приход и расход остаются в текущей модели.</p><form class="filters" id="dailyForm"><input name="date_from" type="date" required><input name="date_to" type="date" required><button class="button primary">Сформировать отчет</button><button class="button" type="button" id="downloadDaily">Скачать CSV</button></form></div><div class="box" style="margin-top:16px"><h3>2. Загрузить готовый CSV отчет</h3><div class="import-actions"><a class="button" href="/import/daily-report-template.csv">Шаблон</a><label class="button primary" for="dailyCsv">Загрузить CSV</label><input class="file-input csv-input" id="dailyCsv" data-kind="daily_report" type="file" accept=".csv"><select id="uploadedReport"></select><button class="button" onclick="showUploadedReport()">Показать</button><button class="button" onclick="exportUploadedReport()">Экспорт</button></div></div><div style="height:16px"></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Блок</th><th>Номер задачи</th><th>Описание / наименование</th><th>Кол-во / метраж</th><th>S/N</th><th>ФИО</th><th>Комментарий / основание</th></tr></thead><tbody id="dailyBody"><tr><td class="empty" colspan="8">Выберите источник отчета</td></tr></tbody></table></div></section>

<section class="view panel" id="worklogs"><div class="import-box"><div><strong>CSV логов работ</strong><p>Источник, тип и номер задачи хранятся отдельно.</p></div><div class="import-actions"><a class="button" href="/import/work-logs-template.csv">Шаблон</a><a class="button" id="exportWorkLogs" href="/export/work-logs.csv">Выгрузить</a><label class="button primary" for="workLogsCsv">Загрузить</label><input class="file-input csv-input" id="workLogsCsv" data-kind="work_logs" type="file" accept=".csv"></div></div><div class="split"><div class="box"><h3>Новый лог работы</h3><form class="form" id="workLogForm"><label>Дата</label><input name="work_date" type="date" required><label>Источник задачи</label><select name="task_source" id="taskSource" required></select><label>Тип задачи</label><select name="task_type" id="taskType" required></select><label>Номер задачи</label><input name="task_number" placeholder="123" required><label>Описание работы</label><textarea name="description" required></textarea><label>Статус</label><select name="status" id="workStatus" required></select><label>Комментарий</label><textarea name="comment"></textarea><div class="actions"><button class="button primary">Добавить лог</button></div></form></div><div class="box"><h3>Фильтр периода</h3><form class="form" id="workLogFilter"><label>Дата начала</label><input name="date_from" type="date"><label>Дата окончания</label><input name="date_to" type="date"><div class="actions"><button class="button primary">Применить</button><button class="button" type="button" onclick="clearWorkLogFilter()">Сбросить</button></div></form></div></div><div style="height:18px"></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Источник</th><th>Задача</th><th>Описание</th><th>Статус</th><th>Комментарий</th></tr></thead><tbody id="workLogBody"></tbody></table></div></section>

<section class="view panel" id="shipments"><h2>Учет поставок-отправок</h2><div class="placeholder">В разработке. Здесь будет учет взаимодействия со снабжением, поставками, отправками и будущая выгрузка/внесение данных в DCIM</div></section><section class="view panel" id="profile"><h2>Профиль</h2><p id="profileInfo" class="hint"></p><form class="form" id="passwordForm"><label>Текущий пароль</label><input name="old_password" type="password" required><label>Новый пароль</label><input name="new_password" type="password" minlength="6" required><div class="actions"><button class="button primary">Сменить пароль</button></div></form></section><section class="view panel" id="kaiten"><h2>Kaiten</h2><div class="placeholder">Интеграция будет реализована позднее.</div></section><section class="view panel" id="weekly"><h2>Еженедельный отчет</h2><div class="placeholder">В разработке</div></section><section class="view panel" id="monitoring"><h2>Мониторинг __DATACENTER__</h2><div class="placeholder">В разработке</div></section>
</main></div><div class="status" id="status"></div>
<script>
let sections={warehouse:[['overview','Обзор'],['receipt','Приход'],['issue','Расход'],['balance','Баланс'],['equipment','Оборудование'],['journal','Журнал'],['shipments','Учет поставок-отправок'],['references','Справочники'],['admin','Администрирование'],['instruction','Инструкция'],['profile','Профиль']],reports:[['daily','Ежедневные отчеты'],['worklogs','Логи работ'],['kaiten','Kaiten'],['weekly','Еженедельный отчет']],monitoring:[['monitoring','В разработке']]};
let state={equipment:[],operations:[],categories:[],locations:[],stats:{},task_sources:[],task_types:[],work_log_statuses:[],references:[],reference_kinds:{},stock_receipts:[],stock_issues:[],balance:[],daily_report_uploads:[],current_user:{}};let currentSection='warehouse';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const option=(value,label=value)=>`<option value="${esc(value)}">${esc(label)}</option>`;
function notify(message,error=false){const x=document.getElementById('status');x.textContent=message;x.className='status show'+(error?' error':'');clearTimeout(x.timer);x.timer=setTimeout(()=>x.className='status',4000)}
async function request(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(data.error||'Ошибка запроса');return data}
function showSection(name){currentSection=name;document.querySelectorAll('.section-button').forEach(x=>x.classList.toggle('active',x.dataset.section===name));const nav=document.getElementById('subnav');nav.innerHTML=sections[name].map((x,i)=>`<button class="subtab ${i?'':'active'}" data-view="${x[0]}">${x[1]}</button>`).join('');nav.querySelectorAll('button').forEach(x=>x.onclick=()=>showView(x.dataset.view));showView(sections[name][0][0])}
function showView(id){document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.subtab').forEach(x=>x.classList.toggle('active',x.dataset.view===id));if(id==='worklogs')loadWorkLogs();if(id==='admin')loadAdmin()}
document.querySelectorAll('.section-button').forEach(x=>x.onclick=()=>showSection(x.dataset.section));
function fillSelects(){const items=state.equipment.map(x=>option(x.id,`${x.inventory_number} — ${x.model} (${x.quantity})`)).join('');const refs=kind=>state.references.filter(v=>v.kind===kind&&v.is_active).map(v=>v.name);const fill=(id,label,values)=>document.getElementById(id).innerHTML=option('',label)+[...new Set(values.filter(Boolean))].map(v=>option(v)).join('');document.querySelectorAll('.items').forEach(x=>x.innerHTML=items);document.querySelectorAll('.categories').forEach(x=>x.innerHTML=state.categories.map(v=>option(v.name)).join(''));document.querySelectorAll('.locations').forEach(x=>x.innerHTML=state.locations.map(v=>option(v.code,`${v.code} — ${v.name}`)).join(''));fill('balanceProject','Все проекты',refs('project'));fill('balanceObject','Все объекты',refs('object'));fill('balanceEquipmentType','Все типы оборудования',refs('equipment_type'));fill('balanceComponentType','Все типы компонентов',refs('component_type'));fill('balanceCableType','Все типы кабеля',refs('cable_type'));fill('balanceUnit','Все единицы',refs('unit'));fill('balanceDatacenter','Все ЦОД',state.balance.map(v=>v.datacenter));document.getElementById('taskSource').innerHTML=refs('task_source').map(v=>option(v)).join('');document.getElementById('taskType').innerHTML=refs('task_type').map(v=>option(v)).join('');document.getElementById('workStatus').innerHTML=refs('work_log_status').map(v=>option(v)).join('');document.getElementById('issueTaskType').innerHTML=option('','Без задачи (только кабель)')+refs('task_type').map(v=>option(v)).join('');document.querySelectorAll('.ref-select').forEach(x=>{const values=refs(x.dataset.kind);x.innerHTML=(x.dataset.optional?option('','Не выбрано'):'')+values.map(v=>option(v)).join('')});const kinds=Object.entries(state.reference_kinds).map(([k,v])=>option(k,v)).join('');document.getElementById('referenceKind').innerHTML=kinds;document.getElementById('referenceFilter').innerHTML=option('','Все справочники')+kinds;document.getElementById('uploadedReport').innerHTML=state.daily_report_uploads.map(x=>option(x.id,`${x.filename} — ${x.uploaded_at} (${x.row_count})`)).join('');renderReferences()}
function renderReferences(){const selected=document.getElementById('referenceFilter').value;const groups=Object.entries(state.reference_kinds).filter(([kind])=>!selected||kind===selected);document.getElementById('referenceBody').innerHTML=groups.map(([kind,label])=>{const rows=state.references.filter(x=>x.kind===kind);return `<tr><th colspan="4">${esc(label)}</th></tr>`+rows.map(x=>`<tr><td>${esc(label)}</td><td>${esc(x.name)}</td><td>${x.is_active?'Активно':'Отключено'}</td><td>${state.current_user.role==='viewer'?'—':`<button class="button" onclick="toggleReference(${x.id},${x.is_active?0:1})">${x.is_active?'Отключить':'Включить'}</button>`}</td></tr>`).join('')}).join('')||'<tr><td class="empty" colspan="4">Нет значений</td></tr>'}
document.getElementById('referenceFilter').oninput=renderReferences;
const balanceFilterMap={balanceProject:'project',balanceObject:'object_name',balanceEquipmentType:'equipment_type',balanceComponentType:'component_type',balanceCableType:'cable_type',balanceUnit:'unit',balanceDatacenter:'datacenter'};function activeBalanceFilters(){return Object.fromEntries(Object.entries(balanceFilterMap).map(([id,key])=>[key,document.getElementById(id).value]).filter(x=>x[1]))}function renderBalance(){const filters=activeBalanceFilters();const rows=state.balance.filter(x=>Object.entries(filters).every(([k,v])=>x[k]===v));document.getElementById('balanceBody').innerHTML=rows.map(x=>`<tr><td>${esc(x.project)}</td><td>${esc(x.item_name)}</td><td>${esc(x.model)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.inventory_number)}</td><td>${Number(x.balance).toLocaleString('ru-RU')}</td><td>${esc(x.unit)}</td><td>${esc(x.shelf)}</td><td>${esc(x.object_name)}</td><td>${esc(x.equipment_type)}</td><td>${esc(x.component_type)}</td><td>${esc(x.cable_type)}</td><td>${esc(x.datacenter)}</td></tr>`).join('')||'<tr><td class="empty" colspan="13">Нет данных</td></tr>';document.getElementById('balanceExport').href='/export/balance.csv?'+new URLSearchParams(filters)}
function renderOperations(){const names={ADD:'Карточка',RECEIPT:'Приход',ISSUE:'Расход',MOVE:'Перемещение'};document.getElementById('operationBody').innerHTML=state.operations.map(x=>`<tr><td>${esc(x.operation_date)}</td><td>${names[x.operation_type]||x.operation_type}</td><td>${esc(x.inventory_number)}</td><td>${esc(x.model)}</td><td>${x.quantity}</td><td>${esc(x.basis)}</td><td>${esc(x.responsible)}</td><td>${esc(x.from_location||'—')} → ${esc(x.to_location||'—')}</td></tr>`).join('')}
async function loadAll(){try{state=await request('/api/data');for(const [key,id] of [['receipts','statReceipts'],['issues','statIssues'],['balance','statBalance'],['positions','statPositions']])document.getElementById(id).textContent=Number(state.stats[key]).toLocaleString('ru-RU');document.getElementById('currentUser').textContent=`${state.current_user.first_name} ${state.current_user.last_name} · ${state.current_user.role}`;document.getElementById('profileInfo').textContent=`${state.current_user.first_name} ${state.current_user.last_name}, ${state.current_user.position}, ${state.current_user.email}`;if(state.current_user.role!=='admin'){sections.warehouse=sections.warehouse.filter(x=>x[0]!=='admin');if(document.querySelector('[data-view=admin]'))showSection(currentSection)}if(state.current_user.role==='viewer'){for(const id of ['stockReceiptForm','stockIssueForm','addForm','moveForm','workLogForm','referenceForm','passwordForm']){const x=document.getElementById(id);if(x&&id!=='passwordForm')x.style.display='none'}document.querySelectorAll('.csv-input').forEach(x=>x.closest('.import-actions')?.querySelector('label')?.remove())}fillSelects();renderBalance();renderOperations();if(state.current_user.must_change_password)notify('Рекомендуется сменить пароль по умолчанию в разделе «Профиль»')}catch(e){notify(e.message,true)}}
function formData(form){return Object.fromEntries(new FormData(form).entries())}
async function submitAction(form,action){try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...formData(form),action})});notify('Операция выполнена');if(action==='WORK_LOG'){form.querySelector('[name=description]').value='';form.querySelector('[name=comment]').value='';form.querySelector('[name=task_number]').value='';await loadWorkLogs()}await loadAll()}catch(e){notify(e.message,true)}}
document.getElementById('stockReceiptForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'STOCK_RECEIPT')};document.getElementById('stockIssueForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'STOCK_ISSUE')};document.getElementById('addForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'ADD')};document.getElementById('moveForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'MOVE')};document.getElementById('workLogForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'WORK_LOG')};document.getElementById('referenceForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'ADD_REFERENCE')};async function toggleReference(reference_id,is_active){try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'TOGGLE_REFERENCE',reference_id,is_active:Boolean(is_active)})});await loadAll();notify('Справочник обновлен')}catch(e){notify(e.message,true)}}
async function importCsv(input){const file=input.files[0];if(!file)return;try{const r=await request(`/api/import-csv?kind=${input.dataset.kind}`,{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});notify(`Загружено строк: ${r.imported}`);await loadAll();if(input.dataset.kind==='work_logs')await loadWorkLogs();if(input.dataset.kind==='daily_report'&&r.upload_id){document.getElementById('uploadedReport').value=r.upload_id;await showUploadedReport()}}catch(e){notify(e.message,true)}finally{input.value=''}}document.querySelectorAll('.csv-input').forEach(x=>x.onchange=()=>importCsv(x));
async function loadWorkLogs(){const f=formData(document.getElementById('workLogFilter'));const q=new URLSearchParams(f);try{const data=await request('/api/work-logs?'+q);document.getElementById('workLogBody').innerHTML=data.logs.map(x=>`<tr><td>${esc(x.work_date)}</td><td>${esc(x.task_source)}</td><td>${esc(x.full_task_name)}</td><td>${esc(x.description)}</td><td><span class="badge">${esc(x.status)}</span></td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="6">Нет логов за период</td></tr>';document.getElementById('exportWorkLogs').href='/export/work-logs.csv?'+q}catch(e){notify(e.message,true)}}
document.getElementById('workLogFilter').onsubmit=e=>{e.preventDefault();loadWorkLogs()};function clearWorkLogFilter(){document.getElementById('workLogFilter').reset();loadWorkLogs()}
function renderDaily(rows){document.getElementById('dailyBody').innerHTML=rows.map(x=>`<tr><td>${esc(x.date)}</td><td>${esc(x.report_block)}</td><td>${esc(x.task_number)}</td><td>${esc(x.description)}</td><td>${esc(x.quantity)}</td><td>${esc(x.serial_number)}</td><td>${esc(x.responsible)}</td><td>${esc(x.comment)}</td></tr>`).join('')||'<tr><td class="empty" colspan="8">Нет данных за период</td></tr>'}
async function buildDaily(){const q=new URLSearchParams(formData(document.getElementById('dailyForm')));try{const data=await request('/api/daily-report?'+q);renderDaily(data.rows)}catch(e){notify(e.message,true)}}document.getElementById('dailyForm').onsubmit=e=>{e.preventDefault();buildDaily()};document.getElementById('downloadDaily').onclick=()=>{const f=document.getElementById('dailyForm');if(!f.reportValidity())return;location.href='/export/daily-report.csv?'+new URLSearchParams(formData(f))};
async function showUploadedReport(){const id=document.getElementById('uploadedReport').value;if(!id)return;try{renderDaily((await request(`/api/uploaded-daily-report?id=${id}`)).rows)}catch(e){notify(e.message,true)}}function exportUploadedReport(){const id=document.getElementById('uploadedReport').value;if(id)location.href=`/export/uploaded-daily-report.csv?id=${id}`}
for(const id of Object.keys(balanceFilterMap))document.getElementById(id).oninput=renderBalance;function clearBalanceFilters(){for(const id of Object.keys(balanceFilterMap))document.getElementById(id).value='';renderBalance()}
let adminState={backups:[],audit:[],users:[]};const sizeText=n=>n<1024?`${n} Б`:n<1048576?`${(n/1024).toFixed(1)} КБ`:`${(n/1048576).toFixed(1)} МБ`;async function loadAdmin(){try{adminState=await request('/api/admin');document.getElementById('backupBody').innerHTML=adminState.backups.map(x=>`<tr><td>${esc(x.name)}</td><td>${esc(x.modified)}</td><td>${sizeText(x.size)}</td></tr>`).join('')||'<tr><td class="empty" colspan="3">Backup-файлов нет</td></tr>';document.getElementById('restoreBackup').innerHTML=adminState.backups.map(x=>option(x.name,`${x.name} — ${x.modified}`)).join('');document.getElementById('userBody').innerHTML=adminState.users.map(x=>`<tr><td>${esc(x.last_name)} ${esc(x.first_name)}</td><td>${esc(x.position)}</td><td>${esc(x.email)}</td><td>${esc(x.role)}</td></tr>`).join('');document.getElementById('auditBody').innerHTML=adminState.audit.map(x=>`<tr><td>${esc(x.event_date)}</td><td>${esc(x.action)}</td><td>${esc(x.entity_type)}</td><td>${esc(x.entity_id)}</td><td>${esc(x.author)}</td><td>${esc(x.details)}</td></tr>`).join('')||'<tr><td class="empty" colspan="6">Записей аудита нет</td></tr>'}catch(e){notify(e.message,true)}}async function createBackup(){try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'CREATE_BACKUP'})});notify(`Backup создан: ${x.backup.name}`);await loadAdmin()}catch(e){notify(e.message,true)}}async function checkDatabase(){try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'CHECK_DATABASE'})});const r=x.integrity;document.getElementById('integrityResult').textContent=r.ok?'База исправна. integrity_check: ok':`Обнаружена ошибка: ${r.messages.join('; ')}. Отсутствуют: ${r.missing_tables.join(', ')||'нет'}`;await loadAdmin()}catch(e){notify(e.message,true)}}async function restoreBackup(){const filename=document.getElementById('restoreBackup').value;if(!filename){notify('Нет выбранного backup-файла',true);return}if(!confirm(`Восстановить базу из ${filename}?\n\nТекущее состояние будет предварительно сохранено в отдельный backup.`))return;try{const x=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'RESTORE_BACKUP',filename,confirmed:true})});notify(`База восстановлена. Страховочный backup: ${x.restore.safety_backup}`);await loadAll();await loadAdmin()}catch(e){notify(e.message,true)}}
document.getElementById('userForm').onsubmit=e=>{e.preventDefault();submitAction(e.currentTarget,'CREATE_USER').then(loadAdmin)};document.getElementById('passwordForm').onsubmit=async e=>{e.preventDefault();try{await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...formData(e.currentTarget),action:'CHANGE_PASSWORD'})});e.currentTarget.reset();notify('Пароль изменен');await loadAll()}catch(x){notify(x.message,true)}};document.getElementById('prodDb').onchange=async e=>{const file=e.target.files[0];if(!file||!confirm(`Загрузить ${file.name} в прод? Будет создан страховочный backup.`))return;try{const x=await request('/api/upload-prod-db?confirmed=1',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file});notify(`База заменена. Backup: ${x.safety_backup}`);await loadAll();await loadAdmin()}catch(x){notify(x.message,true)}finally{e.target.value=''}};async function logout(){await request('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.href='/'}
const today=new Date().toISOString().slice(0,10);document.querySelector('[name=work_date]').value=today;document.querySelector('[name=receipt_date]').value=today;document.querySelector('[name=issue_date]').value=today;document.querySelector('#dailyForm [name=date_from]').value=today;document.querySelector('#dailyForm [name=date_to]').value=today;showSection('warehouse');loadAll();
</script></body></html>'''
HTML = HTML.replace("__DATACENTER__", CURRENT_DATACENTER).replace(
    'value="Ixcellerate"', f'value="{CURRENT_DATACENTER}"'
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
    "quantity": "Кол-во / метраж",
}
BALANCE_HEADERS = {
    "project": "Проект", "item_name": "Наименование", "model": "Модель",
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


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _localized(rows: list[dict[str, Any]], headers: dict[str, str]) -> list[dict[str, Any]]:
    return [{headers[key]: row.get(key, "") for key in headers} for row in rows]


def make_handler(service: WarehouseService) -> type[BaseHTTPRequestHandler]:
    sessions: dict[str, str] = {}
    sessions_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            email = self._session_email()
            if not email:
                if urlparse(self.path).path == "/":
                    self._send(200, LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._send_json(401, {"error": "Требуется вход"})
                return
            try:
                with service.user_context(email), service.lock:
                    self._do_GET()
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_GET(self) -> None:
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            try:
                if path == "/":
                    self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/data":
                    self._send_json(200, {
                        "stats": service.dashboard_stats(), "equipment": service.equipment(),
                        "operations": service.operation_log(limit=100),
                        "categories": service.reference_data("categories"),
                        "locations": service.reference_data("locations"),
                        "task_sources": list(service.TASK_SOURCES),
                        "task_types": list(service.TASK_TYPES),
                        "work_log_statuses": list(service.WORK_LOG_STATUSES),
                        "references": service.references(),
                        "reference_kinds": service.REFERENCE_KINDS,
                        "stock_receipts": service.stock_receipts(),
                        "stock_issues": service.stock_issue_rows(),
                        "balance": service.stock_balance(),
                        "daily_report_uploads": service.daily_report_uploads(),
                        "current_user": service.current_user(),
                    })
                elif path == "/api/work-logs":
                    self._send_json(200, {"logs": service.work_logs(
                        self._query(query, "date_from"), self._query(query, "date_to")
                    )})
                elif path == "/api/daily-report":
                    self._send_json(200, {"rows": service.daily_report(
                        self._query(query, "date_from"), self._query(query, "date_to")
                    )})
                elif path == "/api/balance":
                    self._send_json(200, {"rows": service.stock_balance(**self._balance_filters(query))})
                elif path == "/api/admin":
                    self._send_json(200, {
                        "backups": service.list_backups(),
                        "audit": service.audit_entries(),
                        "users": service.users(),
                    })
                elif path == "/api/uploaded-daily-report":
                    self._send_json(200, {"rows": service.uploaded_daily_report(
                        int(self._query(query, "id") or "0")
                    )})
                elif path == "/export/stock.csv":
                    self._send_csv("equipment_stock.csv", service.equipment())
                elif path == "/export/log.csv":
                    self._send_csv("operation_log.csv", service.operation_log(limit=None))
                elif path == "/export/receipt.csv":
                    self._send_csv(
                        "receipt_operations.csv",
                        _localized(service.stock_receipts(), RECEIPT_HEADERS),
                    )
                elif path == "/export/issue.csv":
                    self._send_csv(
                        "issue_operations.csv",
                        _localized(service.stock_issue_rows(), ISSUE_HEADERS),
                    )
                elif path == "/export/work-logs.csv":
                    rows = service.work_logs(
                        self._query(query, "date_from"), self._query(query, "date_to")
                    )
                    self._send_csv("work_logs.csv", _localized(rows, WORK_LOG_HEADERS))
                elif path == "/export/daily-report.csv":
                    rows = service.daily_report(
                        self._query(query, "date_from"), self._query(query, "date_to")
                    )
                    self._send_csv("daily_report.csv", _localized(rows, REPORT_HEADERS))
                elif path == "/export/uploaded-daily-report.csv":
                    rows = service.uploaded_daily_report(int(self._query(query, "id") or "0"))
                    self._send_csv("uploaded_daily_report.csv", _localized(rows, REPORT_HEADERS))
                elif path == "/export/balance.csv":
                    rows = service.stock_balance(**self._balance_filters(query))
                    self._send_csv("stock_balance.csv", _localized(rows, BALANCE_HEADERS))
                elif path == "/import/equipment-template.csv":
                    self._send_template("equipment_import_template.csv", "Категория;Модель;Серийный номер;Инвентарный номер;ЦОД;Место;Количество;Примечание\r\n")
                elif path == "/import/receipt-template.csv":
                    self._send_template(
                        "receipt_import_template.csv", ";".join(RECEIPT_HEADERS.values()) + "\r\n"
                    )
                elif path == "/import/issue-template.csv":
                    self._send_template(
                        "issue_import_template.csv",
                        "Дата;ФИО;Тип задачи;Номер задачи;SN целевого объекта;"
                        "Hostname целевого оборудования;Кол-во / метраж;"
                        "S/N списываемого;Наименование;Тип кабеля;Комментарий\r\n",
                    )
                elif path == "/import/work-logs-template.csv":
                    self._send_template("work_logs_import_template.csv", "Дата;Источник задачи;Тип задачи;Номер задачи;Описание работы;Статус;Комментарий\r\n")
                elif path == "/import/daily-report-template.csv":
                    self._send_template(
                        "daily_report_template.csv", ";".join(REPORT_HEADERS.values()) + "\r\n"
                    )
                else:
                    self._send_json(404, {"error": "Страница не найдена"})
            except WarehouseError as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                self._send_json(500, {"error": str(error)})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/login":
                self._login()
                return
            email = self._session_email()
            if not email:
                self._send_json(401, {"error": "Требуется вход"})
                return
            try:
                with service.user_context(email), service.lock:
                    if path == "/api/logout":
                        self._logout()
                    else:
                        self._do_POST()
            except WarehouseError as error:
                self._send_json(403, {"error": str(error)})

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/import-csv":
                self._import_csv(self._query(parse_qs(parsed.query), "kind") or "equipment")
                return
            if parsed.path == "/api/upload-prod-db":
                self._upload_prod_database(
                    self._query(parse_qs(parsed.query), "confirmed") == "1"
                )
                return
            if parsed.path != "/api/action":
                self._send_json(404, {"error": "Страница не найдена"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise WarehouseError("Некорректный размер запроса")
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                action = data.get("action")
                response: dict[str, Any] = {"ok": True}
                if action in {"RECEIPT", "ISSUE"}:
                    method = service.receipt if action == "RECEIPT" else service.issue
                    method(int(data["equipment_id"]), int(data["quantity"]), data.get("basis", ""), data.get("responsible", ""))
                elif action == "MOVE":
                    service.move(int(data["equipment_id"]), data.get("destination", ""), data.get("basis", ""), data.get("responsible", ""))
                elif action == "ADD":
                    service.add_equipment(data.get("category", ""), data.get("model", ""), data.get("serial_number", ""), data.get("inventory_number", ""), data.get("location_code", ""), int(data.get("quantity", 0)), "Создание карточки", "Кладовщик № 1", "", data.get("datacenter", "Ixcellerate"))
                elif action == "WORK_LOG":
                    service.add_work_log(data.get("work_date", ""), data.get("task_source", ""), data.get("task_type", ""), data.get("task_number", ""), data.get("description", ""), data.get("status", ""), data.get("comment", ""))
                elif action == "STOCK_RECEIPT":
                    service.add_stock_receipt(**data)
                elif action == "STOCK_ISSUE":
                    service.add_stock_issue(**data)
                elif action == "ADD_REFERENCE":
                    service.add_reference(data.get("kind", ""), data.get("name", ""))
                elif action == "TOGGLE_REFERENCE":
                    service.set_reference_active(int(data.get("reference_id", 0)), bool(data.get("is_active")))
                elif action == "CREATE_BACKUP":
                    response["backup"] = service.create_backup()
                elif action == "CHECK_DATABASE":
                    response["integrity"] = service.check_integrity()
                elif action == "RESTORE_BACKUP":
                    response["restore"] = service.restore_backup(
                        data.get("filename", ""), bool(data.get("confirmed"))
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
                else:
                    raise WarehouseError("Неизвестная операция")
                self._send_json(200, response)
            except (WarehouseError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                self._send_json(500, {"error": str(error)})

        def _import_csv(self, kind: str) -> None:
            try:
                if kind not in {"equipment", "receipt", "issue", "work_logs", "daily_report"}:
                    raise WarehouseError("Неизвестный тип CSV-импорта")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise WarehouseError("Выберите непустой CSV-файл")
                if length > 50_000_000:
                    raise WarehouseError("CSV-файл превышает допустимый размер 50 МБ")
                body = self.rfile.read(length)
                try:
                    text = body.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = body.decode("cp1251")
                try:
                    delimiter = csv.Sniffer().sniff(text[:4096], delimiters=";,").delimiter
                except csv.Error:
                    delimiter = ";"
                reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
                if not reader.fieldnames:
                    raise WarehouseError("В CSV-файле отсутствует строка заголовков")
                aliases = {
                    "категория": "category", "category": "category", "модель": "model", "model": "model",
                    "серийный номер": "serial_number", "serial_number": "serial_number",
                    "инвентарный номер": "inventory_number", "inventory_number": "inventory_number",
                    "место": "location", "location": "location", "количество": "quantity", "quantity": "quantity",
                    "примечание": "notes", "notes": "notes", "цод": "datacenter", "datacenter": "datacenter",
                    "основание": "basis", "basis": "basis", "ответственный": "responsible", "responsible": "responsible",
                    "дата": "work_date", "work_date": "work_date", "источник задачи": "task_source", "task_source": "task_source",
                    "тип задачи": "task_type", "task_type": "task_type", "номер задачи": "task_number", "task_number": "task_number",
                    "описание работы": "description", "description": "description", "статус": "status", "status": "status",
                    "комментарий": "comment", "comment": "comment",
                    "комментарий / основание": "comment",
                    "блок отчета": "report_block", "report_block": "report_block",
                    "описание / наименование": "description",
                    "количество / метраж": "quantity", "s/n": "serial_number",
                    "фио": "responsible", "дата заказа": "order_date",
                    "заявка№": "request_number", "заявка №": "request_number",
                    "заказ№": "order_number", "заказ №": "order_number", "plu": "plu",
                    "наименование": "item_name", "проект": "project", "sn": "serial_number",
                    "инв.№": "inventory_number", "инв. №": "inventory_number",
                    "поставщик": "supplier", "вендор": "vendor",
                    "стеллаж/полка": "shelf", "объект": "object_name",
                    "цод": "datacenter", "datacenter": "datacenter",
                    "тип оборудования": "equipment_type", "тип компонента": "component_type",
                    "тип кабеля": "cable_type", "единица учета": "unit",
                    "кол-во / метраж": "quantity", "количество / метраж": "quantity",
                    "sn целевого объекта": "target_serial_number",
                    "sn целевого об-я": "target_serial_number",
                    "hostname целевого оборудования": "target_hostname",
                    "s/n списываемого": "source_serial_number",
                }
                header_map = {field: aliases.get(str(field).strip().casefold(), "") for field in reader.fieldnames}
                required_sets = {
                    "equipment": {"category", "model", "serial_number", "inventory_number", "location", "quantity"},
                    "receipt": {"work_date", "responsible", "item_name", "project",
                                "serial_number", "inventory_number", "supplier", "vendor",
                                "model", "shelf", "object_name", "equipment_type",
                                "component_type", "cable_type", "unit", "quantity"},
                    "issue": {"work_date", "responsible", "task_type", "task_number",
                              "target_serial_number", "target_hostname", "quantity",
                              "source_serial_number", "item_name", "cable_type", "comment"},
                    "work_logs": {"work_date", "task_source", "task_type", "task_number", "description", "status", "comment"},
                    "daily_report": {"work_date", "report_block", "task_number", "description", "quantity", "serial_number", "responsible", "comment"},
                }
                if missing := required_sets[kind] - set(header_map.values()):
                    raise WarehouseError("В CSV отсутствуют обязательные столбцы: " + ", ".join(sorted(missing)))
                rows = [{canonical: row.get(original, "") for original, canonical in header_map.items() if canonical} for row in reader]
                if kind == "equipment":
                    imported = service.import_equipment_rows(rows)
                elif kind == "work_logs":
                    imported = service.import_work_log_rows(rows)
                elif kind == "receipt":
                    for row in rows:
                        row["receipt_date"] = row.pop("work_date", row.get("receipt_date", ""))
                    imported = service.import_stock_receipt_rows(rows)
                elif kind == "daily_report":
                    for row in rows:
                        row["date"] = row.pop("work_date", "")
                    result = service.import_daily_report_rows(
                        unquote(self.headers.get("X-Filename", "daily_report.csv")), rows
                    )
                    imported = result["row_count"]
                else:
                    for row in rows:
                        row["issue_date"] = row.pop("work_date", row.get("issue_date", ""))
                        row["source_item_name"] = row.pop("item_name", "")
                        row["source_cable_type"] = row.pop("cable_type", "")
                    imported = service.import_stock_issue_rows(rows)
                response = {"ok": True, "imported": imported}
                if kind == "daily_report":
                    response["upload_id"] = result["id"]
                self._send_json(200, response)
            except (WarehouseError, ValueError, csv.Error, UnicodeError) as error:
                self._send_json(400, {"error": str(error)})
            except Exception as error:
                self._send_json(500, {"error": str(error)})

        def _login(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 100_000:
                    raise WarehouseError("Некорректный размер запроса")
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                user = service.authenticate(data.get("email", ""), data.get("password", ""))
                token = secrets.token_urlsafe(32)
                with sessions_lock:
                    sessions[token] = str(user["email"])
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
            token = self._session_token()
            with sessions_lock:
                return sessions.get(token, "")

        @staticmethod
        def _query(query: dict[str, list[str]], name: str) -> str:
            return query.get(name, [""])[0]

        def _balance_filters(self, query: dict[str, list[str]]) -> dict[str, str]:
            return {
                name: self._query(query, name)
                for name in (
                    "project", "object_name", "equipment_type", "component_type",
                    "cable_type", "unit", "datacenter",
                )
            }

        def _send_template(self, filename: str, text: str) -> None:
            self._send_download(filename, ("\ufeff" + text).encode("utf-8"))

        def _send_json(self, status: int, data: Any) -> None:
            self._send(status, _json_bytes(data), "application/json; charset=utf-8")

        def _send_csv(self, filename: str, rows: list[dict[str, Any]]) -> None:
            buffer = io.StringIO()
            if rows:
                writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            self._send_download(filename, ("\ufeff" + buffer.getvalue()).encode("utf-8"))

        def _send_download(self, filename: str, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
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
    service = WarehouseService(args.db)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
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
