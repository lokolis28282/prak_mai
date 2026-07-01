#!/usr/bin/env python3
"""Собрать минимальный переносимый пакет ODE для Windows."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "ODE_windows_ready.zip"


def package_files(root: Path = ROOT, backup_path: Path | None = None) -> list[tuple[Path, Path]]:
    required = [
        "app.py", "README.md", "README_WINDOWS.md", "CHANGELOG.md", "requirements.txt",
        "start_windows.bat", "start_macos.command",
    ]
    files = [(root / name, Path(name)) for name in required]
    for folder in ("inventory", "tests"):
        files.extend(
            (path, path.relative_to(root))
            for path in sorted((root / folder).rglob("*.py"))
        )
    database = root / "data" / "warehouse.db"
    files.append((database, Path("data/warehouse.db")))
    if backup_path is None:
        backups = sorted(
            (root / "data" / "backups").glob("*.db"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not backups:
            raise FileNotFoundError("Не найдена резервная копия базы")
        backup_path = backups[0]
    backup_path = backup_path.resolve()
    files.append((backup_path, Path("data/backups") / backup_path.name))
    missing = [str(path) for path, _ in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены обязательные файлы: " + ", ".join(missing))
    return files


def build_windows_package(
    output_path: Path | None = None,
    *,
    root: Path = ROOT,
    backup_path: Path | None = None,
) -> Path:
    output = (output_path or root / PACKAGE_NAME).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, archive_name in package_files(root.resolve(), backup_path):
            if "__pycache__" in archive_name.parts or archive_name.suffix == ".pyc":
                continue
            archive.write(source, archive_name.as_posix())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Собрать ODE_windows_ready.zip")
    parser.add_argument("--output", type=Path, default=ROOT / PACKAGE_NAME)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    result = build_windows_package(args.output, backup_path=args.backup)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
