# FRONTEND_CONTRACTS

Дата: 2026-07-10

## Зачем нужен контракт

ODE сейчас находится в переходном состоянии: HTML-каркас приходит из `inventory/webapp.py`, часть UI вынесена в `static/js`, а часть legacy-разметки еще создается динамически. Ошибки `Cannot read properties of null` обычно появляются, когда JavaScript обращается к id, которого больше нет в HTML.

`scripts/audit_frontend_contracts.py` проверяет контракт HTML <-> JS:

- собирает id из `LOGIN_HTML` и итогового `HTML`;
- читает `inventory/webapp.py` и `static/js/*.js`;
- ищет статические обращения `getElementById("...")`, `byId("...")`, `querySelector("#...")`, `querySelectorAll("#...")`;
- выводит missing static ids;
- не падает на динамических id из whitelist.

## Как запускать

```bash
python3 scripts/audit_frontend_contracts.py
```

Ожидаемый результат:

```text
frontend-contracts: OK, no missing static ids
```

Exit code:

- `0` - явных missing static id нет;
- `1` - найдено обращение к id, которого нет в HTML и нет в whitelist.

## Как добавлять новые id

1. Если элемент статический, добавьте его в HTML-шаблон или компонент.
2. Если JS обращается к нему через `getElementById`, `byId` или `querySelector("#...")`, запустите audit.
3. Если audit показывает missing id, исправьте HTML/компонент, а не whitelist.

## Как добавлять whitelist

Whitelist допустим только для id, который создается динамически до использования:

- wizard-поля;
- preview-контейнеры;
- lazy panels;
- временные элементы, создаваемые конкретной render-функцией.

Добавление в whitelist делается в `DYNAMIC_ID_WHITELIST` внутри `scripts/audit_frontend_contracts.py`. Рядом должна быть понятная группа или комментарий. Нельзя добавлять id в whitelist, если элемент должен существовать в базовом HTML.

## Ограничения

Скрипт не является полноценным JavaScript parser. Он намеренно проверяет только статические строковые обращения. Динамические template string id и сложные CSS-селекторы должны покрываться smoke UI и ручным click smoke.
