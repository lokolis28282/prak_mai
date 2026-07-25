"""Dependency-free command line surface for ODE 0.13 foundation operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ode.application.config import DatabaseConfig, Environment
from ode.application.context import build_application_context
from ode.application.errors import OdeError
from ode.infrastructure.migrations import load_schema_manifest
from ode.system.models import HealthStatus


_BIDI_CONTROLS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        from ode.application.errors import ConfigurationError

        raise ConfigurationError("INVALID_CLI_ARGUMENTS", message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python3 -m ode")
    commands = parser.add_subparsers(dest="group", required=True)
    db = commands.add_parser("db", help="database lifecycle diagnostics")
    db_commands = db.add_subparsers(dest="command", required=True)
    for name in ("create", "status", "verify", "migrations"):
        command = db_commands.add_parser(name)
        command.add_argument("--path", required=True, type=Path)
        command.add_argument("--allow-external-dev-path", action="store_true")
    system = commands.add_parser("system", help="system diagnostics")
    system_commands = system.add_subparsers(dest="command", required=True)
    health = system_commands.add_parser("health")
    health.add_argument("--path", required=True, type=Path)
    health.add_argument("--allow-external-dev-path", action="store_true")
    return parser


def _config(args: argparse.Namespace, *, read_only: bool) -> DatabaseConfig:
    manifest = load_schema_manifest()
    return DatabaseConfig.create(
        args.path,
        environment=Environment.DEVELOPMENT,
        read_only=read_only,
        expected_schema_version=manifest.expected_user_version,
        expected_application_id=manifest.application_id,
        allow_external_dev_path=bool(args.allow_external_dev_path),
    )


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _terminal_safe_text(value: str) -> str:
    result: list[str] = []
    for character in value:
        codepoint = ord(character)
        if character in _BIDI_CONTROLS or codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            if codepoint <= 0xFF:
                result.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                result.append(f"\\u{codepoint:04x}")
            else:
                result.append(f"\\U{codepoint:08x}")
        else:
            result.append(character)
    return "".join(result)


def _terminal_safe_value(value: object) -> object:
    if isinstance(value, str):
        return _terminal_safe_text(value)
    if isinstance(value, dict):
        return {
            _terminal_safe_text(str(key)): _terminal_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_terminal_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_terminal_safe_value(item) for item in value)
    return value


def _human_success(command: str, payload: dict[str, object]) -> None:
    print(f"OK: {_terminal_safe_text(command)}")
    for key, value in payload.items():
        if key == "command":
            continue
        if isinstance(value, (str, int, bool)) or value is None:
            display = _terminal_safe_text(value) if isinstance(value, str) else value
            print(f"{_terminal_safe_text(key)}: {display}")
        else:
            print(f"{_terminal_safe_text(key)}:")
            print(
                json.dumps(
                    _terminal_safe_value(value),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )


def _dispatch(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    name = f"{args.group} {args.command}"
    config = _config(args, read_only=not (args.group == "db" and args.command == "create"))
    context = build_application_context(config)
    if name == "db create":
        result = context.migration_runner.create()
        return 0, {"command": name, **result.to_dict()}
    if name == "db status":
        status = context.diagnostics.migration_status()
        return (0 if status.ready else 2), {"command": name, "status": status.to_dict()}
    if name == "db verify":
        result = context.migration_runner.verify()
        return 0, {"command": name, "verification": result.to_dict()}
    if name == "db migrations":
        context.migration_runner.validate_sources()
        manifest = context.migration_runner.manifest
        status = context.diagnostics.migration_status()
        manifest_payload: dict[str, object] = {
            "schema_version": manifest.schema_version,
            "application_id": manifest.application_id,
            "approved_schema_hash": manifest.approved_schema_hash,
            "expected_migration_count": manifest.expected_migration_count,
            "expected_user_version": manifest.expected_user_version,
            "migrations": [
                {"version": item.version, "file": item.file, "sha256": item.sha256}
                for item in manifest.migrations
            ],
        }
        return (0 if status.ready else 2), {
            "command": name,
            "manifest": manifest_payload,
            "applied": status.to_dict(),
        }
    if name == "system health":
        health = context.system.health()
        successful = health.status in {HealthStatus.READY, HealthStatus.NOT_INITIALIZED}
        return (0 if successful else 2), {"command": name, "health": health.to_dict()}
    raise RuntimeError("argparse accepted an unknown command")


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in raw
    raw = [argument for argument in raw if argument != "--json"]
    try:
        args = _parser().parse_args(raw)
        exit_code, payload = _dispatch(args)
        envelope = {"ok": exit_code == 0, **payload}
        if json_output:
            _print_json(envelope)
        else:
            _human_success(str(payload["command"]), payload)
        return exit_code
    except OdeError as exc:
        if json_output:
            _print_json(exc.to_envelope())
        else:
            print(
                f"ERROR {_terminal_safe_text(exc.code)}: "
                f"{_terminal_safe_text(str(exc))}",
                file=sys.stderr,
            )
        return 2
    except KeyboardInterrupt:
        envelope: dict[str, object] = {
            "ok": False,
            "error": {
                "code": "OPERATION_INTERRUPTED",
                "message": "Operation interrupted",
                "details": {},
            },
        }
        if json_output:
            _print_json(envelope)
        else:
            print("ERROR OPERATION_INTERRUPTED: Operation interrupted", file=sys.stderr)
        return 130
    except Exception:
        envelope = {
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unexpected internal failure",
                "details": {},
            },
        }
        if json_output:
            _print_json(envelope)
        else:
            print("ERROR INTERNAL_ERROR: Unexpected internal failure", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
