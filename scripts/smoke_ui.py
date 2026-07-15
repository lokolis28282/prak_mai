#!/usr/bin/env python3
"""Самозавершающийся UI smoke-test ODE на временной копии базы."""
from __future__ import annotations
import argparse

import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import sys
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inventory.db import hash_password
from inventory.core.application import create_application_context
from inventory.service import WarehouseService
from inventory.webapp import make_handler
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "warehouse.db")
    args = parser.parse_args(argv)
    if not CHROME.exists():
        raise SystemExit(f"Chrome не найден: {CHROME}")
    source_database = args.db.resolve()
    if not source_database.is_file():
        raise SystemExit(f"База не найдена: {source_database}")
    with tempfile.TemporaryDirectory(prefix="ode_ui_smoke_") as directory:
        work = Path(directory)
        database = work / "warehouse.db"
        shutil.copy2(source_database, database)
        with closing(sqlite3.connect(database)) as db, db:
            db.execute(
                """UPDATE users
                   SET password_hash = ?, must_change_password = 0, is_active = 1
                   WHERE email = 'lokolis'""",
                (hash_password("lokolis"),),
            )
        service = WarehouseService(database)
        context = create_application_context(
            database,
            service=service,
            warehouse_contour="demo",
            full_inventory_state_root=work / "full_inventory_state",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(context))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print("smoke: server started", flush=True)
        app_url = f"http://127.0.0.1:{server.server_port}"
        debug_port = free_port()
        chrome = subprocess.Popen([
            str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={debug_port}", f"--user-data-dir={work / 'chrome'}",
            app_url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            print("smoke: chrome started", flush=True)
            for _ in range(60):
                if chrome.poll() is not None:
                    raise RuntimeError("Chrome завершился до начала теста")
                try:
                    urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=.2).read()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("DevTools Chrome не запустился")
            print("smoke: devtools ready", flush=True)
            result = subprocess.run(
                ["node", str(ROOT / "tests" / "headless_smoke.js"), app_url, str(debug_port)],
                cwd=ROOT, text=True, capture_output=True, timeout=180,
            )
            print(result.stdout.strip(), flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "UI smoke-test завершился ошибкой")
            return 0
        finally:
            print("smoke: cleanup", flush=True)
            chrome.terminate()
            try: chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill(); chrome.wait(timeout=5)
            server.shutdown(); server.server_close(); thread.join(timeout=5)
            print("smoke: stopped", flush=True)

if __name__ == "__main__":
    raise SystemExit(main())
