"""Reports-owned file exports."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    prepared = list(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        if not prepared:
            file.write("")
            return
        writer = csv.DictWriter(
            file,
            fieldnames=list(prepared[0].keys()),
            delimiter=",",
        )
        writer.writeheader()
        writer.writerows(prepared)


def export_work_logs_csv(
    output_file: str | Path,
    work_logs: Iterable[dict[str, Any]],
) -> Path:
    """Write work logs using the historical CLI-compatible Russian columns."""
    path = Path(output_file)
    rows = [
        {
            "Дата": row["work_date"],
            "Источник задачи": row["task_source"],
            "Тип задачи": row["task_type"],
            "Номер задачи": row["task_number"],
            "Описание работы": row["description"],
            "Статус": row["status"],
            "Комментарий": row["comment"],
        }
        for row in work_logs
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(path, rows)
    return path
