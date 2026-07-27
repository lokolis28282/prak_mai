# ODE 0.18.1 — multi-DB backup review

Дата: 2026-07-27. Статус: **ACCEPTED FOR STATUS/CREATE-BACKUP SLICE**.

## Решение

Первый вертикальный срез принят: Administration централизованно описывает три
физически независимые runtime-БД и умеет только читать их состояние, выводить
список копий и создавать проверенный внешний snapshot. Registry не владеет
доменными таблицами, а Warehouse и Vacations facades не восстанавливают
файлы.

Restore отклонён из текущего scope. Без exact target resolution, проверки
profile/schema/FK/sidecars, safety backup, одноразового preview token,
остановки writers и атомарной публикации безопасной функции восстановления
нет. Поэтому route fail-closed, а кнопка и upload-контрол отсутствуют.

## Проверенные свойства

- три точных ID: `warehouse_ix`, `warehouse_solar`, `vacations`;
- status не создаёт backup-каталог и не изменяет SHA runtime-БД;
- snapshot каждой базы проходит integrity, FK и required-schema checks;
- SHA файла совпадает с manifest;
- путь backup находится вне repository;
- symlink/hardlink runtime targets блокируются;
- engineer/viewer denied; право определяется session role;
- три успешных операции дают три Administration audit event;
- ошибка публикации очищает только временные/незавершённые output-файлы;
- production restore action всегда отклоняется.

## Исправленные регрессии

1. Duplicate ФИО Vacations отдавал пользователю текст SQLite
   `UNIQUE constraint`. Теперь возвращается доменное сообщение и HTTP 409.
2. Детерминированный code graph был platform-dependent из-за `\`/`/`.
   Генератор нормализует пути в POSIX-виде; добавлен regression-тест.
3. При сохранении lexical backup target путь `VacationFacade` на Windows
   перестал совпадать с каноническим runtime path. Composition теперь хранит
   lexical candidate только в registry, а facade получает resolved path.
4. Restore-status содержал технический англицизм в пользовательском тексте.
   Формулировка заменена без ослабления fail-closed поведения.
5. Длинный абсолютный Windows-путь сжимал колонку таблицы до нескольких
   символов. Admin-grid получил `minmax(0, ...)`, широкую прокручиваемую
   таблицу и минимальную ширину path-колонки; добавлен frontend regression.

## Ограничения следующего этапа

Нужны restore preview/token, safety snapshot, cross-profile rejection,
corrupt/FK/sidecar tests, atomic-replace failure test и полный browser flow.
Correction/reversal Warehouse остаётся отдельным изменением согласно ADR-014.
