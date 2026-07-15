#!/usr/bin/env python3
"""Собрать чистую переносимую папку и ZIP ODE для Windows."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

from inventory import __version__


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "ODE_0.14.0_windows_source.zip"
RC_DIR_NAME = "ODE_0.14.0"
RC_PACKAGE_NAME = f"{RC_DIR_NAME}.zip"


RELEASE_NOTES = f"""# ODE {__version__} Release Notes

Status: Release Candidate for controlled local pilot.

This package includes:

- warehouse;
- equipment and component receipt;
- equipment and component issue;
- separate cable accounting;
- deliveries;
- physical delivery acceptance;
- balance;
- history;
- daily and weekly reports;
- profile.
- compact four-module home and modal global search;
- editable receipt/issue scanner drafts before confirmation;
- disposable test contour with an unmistakable UI banner;
- equipment card with operational history;
- bounded large-data views and session-isolated previews.

The package deliberately contains no runtime database, production data,
candidate database or credentials. A target installation must create and own
its database separately under the documented bootstrap procedure.

Limitations:

- close delivery remains compatibility/legacy;
- destructive override for conflicting existing data is not implemented;
- Monitoring is still in development;
- external system APIs are not connected;
- server deployment has not been performed;
- deployment is limited to one local ODE process and one local SQLite file;
- real initial-baseline publish remains disabled;
- this source package requires target Windows acceptance before any rollout.
"""


KNOWN_ISSUES = """# Known Issues

- close_delivery is still compatibility/legacy.
- Destructive override for conflicting existing warehouse data is absent.
- Monitoring is a placeholder.
- Part of the frontend remains in legacy ui.js.
- WarehouseCore remains a compatibility core.
- Physical Windows launch must be confirmed on the target laptop.
- Scheduled automatic backup is not implemented.
- Server deployment is not implemented.
- One CSV import is limited to 40,000 non-empty rows.
- Corrective/reversal operations are not implemented.
- Initial-baseline publish to the operational database is disabled; only a
  disposable target-schema rehearsal is available.
"""


def package_files(root: Path = ROOT) -> list[tuple[Path, Path]]:
    required = [
        "app.py",
        "README.md",
        "README_WINDOWS.md",
        "WINDOWS_RELEASE.md",
        "CHANGELOG.md",
        "ARCHITECTURE.md",
        "PRODUCT_REVIEW.md",
        "UX_REVIEW.md",
        "ARCHITECT_REVIEW.md",
        "PERFORMANCE_REVIEW.md",
        "SECURITY_REVIEW.md",
        "QA_STAGE_0_12_17.md",
        "BUGS_STAGE_0_12_17.md",
        "requirements.txt",
        "start_windows.bat",
        "start_macos.command",
        "start_test_windows.bat",
        "start_test_macos.command",
        "scripts/create_clean_test_db.py",
    ]
    files = [(root / name, Path(name)) for name in required]
    files.extend(
        (path, path.relative_to(root))
        for path in sorted((root / "inventory").rglob("*.py"))
    )
    if (root / "static").is_dir():
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(root.joinpath("static").rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    if (root / "docs").is_dir():
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(root.joinpath("docs").rglob("*.md"))
        )
    for name in ("LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md"):
        if (root / name).is_file():
            files.append((root / name, Path(name)))
    files.append((root / "data" / "README.md", Path("data/README.md")))
    missing = [str(path) for path, _ in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены обязательные файлы: " + ", ".join(missing))
    return files


def _write_release_metadata(clean_dir: Path) -> None:
    (clean_dir / "VERSION").write_text(f"ODE {__version__}\n", encoding="utf-8")
    (clean_dir / "RELEASE_NOTES.md").write_text(RELEASE_NOTES, encoding="utf-8")
    (clean_dir / "KNOWN_ISSUES.md").write_text(KNOWN_ISSUES, encoding="utf-8")


def _write_sha256sums(clean_dir: Path) -> None:
    rows: list[str] = []
    for path in sorted(clean_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(f"{digest}  {path.relative_to(clean_dir).as_posix()}")
    (clean_dir / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


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
    output = (output_path or root / "release" / PACKAGE_NAME).resolve()
    if release_dir is None and output_path is not None:
        clean_dir = output.with_suffix("")
    else:
        clean_dir = (release_dir or root / "release" / RC_DIR_NAME).resolve()
    if clean_dir.exists():
        shutil.rmtree(clean_dir)
    clean_dir.mkdir(parents=True)
    for source, relative in package_files(root):
        target = clean_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    _write_release_metadata(clean_dir)
    _write_sha256sums(clean_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(clean_dir.rglob("*")):
            if path.is_file():
                archive.write(path, (Path("ODE") / path.relative_to(clean_dir)).as_posix())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Собрать release/ODE_windows_test.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "release" / PACKAGE_NAME)
    parser.add_argument("--release-dir", type=Path, default=None)
    args = parser.parse_args()
    release_dir = args.release_dir or ROOT / "release" / RC_DIR_NAME
    archive = build_windows_package(args.output, release_dir=release_dir)
    if args.output.resolve() == (ROOT / "release" / PACKAGE_NAME).resolve():
        shutil.copy2(archive, ROOT / "release" / RC_PACKAGE_NAME)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
