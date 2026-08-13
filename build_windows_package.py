#!/usr/bin/env python3
"""Собрать чистую переносимую папку и ZIP ODE для Windows."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from inventory import __version__


ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = f"ODE_{__version__}_windows_source.zip"
RC_DIR_NAME = f"ODE_{__version__}"
RC_PACKAGE_NAME = f"{RC_DIR_NAME}.zip"


RELEASE_NOTES = f"""# ODE {__version__} Release Notes

Status: Release Candidate for controlled local pilot.

This package includes:

- physically isolated IXcellerate and Solar Warehouse contours;
- separate Vacations database and workflow;
- warehouse receipt, issue, cable, delivery, balance and history flows;
- equipment cards and evidence-only component composition;
- Reports, Knowledge, Administration and multi-database backup;
- manual Monitoring workflow with installation-owned hostname routing rules
  (the private JSON files are not shipped in the public package);
- normalized pasted hostnames, DCIM field enrichment and incident templates;
- disposable test contour with an unmistakable UI banner;
- a self-contained management presentation and operator guide;
- Windows launchers with verified CRLF line endings;
- the complete FULL Inventory rehearsal runtime dependency set.

The package deliberately contains no runtime database, production data,
candidate database or credentials. A target installation must create and own
its runtime databases separately under the documented bootstrap procedure.

Limitations:

- correction/reversal operations are not implemented;
- Monitoring does not send email or Rooms messages automatically;
- live Monitoring collection requires local Selenium/Edge setup and is not
  exercised by the source package acceptance;
- server deployment has not been performed;
- deployment is limited to one local ODE process and local SQLite files;
- real initial-baseline publish remains disabled;
- this source package requires target Windows acceptance before any rollout;
- API-key/Bearer/OAuth authentication is not implemented; the local browser
  and HTTP API use an in-memory cookie session only.
"""


KNOWN_ISSUES = """# Known Issues

- Corrective/reversal warehouse operations are absent.
- Live Monitoring collection depends on the corporate DCIM session and local
  Selenium/Edge configuration; routing JSON is installation-owned data.
- Monitoring does not send email or Rooms messages automatically.
- Part of the frontend remains in legacy ui.js.
- WarehouseCore remains a compatibility core.
- Physical Windows launch must be confirmed on the target laptop.
- Scheduled automatic backup is not implemented.
- Multi-database restore remains fail-closed.
- Server deployment is not implemented.
- One CSV import is limited to 40,000 non-empty rows.
- Initial-baseline publish to the operational database is disabled; only a
  disposable target-schema rehearsal is available.
"""


WINDOWS_SCRIPT_SUFFIXES = {".bat", ".cmd"}
RUNTIME_TREE_SUFFIXES = {
    "inventory": {".py", ".sql"},
    "baseline_rehearsal": {".py"},
    "ode": {".py", ".json"},
}
STATIC_TREE_SUFFIXES = {
    ".css",
    ".html",
    ".ico",
    ".js",
    ".json",
    ".png",
    ".svg",
    ".ttf",
    ".woff",
    ".woff2",
}
RELEASE_OWNED_TREES = {
    "baseline_rehearsal",
    "docs",
    "inventory",
    "ode",
    "scripts",
    "static",
    "tests",
}
# These files are intentionally part of the 0.21.1 release change and must be
# packageable before the release commit is created. Every other untracked file
# in a release-owned tree fails closed.
APPROVED_UNTRACKED_RELEASE_FILES = {
    Path("CONTRIBUTORS.md"),
    Path("ODE_PRESENTATION.html"),
    Path(f"RELEASE_REPORT_ODE_{__version__.replace('.', '_')}.md"),
    Path(f"docs/MANUAL_TESTING_{__version__.replace('.', '_')}_WINDOWS.md"),
    Path(f"docs/assets/ode-code-graph-{__version__}.png"),
    Path("docs/project/VERSION_HISTORY.md"),
    Path("inventory/core/web_runtime.py"),
    Path("inventory/shared/runtime_paths.py"),
    Path("tests/test_windows_package.py"),
}
EXCLUDED_UNTRACKED_RELEASE_NAMES = {"LAN_ACCESS_WINDOWS.md"}
EXCLUDED_UNTRACKED_RELEASE_PREFIXES = ("PRIVATE_WINDOWS_TRANSFER_",)
SENSITIVE_PATH_WORDS = {"credential", "private-key", "secret", "token"}
SENSITIVE_CONTENT_PATTERNS = (
    re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+"
        rb"[A-Za-z0-9+/=]{16,}"
    ),
    re.compile(rb"\bsk-proj-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(rb"\bxoxb-[A-Za-z0-9-]{20,}"),
)
SQLITE_HEADER = b"SQLite format 3\x00"
TEXT_SOURCE_SUFFIXES = {
    ".bat",
    ".cmd",
    ".command",
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".svg",
    ".txt",
}
BUILD_LOCK_NAME = ".ode_windows_package.lock"
COMMITTED_MARKER_NAME = ".ode_windows_package.committed.json"
COMMITTED_MARKER_SCHEMA = 1


def _runtime_tree_files(root: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for tree_name, suffixes in RUNTIME_TREE_SUFFIXES.items():
        tree = root / tree_name
        if not tree.is_dir():
            raise FileNotFoundError(f"Не найден обязательный runtime-каталог: {tree}")
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(tree.rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.casefold() in suffixes
        )
    return files


def _git_paths(root: Path, *arguments: str) -> set[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise RuntimeError("Source-пакет можно собирать только из Git checkout") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "Source-пакет можно собирать только из Git checkout"
            + (f": {detail}" if detail else "")
        )
    paths: set[Path] = set()
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="surrogateescape"))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Git вернул недопустимый путь: {relative}")
        paths.add(relative)
    return paths


def _is_release_owned_path(relative: Path) -> bool:
    if not relative.parts:
        return False
    if relative.parts[0] in RELEASE_OWNED_TREES:
        return True
    return (
        len(relative.parts) == 1
        and (
            relative.suffix.casefold() in {".bat", ".command", ".md"}
            or relative
            in {
                Path(".env.example"),
                Path("ODE_PRESENTATION.html"),
                Path("ODE_USER_GUIDE.html"),
                Path("app.py"),
                Path("build_windows_package.py"),
            }
        )
    )


def _repository_snapshot(root: Path) -> tuple[set[Path], set[Path]]:
    tracked = _git_paths(root, "--cached")
    untracked = _git_paths(root, "--others", "--exclude-standard")
    unexpected = sorted(
        relative.as_posix()
        for relative in untracked
        if _is_release_owned_path(relative)
        and relative not in APPROVED_UNTRACKED_RELEASE_FILES
        and not (
            len(relative.parts) == 1
            and (
                relative.name in EXCLUDED_UNTRACKED_RELEASE_NAMES
                or relative.name.startswith(EXCLUDED_UNTRACKED_RELEASE_PREFIXES)
            )
        )
    )
    if unexpected:
        raise RuntimeError(
            "Найдены неутверждённые untracked-файлы в release scope: "
            + ", ".join(unexpected)
        )
    return tracked, untracked


def _source_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _validate_regular_single_link(path: Path, metadata: os.stat_result) -> None:
    if stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"Symbolic link запрещён в source-пакете: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"Source должен быть обычным файлом: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"Hard link запрещён в source-пакете: {path}")


def _validated_source_with_identity(
    root: Path, source: Path
) -> tuple[Path, os.stat_result]:
    """Return a regular in-tree source and the identity proven during validation."""
    root = root.resolve(strict=True)
    source = source.absolute()
    try:
        source_metadata = os.lstat(source)
    except OSError as error:
        raise RuntimeError(f"Не удалось проверить source-файл: {source}") from error
    _validate_regular_single_link(source, source_metadata)
    try:
        lexical_relative = source.relative_to(root)
    except ValueError:
        # macOS may expose the same temporary path through /var and
        # /private/var. The resolved containment check below remains final.
        lexical_relative = None
    if lexical_relative is not None:
        cursor = root
        for part in lexical_relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise RuntimeError(f"Symbolic link запрещён в source-пакете: {source}")
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"Недопустимый файл source-пакета: {source}")
    try:
        resolved_metadata = os.lstat(resolved)
    except OSError as error:
        raise RuntimeError(f"Не удалось проверить source-файл: {source}") from error
    _validate_regular_single_link(resolved, resolved_metadata)
    if _source_identity(source_metadata) != _source_identity(resolved_metadata):
        raise RuntimeError(f"Source-файл изменился во время проверки: {source}")
    return resolved, resolved_metadata


def _validated_source_file(root: Path, source: Path) -> Path:
    """Return a regular in-tree source without following repository symlinks."""
    return _validated_source_with_identity(root, source)[0]


def _validate_release_source_content(relative: Path, content: bytes) -> None:
    lowered_parts = tuple(part.casefold() for part in relative.parts)
    if any(word in part for word in SENSITIVE_PATH_WORDS for part in lowered_parts):
        raise RuntimeError(f"Чувствительное имя файла запрещено в release: {relative}")
    if content.startswith(SQLITE_HEADER):
        raise RuntimeError(f"SQLite-файл запрещён в source-пакете: {relative}")
    if relative.suffix.casefold() in TEXT_SOURCE_SUFFIXES:
        for pattern in SENSITIVE_CONTENT_PATTERNS:
            if pattern.search(content):
                raise RuntimeError(f"Обнаружен секрет в source-файле: {relative}")


def _open_source_beneath_root(root: Path, relative: Path) -> int:
    flags_directory = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    flags_file = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if os.open not in os.supports_dir_fd:
        try:
            return os.open(root / relative, flags_file)
        except OSError as error:
            raise RuntimeError(
                f"Source-файл изменился до чтения: {root / relative}"
            ) from error
    directory_fd = os.open(root, flags_directory)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, flags_directory, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(relative.name, flags, dir_fd=directory_fd)
    except OSError as error:
        raise RuntimeError(f"Source-файл изменился до чтения: {root / relative}") from error
    finally:
        os.close(directory_fd)


def _read_stable_source(root: Path, source: Path) -> tuple[Path, bytes, os.stat_result]:
    root = root.resolve(strict=True)
    source, validated = _validated_source_with_identity(root, source)
    relative = source.relative_to(root)
    descriptor = _open_source_beneath_root(root, relative)
    try:
        opened = os.fstat(descriptor)
        _validate_regular_single_link(source, opened)
        if _source_identity(validated) != _source_identity(opened):
            raise RuntimeError(f"Source-файл изменился до чтения: {source}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read()
        after = os.fstat(descriptor)
        _validate_regular_single_link(source, after)
        if _source_identity(opened) != _source_identity(after):
            raise RuntimeError(f"Source-файл изменился во время чтения: {source}")
    finally:
        os.close(descriptor)
    try:
        current = os.stat(source, follow_symlinks=False)
    except OSError as error:
        raise RuntimeError(f"Source-файл изменился после чтения: {source}") from error
    _validate_regular_single_link(source, current)
    if _source_identity(after) != _source_identity(current):
        raise RuntimeError(f"Source-файл изменился после чтения: {source}")
    return source, content, opened


def _copy_portable_file(root: Path, source: Path, target: Path) -> None:
    source, content, metadata = _read_stable_source(root, source)
    relative = source.relative_to(root.resolve(strict=True))
    _validate_release_source_content(relative, content)
    if target.suffix.casefold() in WINDOWS_SCRIPT_SUFFIXES:
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        content = content.replace(b"\n", b"\r\n")
    with target.open("xb") as output:
        output.write(content)
    os.chmod(target, stat.S_IMODE(metadata.st_mode))
    os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))


def package_files(root: Path = ROOT) -> list[tuple[Path, Path]]:
    root = root.resolve(strict=True)
    tracked, _untracked = _repository_snapshot(root)
    required = [
        "app.py",
        "build_windows_package.py",
        "README.md",
        "CONTRIBUTORS.md",
        "ODE_PRESENTATION.html",
        "ODE_USER_GUIDE.md",
        "ODE_USER_GUIDE.html",
        "README_WINDOWS.md",
        "WINDOWS_RELEASE.md",
        "CHANGELOG.md",
        "ARCHITECTURE.md",
        f"RELEASE_REPORT_ODE_{__version__.replace('.', '_')}.md",
        ".env.example",
        "docs/history/PRODUCT_REVIEW.md",
        "docs/history/UX_REVIEW.md",
        "docs/history/ARCHITECT_REVIEW.md",
        "docs/history/PERFORMANCE_REVIEW.md",
        "docs/history/SECURITY_REVIEW.md",
        "docs/history/QA_STAGE_0_12_17.md",
        "docs/history/BUGS_STAGE_0_12_17.md",
        "docs/assets/code_graph.html",
        "docs/assets/ode-architecture-graph.svg",
        f"docs/assets/ode-code-graph-{__version__}.png",
        "requirements.txt",
        "requirements-monitoring.txt",
        "start_windows.bat",
        "start_macos.command",
        "start_test_windows.bat",
        "start_test_macos.command",
        "scripts/create_clean_test_db.py",
        "scripts/create_clean_vacations_test_db.py",
        "scripts/generate_hostname_rules.py",
        "scripts/integrate_recipient_rules_from_xlsx.py",
        "docs/architecture/ddl/verify_schema.sql",
        "docs/architecture/ddl/verify_domain_invariants.sql",
    ]
    files = [(root / name, Path(name)) for name in required]
    files.extend(_runtime_tree_files(root))
    files.extend(
        (path, path.relative_to(root))
        for path in sorted(root.glob("*.md"))
        if path.is_file()
        and not path.name.startswith("PRIVATE_WINDOWS_TRANSFER_")
        and path.name != "LAN_ACCESS_WINDOWS.md"
    )
    files.extend(
        (path, path.relative_to(root))
        for pattern in ("start*_windows.bat", "start*.command")
        for path in sorted(root.glob(pattern))
        if path.is_file()
        and path.name not in {"start_lan_windows.bat"}
    )
    for tree_name, suffixes in {
        "scripts": {".py"},
        "tests": {".py", ".js"},
    }.items():
        tree = root / tree_name
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(tree.rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.casefold() in suffixes
        )
    if (root / "static").is_dir():
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(root.joinpath("static").rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.casefold() in STATIC_TREE_SUFFIXES
        )
    if (root / "docs").is_dir():
        files.extend(
            (path, path.relative_to(root))
            for path in sorted(root.joinpath("docs").rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.casefold() in {".md", ".sql", ".html", ".svg", ".png"}
        )
    for name in ("LICENSE", "LICENSE.md", "NOTICE", "NOTICE.md"):
        if (root / name).is_file():
            files.append((root / name, Path(name)))
    files.append((root / "data" / "README.md", Path("data/README.md")))
    missing = [str(path) for path, _ in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Не найдены обязательные файлы: " + ", ".join(missing))
    unique: dict[Path, Path] = {}
    for source, relative in files:
        if relative not in tracked and relative not in APPROVED_UNTRACKED_RELEASE_FILES:
            raise RuntimeError(
                f"Файл release не tracked и не утверждён явно: {relative}"
            )
        validated = _validated_source_file(root, source)
        previous = unique.get(relative)
        if previous is not None and previous != validated:
            raise RuntimeError(f"Конфликт файлов пакета для {relative}")
        unique[relative] = validated
    ordered = sorted(unique.items(), key=lambda item: item[0].as_posix())
    return [(source, relative) for relative, source in ordered]


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


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _validate_output_parent(path: Path) -> None:
    parent = path.parent
    if parent.exists() and parent.is_symlink():
        raise RuntimeError(f"Родительский release-каталог не может быть symbolic link: {parent}")


def _validate_archive_target(path: Path) -> Path:
    output = _lexical_absolute(path)
    _validate_output_parent(output)
    if output.suffix.casefold() != ".zip":
        raise ValueError("Windows package output должен иметь расширение .zip")
    if output.is_symlink():
        raise RuntimeError(f"Output ZIP не может быть symbolic link: {output}")
    if output.exists() and not output.is_file():
        raise RuntimeError(f"Output ZIP должен быть обычным файлом: {output}")
    if output.exists() and os.lstat(output).st_nlink != 1:
        raise RuntimeError(f"Output ZIP не может быть hard link: {output}")
    return output


def _sha256_sidecar_path(archive: Path) -> Path:
    return archive.with_name(f"{archive.name}.sha256")


def _validate_sidecar_target(path: Path) -> Path:
    output = _lexical_absolute(path)
    _validate_output_parent(output)
    if not output.name.casefold().endswith(".zip.sha256"):
        raise ValueError("Checksum sidecar должен иметь расширение .zip.sha256")
    if output.is_symlink():
        raise RuntimeError(f"Checksum sidecar не может быть symbolic link: {output}")
    if output.exists() and not output.is_file():
        raise RuntimeError(f"Checksum sidecar должен быть обычным файлом: {output}")
    if output.exists() and os.lstat(output).st_nlink != 1:
        raise RuntimeError(f"Checksum sidecar не может быть hard link: {output}")
    return output


def _write_external_sha256(source: Path, target: Path, archive_name: str) -> None:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target.write_text(f"{digest}  {archive_name}\n", encoding="ascii")


def _validate_release_directory(root: Path, release_dir: Path | None) -> Path | None:
    if release_dir is None:
        return None
    expected = root / "release" / RC_DIR_NAME
    selected_lexical = _lexical_absolute(release_dir)
    release_root = root / "release"
    if selected_lexical.is_symlink():
        raise RuntimeError("Release-каталог не может быть symbolic link")
    selected = selected_lexical.resolve(strict=False)
    if selected != expected or selected.parent != release_root:
        raise RuntimeError(
            f"Распакованный release разрешён только в {expected}"
        )
    if release_root.is_symlink() or selected.is_symlink():
        raise RuntimeError("Release-каталог не может быть symbolic link")
    if selected.exists() and not selected.is_dir():
        raise RuntimeError(f"Release path должен быть каталогом: {selected}")
    return selected


def _create_zip(clean_dir: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(clean_dir.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    (Path(RC_DIR_NAME) / path.relative_to(clean_dir)).as_posix(),
                )
    with zipfile.ZipFile(output, "r") as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise RuntimeError(f"ZIP verification failed: {corrupt_member}")
    with output.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory_best_effort(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # Windows cannot reliably open directories through os.open. Atomic
        # replacement is complete; directory durability is best-effort there.
        pass


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


@dataclass(frozen=True)
class _Publication:
    destination: Path
    recovery: Path
    had_previous: bool


@contextlib.contextmanager
def _exclusive_build_lock(release_root: Path):
    release_root.mkdir(parents=True, exist_ok=True)
    _validate_output_parent(release_root / "placeholder")
    lock = release_root / BUILD_LOCK_NAME
    try:
        descriptor = os.open(
            lock,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError as error:
        # Never auto-delete a lock based only on age: doing so races a slow or
        # suspended live builder. Stale locks require explicit operator review.
        raise RuntimeError(
            f"Другой Windows package build уже выполняется: {lock}"
        ) from error
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
        _fsync_directory_best_effort(release_root)


def _recovery_paths(destination: Path) -> tuple[Path, Path]:
    return (
        destination.with_name(f".{destination.name}.previous"),
        destination.with_name(f".{destination.name}.failed"),
    )


def _preflight_recovery_paths(destinations: list[Path]) -> None:
    stale: list[str] = []
    for destination in destinations:
        stale.extend(
            str(path) for path in _recovery_paths(destination) if _path_exists(path)
        )
    if stale:
        raise RuntimeError(
            "Найдены незавершённые recovery-артефакты; требуется ручная проверка: "
            + ", ".join(stale)
        )


def _install_pending(pending: Path, destination: Path) -> _Publication:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _validate_output_parent(destination)
    pending_is_directory = pending.is_dir()
    recovery, failed = _recovery_paths(destination)
    if _path_exists(recovery) or _path_exists(failed):
        raise RuntimeError(
            "Найден незавершённый recovery-артефакт; требуется ручная проверка: "
            f"{recovery if _path_exists(recovery) else failed}"
        )
    had_previous = _path_exists(destination)
    if had_previous:
        if destination.is_symlink():
            raise RuntimeError(f"Destination не может быть symbolic link: {destination}")
        if destination.is_dir() != pending_is_directory:
            raise RuntimeError(f"Тип существующего release path не совпадает: {destination}")
        os.replace(destination, recovery)
    try:
        os.replace(pending, destination)
    except BaseException as publish_error:
        if had_previous and _path_exists(recovery) and not _path_exists(destination):
            try:
                os.replace(recovery, destination)
            except BaseException as rollback_error:
                raise RuntimeError(
                    "Публикация и автоматический rollback не удались; "
                    f"предыдущий артефакт сохранён для восстановления: {recovery}"
                ) from rollback_error
        raise publish_error
    _fsync_directory_best_effort(destination.parent)
    return _Publication(destination, recovery, had_previous)


def _prepare_file_publication(source: Path, destination: Path) -> _Publication:
    destination.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".ode_publish_", dir=destination.parent))
    try:
        pending = workspace / destination.name
        shutil.copyfile(source, pending)
        with pending.open("rb") as stream:
            os.fsync(stream.fileno())
        return _install_pending(pending, destination)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _prepare_directory_publication(staged: Path, destination: Path) -> _Publication:
    destination.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=".ode_publish_", dir=destination.parent))
    try:
        pending = workspace / destination.name
        shutil.copytree(staged, pending)
        return _install_pending(pending, destination)
    finally:
        # The previous release, if rollback itself failed, lives in the stable
        # sibling recovery path and is never inside this disposable workspace.
        shutil.rmtree(workspace, ignore_errors=True)


def _rollback_publication(publication: _Publication) -> None:
    destination = publication.destination
    recovery = publication.recovery
    if publication.had_previous:
        _recovery, failed = _recovery_paths(destination)
        if _path_exists(failed):
            raise RuntimeError(f"Rollback blocked by existing artifact: {failed}")
        if _path_exists(destination):
            os.replace(destination, failed)
        try:
            os.replace(recovery, destination)
        except BaseException as error:
            raise RuntimeError(
                "Rollback не завершён; предыдущий и новый артефакты сохранены: "
                f"{recovery}, {failed}"
            ) from error
        _remove_path(failed)
    else:
        _remove_path(destination)
    _fsync_directory_best_effort(destination.parent)


def _commit_publication(publication: _Publication) -> None:
    if not publication.had_previous:
        return
    _remove_path(publication.recovery)
    _fsync_directory_best_effort(publication.destination.parent)


def _verify_published_archives(
    staged_zip: Path,
    archive_targets: list[Path],
    sidecar_targets: list[Path],
) -> str:
    expected_digest = hashlib.sha256(staged_zip.read_bytes()).hexdigest()
    for archive in archive_targets:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_digest:
            raise RuntimeError(f"Published ZIP не совпадает со staged artifact: {archive}")
        with zipfile.ZipFile(archive, "r") as bundle:
            corrupt_member = bundle.testzip()
            if corrupt_member is not None:
                raise RuntimeError(f"Published ZIP повреждён: {archive}: {corrupt_member}")
    for archive, sidecar in zip(archive_targets, sidecar_targets):
        expected = f"{expected_digest}  {archive.name}\n"
        if sidecar.read_text(encoding="ascii") != expected:
            raise RuntimeError(f"Checksum sidecar не совпадает с ZIP: {sidecar}")
    return expected_digest


def _directory_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Symbolic link запрещён в published release: {path}")
        if not path.is_file():
            continue
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError(f"Недопустимый published release file: {path}")
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        content_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(content_digest)
    return digest.hexdigest()


def _committed_marker_path(release_root: Path) -> Path:
    return release_root / COMMITTED_MARKER_NAME


def _marker_destinations(
    archive_targets: list[Path],
    sidecar_targets: list[Path],
    published_directory: Path | None,
) -> dict[str, object]:
    return {
        "archives": [str(path) for path in archive_targets],
        "sidecars": [str(path) for path in sidecar_targets],
        "release_directory": (
            str(published_directory) if published_directory is not None else None
        ),
    }


def _write_committed_marker(
    marker_path: Path,
    *,
    archive_targets: list[Path],
    sidecar_targets: list[Path],
    published_directory: Path | None,
    publications: list[_Publication],
    canonical_digest: str,
) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    if marker_path.is_symlink() or marker_path.exists():
        raise RuntimeError(f"Committed marker уже существует: {marker_path}")
    payload = {
        "schema": COMMITTED_MARKER_SCHEMA,
        "version": __version__,
        "canonical_sha256": canonical_digest,
        "destinations": _marker_destinations(
            archive_targets,
            sidecar_targets,
            published_directory,
        ),
        "previous_destinations": [
            str(publication.destination)
            for publication in publications
            if publication.had_previous
        ],
        "release_directory_sha256": (
            _directory_digest(published_directory)
            if published_directory is not None
            else None
        ),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{COMMITTED_MARKER_NAME}.",
        suffix=".tmp",
        dir=marker_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        content = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = -1
        if marker_path.is_symlink() or marker_path.exists():
            raise RuntimeError(f"Committed marker появился во время записи: {marker_path}")
        os.replace(temporary, marker_path)
        _fsync_directory_best_effort(marker_path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _load_committed_marker(marker_path: Path) -> dict[str, object]:
    metadata = os.lstat(marker_path)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError(f"Недопустимый committed marker: {marker_path}")
    if metadata.st_size > 64 * 1024:
        raise RuntimeError(f"Committed marker слишком велик: {marker_path}")
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Committed marker повреждён: {marker_path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Committed marker имеет неверный формат: {marker_path}")
    return payload


def _finish_committed_cleanup(
    marker_path: Path,
    *,
    archive_targets: list[Path],
    sidecar_targets: list[Path],
    published_directory: Path | None,
    tolerate_cleanup_error: bool,
) -> bool:
    if not _path_exists(marker_path):
        return True
    if marker_path.is_symlink():
        raise RuntimeError(f"Committed marker не может быть symbolic link: {marker_path}")
    payload = _load_committed_marker(marker_path)
    expected_destinations = _marker_destinations(
        archive_targets,
        sidecar_targets,
        published_directory,
    )
    if (
        payload.get("schema") != COMMITTED_MARKER_SCHEMA
        or payload.get("version") != __version__
        or payload.get("destinations") != expected_destinations
    ):
        raise RuntimeError("Committed marker не соответствует текущему release-набору")
    canonical_digest = payload.get("canonical_sha256")
    previous_destinations = payload.get("previous_destinations")
    if (
        not isinstance(canonical_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", canonical_digest) is None
        or not isinstance(previous_destinations, list)
        or not all(isinstance(path, str) for path in previous_destinations)
    ):
        raise RuntimeError("Committed marker содержит недопустимые поля")
    all_destinations = archive_targets + sidecar_targets + (
        [published_directory] if published_directory is not None else []
    )
    allowed = {str(path): path for path in all_destinations}
    if len(previous_destinations) != len(set(previous_destinations)) or any(
        path not in allowed for path in previous_destinations
    ):
        raise RuntimeError("Committed marker содержит недопустимый recovery scope")
    for archive in archive_targets:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != canonical_digest:
            raise RuntimeError(f"Committed ZIP не совпадает с marker: {archive}")
        with zipfile.ZipFile(archive, "r") as bundle:
            if corrupt_member := bundle.testzip():
                raise RuntimeError(f"Committed ZIP повреждён: {archive}: {corrupt_member}")
    for archive, sidecar in zip(archive_targets, sidecar_targets):
        expected = f"{canonical_digest}  {archive.name}\n"
        if sidecar.read_text(encoding="ascii") != expected:
            raise RuntimeError(f"Committed sidecar не совпадает с marker: {sidecar}")
    expected_directory_digest = payload.get("release_directory_sha256")
    if published_directory is None:
        if expected_directory_digest is not None:
            raise RuntimeError("Committed marker содержит лишний directory digest")
    elif (
        not isinstance(expected_directory_digest, str)
        or _directory_digest(published_directory) != expected_directory_digest
    ):
        raise RuntimeError("Committed release directory не совпадает с marker")
    try:
        for destination_text in previous_destinations:
            destination = allowed[destination_text]
            recovery = _recovery_paths(destination)[0]
            if _path_exists(recovery):
                _remove_path(recovery)
        marker_path.unlink()
        _fsync_directory_best_effort(marker_path.parent)
    except OSError as error:
        if tolerate_cleanup_error:
            return False
        raise RuntimeError(
            f"Committed release подтверждён, но cleanup ещё не завершён: {marker_path}"
        ) from error
    return True


def _recover_interrupted_release_set(
    archive_targets: list[Path],
    sidecar_targets: list[Path],
    published_directory: Path | None,
) -> None:
    destinations = archive_targets + sidecar_targets + (
        [published_directory] if published_directory is not None else []
    )
    recoveries = {
        destination: _recovery_paths(destination)[0]
        for destination in destinations
    }
    present = {
        destination: recovery
        for destination, recovery in recoveries.items()
        if _path_exists(recovery)
    }
    if not present:
        return
    # A complete previous set proves an interrupted multi-artifact publish.
    # Restore every previous artifact before starting a new transaction.
    if len(present) != len(destinations):
        raise RuntimeError(
            "Неполный recovery-набор требует ручной проверки: "
            + ", ".join(str(path) for path in present.values())
        )
    for destination in reversed(destinations):
        recovery = recoveries[destination]
        failed = _recovery_paths(destination)[1]
        if _path_exists(failed):
            raise RuntimeError(f"Recovery blocked by existing artifact: {failed}")
        if _path_exists(destination):
            os.replace(destination, failed)
        try:
            os.replace(recovery, destination)
        except BaseException as error:
            raise RuntimeError(
                "Автоматическое восстановление прерванного release-набора не удалось; "
                f"сохранены пути {recovery} и {failed}"
            ) from error
        _remove_path(failed)
    _fsync_directory_best_effort(destinations[0].parent)


def _publish_release_directory(staged: Path, destination: Path) -> None:
    publication = _prepare_directory_publication(staged, destination)
    _commit_publication(publication)


def _atomic_zip(clean_dir: Path, output: Path) -> None:
    output = _validate_archive_target(output)
    with tempfile.TemporaryDirectory(prefix="ode_zip_stage_") as workspace:
        staged = Path(workspace) / output.name
        _create_zip(clean_dir, staged)
        publication = _prepare_file_publication(staged, output)
    _commit_publication(publication)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination = _validate_archive_target(destination)
    publication = _prepare_file_publication(source, destination)
    _commit_publication(publication)


def build_windows_package(
    output_path: Path | None = None,
    *,
    root: Path = ROOT,
    release_dir: Path | None = None,
    alias_path: Path | None = None,
    write_sha256_sidecars: bool = False,
    backup_path: Path | None = None,
) -> Path:
    # backup_path оставлен в сигнатуре для совместимости; реальные backup запрещены.
    del backup_path
    root = root.resolve(strict=True)
    output = _validate_archive_target(output_path or root / "release" / PACKAGE_NAME)
    alias = _validate_archive_target(alias_path) if alias_path is not None else None
    if alias is not None and alias == output:
        raise RuntimeError("Canonical ZIP и alias должны иметь разные пути")
    archive_targets = [output] + ([alias] if alias is not None else [])
    sidecar_targets = (
        [_validate_sidecar_target(_sha256_sidecar_path(target)) for target in archive_targets]
        if write_sha256_sidecars
        else []
    )
    all_file_targets = archive_targets + sidecar_targets
    resolved_file_targets = [target.resolve(strict=False) for target in all_file_targets]
    if (
        len(set(all_file_targets)) != len(all_file_targets)
        or len(set(resolved_file_targets)) != len(resolved_file_targets)
    ):
        raise RuntimeError("Release artifacts должны иметь уникальные пути")
    published_directory = _validate_release_directory(root, release_dir)
    if published_directory is not None:
        for target in all_file_targets:
            comparison = target.resolve(strict=False)
            if (
                comparison == published_directory
                or published_directory in comparison.parents
            ):
                raise RuntimeError("Output ZIP не может находиться внутри release-каталога")
    release_root = root / "release"
    destinations = all_file_targets + (
        [published_directory] if published_directory is not None else []
    )
    committed_marker = _committed_marker_path(release_root)
    with _exclusive_build_lock(release_root):
        _finish_committed_cleanup(
            committed_marker,
            archive_targets=archive_targets,
            sidecar_targets=sidecar_targets,
            published_directory=published_directory,
            tolerate_cleanup_error=False,
        )
        _recover_interrupted_release_set(
            archive_targets,
            sidecar_targets,
            published_directory,
        )
        _preflight_recovery_paths(destinations)
        with tempfile.TemporaryDirectory(prefix="ode_windows_package_") as workspace:
            clean_dir = Path(workspace) / RC_DIR_NAME
            clean_dir.mkdir()
            for source, relative in package_files(root):
                target = clean_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_portable_file(root, source, target)
            _write_release_metadata(clean_dir)
            _write_sha256sums(clean_dir)
            staged_zip = Path(workspace) / PACKAGE_NAME
            _create_zip(clean_dir, staged_zip)
            staged_sidecars: list[tuple[Path, Path]] = []
            for index, (archive_target, sidecar_target) in enumerate(
                zip(archive_targets, sidecar_targets)
            ):
                staged_sidecar = Path(workspace) / f"checksum-{index}.zip.sha256"
                _write_external_sha256(staged_zip, staged_sidecar, archive_target.name)
                staged_sidecars.append((staged_sidecar, sidecar_target))
            publications: list[_Publication] = []
            try:
                if published_directory is not None:
                    publications.append(
                        _prepare_directory_publication(clean_dir, published_directory)
                    )
                # Alias is prepared before the canonical ZIP. The canonical path is
                # the commit marker: any earlier exception rolls all prior paths back.
                if alias is not None:
                    publications.append(_prepare_file_publication(staged_zip, alias))
                # Publish the alias checksum first and the canonical checksum last,
                # immediately before the canonical ZIP commit marker.
                for staged_sidecar, sidecar_target in reversed(staged_sidecars):
                    publications.append(
                        _prepare_file_publication(staged_sidecar, sidecar_target)
                    )
                publications.append(_prepare_file_publication(staged_zip, output))
                canonical_digest = _verify_published_archives(
                    staged_zip,
                    archive_targets,
                    sidecar_targets,
                )
                _write_committed_marker(
                    committed_marker,
                    archive_targets=archive_targets,
                    sidecar_targets=sidecar_targets,
                    published_directory=published_directory,
                    publications=publications,
                    canonical_digest=canonical_digest,
                )
            except BaseException as publish_error:
                # Atomic marker installation is the irrevocable commit point.
                # If anything interrupts marker-directory fsync or later code,
                # never roll the verified NEW set back underneath a marker that
                # is already bound to its digest. The next locked invocation
                # validates the marker and finishes cleanup before rebuilding.
                if _path_exists(committed_marker):
                    raise
                rollback_errors: list[str] = []
                for publication in reversed(publications):
                    try:
                        _rollback_publication(publication)
                    except BaseException as rollback_error:
                        rollback_errors.append(str(rollback_error))
                if rollback_errors:
                    raise RuntimeError(
                        "Публикация release-набора не удалась; rollback требует "
                        "ручного восстановления: " + "; ".join(rollback_errors)
                    ) from publish_error
                raise
            _finish_committed_cleanup(
                committed_marker,
                archive_targets=archive_targets,
                sidecar_targets=sidecar_targets,
                published_directory=published_directory,
                tolerate_cleanup_error=True,
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Собрать release/ODE_windows_test.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "release" / PACKAGE_NAME)
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        help=f"только {ROOT / 'release' / RC_DIR_NAME}; другие пути запрещены",
    )
    args = parser.parse_args()
    release_dir = args.release_dir or ROOT / "release" / RC_DIR_NAME
    default_output = _lexical_absolute(ROOT / "release" / PACKAGE_NAME)
    alias = (
        ROOT / "release" / RC_PACKAGE_NAME
        if _lexical_absolute(args.output) == default_output
        else None
    )
    archive = build_windows_package(
        args.output,
        release_dir=release_dir,
        alias_path=alias,
        write_sha256_sidecars=True,
    )
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
