#!/usr/bin/env python3
"""Headless acceptance smoke on a temporary copy of the full candidate DB."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ODE_FULL_MIGRATION_CANDIDATE"] = "1"

import inventory.core.application as _application_wiring  # noqa: E402,F401
from inventory.db import hash_password  # noqa: E402
from inventory.service import WarehouseService  # noqa: E402
from inventory.warehouse.migration_full_review import (  # noqa: E402
    FULL_FILENAME,
    validate_full_migration_database,
)
from inventory.webapp import make_handler  # noqa: E402


CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_CANDIDATE = ROOT / "migration_inputs" / "workspace" / FULL_FILENAME


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _samples(database: Path) -> dict[str, dict[str, object]]:
    with closing(sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )) as connection:
        connection.row_factory = sqlite3.Row
        leading = connection.execute(
            """SELECT r.id, r.display_serial_value, r.source_item_name,
                      r.canonical_item_name
                 FROM migration_full_reconciliation r
                WHERE r.operation_kind='RECEIPT' AND r.final_status='IMPORTED'
                  AND r.preservation_status='TEXT_EXACT'
                  AND r.display_serial_value GLOB '0*'
                  AND r.target_identity_id IS NOT NULL
                ORDER BY r.id LIMIT 1"""
        ).fetchone()
        numeric = connection.execute(
            """SELECT r.id, r.display_serial_value, r.raw_xml_value,
                      r.source_item_name, r.canonical_item_name
                 FROM migration_full_reconciliation r
                WHERE r.final_status='NUMERIC_PROVISIONAL_IMPORTED'
                  AND r.target_identity_id IS NOT NULL
                  AND upper(r.raw_xml_value) LIKE '%E%'
                ORDER BY r.id LIMIT 1"""
        ).fetchone()
        opening = connection.execute(
            """SELECT r.id, r.display_serial_value, r.source_item_name,
                      r.canonical_item_name
                 FROM migration_full_reconciliation r
                WHERE r.final_status='OPENING_STATE_CREATED'
                  AND r.target_identity_id IS NOT NULL
                ORDER BY r.id LIMIT 1"""
        ).fetchone()
    if leading is None or numeric is None or opening is None:
        raise RuntimeError("Full candidate не содержит обязательные smoke samples")
    return {
        "leading": dict(leading),
        "numeric": dict(numeric),
        "opening": dict(opening),
    }


def main(argv: list[str] | None = None) -> int:
    source = Path(argv[0]).expanduser() if argv else DEFAULT_CANDIDATE
    if not CHROME.exists():
        raise SystemExit(f"Chrome не найден: {CHROME}")
    validate_full_migration_database(source)
    source_sha_before = sha256_file(source)
    samples = _samples(source)
    with tempfile.TemporaryDirectory(prefix="ode_full_candidate_smoke_") as directory:
        work = Path(directory)
        database = work / FULL_FILENAME
        shutil.copy2(source, database)
        if os.name == "posix":
            database.chmod(0o600)
        validate_full_migration_database(database)
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(
                """UPDATE users
                      SET password_hash = ?, must_change_password = 0, is_active = 1
                    WHERE email = 'lokolis'""",
                (hash_password("lokolis"),),
            )
        database_sha_before = sha256_file(database)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(WarehouseService(database, initialize_database=False)),
        )
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        app_url = f"http://127.0.0.1:{server.server_port}"
        debug_port = free_port()
        chrome = subprocess.Popen(
            [
                str(CHROME),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={work / 'chrome'}",
                app_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if chrome.poll() is not None:
                    raise RuntimeError("Chrome завершился до начала full smoke")
                try:
                    urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=0.2).read()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("DevTools Chrome не запустился")
            result = subprocess.run(
                [
                    "node",
                    str(ROOT / "tests/headless_migration_full_smoke.js"),
                    app_url,
                    str(debug_port),
                    json.dumps(samples, ensure_ascii=False),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=180,
            )
            print(result.stdout.strip(), flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Full UI smoke завершился ошибкой")
        finally:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()
                chrome.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        if sha256_file(database) != database_sha_before:
            raise RuntimeError("Read-only runtime изменил SHA full candidate copy")
        validate_full_migration_database(database)
    source_sha_after = sha256_file(source)
    if source_sha_after != source_sha_before:
        raise RuntimeError("Headless smoke изменил исходную full candidate DB")
    print(json.dumps({
        "candidate_sha_unchanged": True,
        "candidate_sha256": source_sha_after,
        "source_sidecars": [
            suffix for suffix in ("-wal", "-shm", "-journal")
            if Path(str(source) + suffix).exists()
        ],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
