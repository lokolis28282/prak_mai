#!/usr/bin/env python3
"""Собрать чистую переносимую папку и ZIP ODE для Windows."""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RELEASE_DIR = ROOT / "release" / "ODE"
PACKAGE_NAME = "ODE_windows_test.zip"


def package_files(root: Path = ROOT) -> list[tuple[Path, Path]]:
    required = [
        "app.py", "README.md", "WINDOWS_RELEASE.md", "CHANGELOG.md",
        "requirements.txt", "start_windows.bat",
    ]
    files = [(root / name, Path(name)) for name in required]
    files.extend(
        (path, path.relative_to(root))
        for path in sorted((root / "inventory").rglob("*.py"))
    )
    files.append((root / "data" / "warehouse.db", Path("data/warehouse.db")))
    missing = [str(path) for path, _ in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены обязательные файлы: " + ", ".join(missing))
    return files


def build_windows_package(
    output_path: Path | None = None,
    *,
    root: Path = ROOT,
    release_dir: Path | None = None,
    backup_path: Path | None = None,
) -> Path:
    # backup_path оставлен в сигнатуре для совместимости; реальные backup запрещены.
    del backup_path
    root = root.resolve()
    clean_dir = (release_dir or root / "release" / "ODE").resolve()
    output = (output_path or root / "release" / PACKAGE_NAME).resolve()
    if clean_dir.exists():
        shutil.rmtree(clean_dir)
    clean_dir.mkdir(parents=True)
    for source, relative in package_files(root):
        target = clean_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(clean_dir.rglob("*")):
            if path.is_file():
                archive.write(path, (Path("ODE") / path.relative_to(clean_dir)).as_posix())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Собрать release/ODE_windows_test.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "release" / PACKAGE_NAME)
    args = parser.parse_args()
    print(build_windows_package(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
