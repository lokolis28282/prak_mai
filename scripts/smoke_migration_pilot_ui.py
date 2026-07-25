#!/usr/bin/env python3
"""Headless review smoke on a temporary copy of the real migration pilot DB."""

from __future__ import annotations

from contextlib import closing
import hashlib
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
os.environ["ODE_MIGRATION_PILOT"] = "1"

import inventory.core.application as _application_wiring  # noqa: E402,F401
from inventory.service import WarehouseService
from inventory.warehouse.migration_pilot_review import (
    PILOT_FILENAME,
    validate_migration_pilot_database,
)
from inventory.webapp import make_handler


CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_PILOT = ROOT / "migration_inputs" / "workspace" / PILOT_FILENAME


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


def _leading_zero_import(database: Path) -> tuple[int, str, str, str]:
    with closing(sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )) as connection:
        row = connection.execute(
            """SELECT id, source_serial_value, source_item_name, canonical_item_name
                 FROM migration_pilot_selection
                WHERE import_decision = 'IMPORT'
                  AND target_receipt_id IS NOT NULL
                  AND source_serial_value GLOB '0*'
                ORDER BY selection_order LIMIT 1"""
        ).fetchone()
    if row is None:
        raise RuntimeError("Pilot selection не содержит IMPORT S/N с ведущим нулём")
    return int(row[0]), str(row[1]), str(row[2]), str(row[3])


def main(argv: list[str] | None = None) -> int:
    source = Path(argv[0]).expanduser() if argv else DEFAULT_PILOT
    if not CHROME.exists():
        raise SystemExit(f"Chrome не найден: {CHROME}")
    validate_migration_pilot_database(source)
    selection_id, serial, source_name, canonical_name = _leading_zero_import(source)
    with tempfile.TemporaryDirectory(prefix="ode_migration_pilot_smoke_") as directory:
        work = Path(directory)
        database = work / PILOT_FILENAME
        shutil.copy2(source, database)
        if os.name == "posix":
            database.chmod(0o600)
        validate_migration_pilot_database(database)
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
            for _ in range(60):
                if chrome.poll() is not None:
                    raise RuntimeError("Chrome завершился до начала pilot smoke")
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
                    str(ROOT / "tests" / "headless_migration_pilot_smoke.js"),
                    app_url,
                    str(debug_port),
                    str(selection_id),
                    serial,
                    source_name,
                    canonical_name,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=45,
            )
            print(result.stdout.strip(), flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Pilot UI smoke завершился ошибкой")
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
        database_sha_after = sha256_file(database)
        if database_sha_after != database_sha_before:
            raise RuntimeError("Read-only pilot runtime изменил SHA pilot DB copy")
        validate_migration_pilot_database(database)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
