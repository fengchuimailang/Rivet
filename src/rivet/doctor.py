from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolCheck:
    name: str
    kind: str
    command: str | None
    detected: str | None
    minimum: str | None
    validated: list[str]
    selected: str | None
    status: str
    path: str | None = None
    error: str | None = None


def _version(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    match = re.search(r"\d+(?:\.\d+)+", value)
    return tuple(int(part) for part in match.group(0).split(".")) if match else ()


def _meets_minimum(detected: str | None, minimum: str | None) -> bool:
    if not detected or not minimum:
        return False
    return _version(detected) >= _version(minimum)


def _validated_status(detected: str | None, minimum: str | None, validated: list[str]) -> str:
    if not detected:
        return "missing"
    if not _meets_minimum(detected, minimum):
        return "unsupported"
    if validated and detected not in validated:
        return "unvalidated"
    if not validated:
        return "unvalidated"
    return "validated"


def _command_version(command: str) -> tuple[str | None, str | None, str | None]:
    path = shutil.which(command)
    if not path:
        return None, None, f"command not found: {command}"
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return path, None, str(exc)
    output = (result.stdout or result.stderr).strip()
    detected = re.search(r"\d+(?:\.\d+)+", output)
    if result.returncode != 0:
        return path, None, output or f"version command exited with {result.returncode}"
    if not detected:
        return path, None, output or "version output did not contain a semantic version"
    return path, detected.group(0), None


def _import_version(module_name: str) -> tuple[str | None, str | None, str | None]:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        return None, None, str(exc)
    version = getattr(module, "__version__", None)
    if not version:
        return None, None, f"{module_name} does not expose __version__"
    return sys.executable, str(version), None


def _check_command(name: str, config: dict[str, Any]) -> ToolCheck:
    path, detected, error = _command_version(config["command"])
    return ToolCheck(
        name=name,
        kind="command",
        command=config["command"],
        detected=detected,
        minimum=config.get("minimum_version"),
        validated=config.get("validated_versions", []),
        selected=detected,
        status=_validated_status(detected, config.get("minimum_version"), config.get("validated_versions", [])),
        path=path,
        error=error,
    )


def _check_python(name: str, config: dict[str, Any]) -> ToolCheck:
    detected = platform.python_version()
    return ToolCheck(
        name=name,
        kind="python",
        command=config.get("command"),
        detected=detected,
        minimum=config.get("minimum_version"),
        validated=config.get("validated_versions", []),
        selected=detected,
        status=_validated_status(detected, config.get("minimum_version"), config.get("validated_versions", [])),
        path=sys.executable,
    )


def _check_import(name: str, config: dict[str, Any]) -> ToolCheck:
    path, detected, error = _import_version(config["import_name"])
    return ToolCheck(
        name=name,
        kind="python_import",
        command=None,
        detected=detected,
        minimum=config.get("minimum_version"),
        validated=config.get("validated_versions", []),
        selected=detected,
        status=_validated_status(detected, config.get("minimum_version"), config.get("validated_versions", [])),
        path=path,
        error=error,
    )


def run_doctor(root: Path) -> dict[str, Any]:
    config_path = root / "rivet.toml"
    if not config_path.is_file():
        raise FileNotFoundError(f"missing project config: {config_path}")
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)

    checks: list[ToolCheck] = []
    for name, tool_config in config.get("tools", {}).items():
        if "command" in tool_config and name == "python":
            checks.append(_check_python(name, tool_config))
        elif "command" in tool_config:
            checks.append(_check_command(name, tool_config))
        elif "import_name" in tool_config:
            checks.append(_check_import(name, tool_config))

    statuses = {check.status for check in checks}
    if "missing" in statuses or "unsupported" in statuses:
        overall = "failed"
    elif "unvalidated" in statuses:
        overall = "unvalidated"
    else:
        overall = "validated"
    return {
        "schema_version": 1,
        "project": config.get("project"),
        "overall_status": overall,
        "root": str(root),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "tools": [asdict(check) for check in checks],
    }


def render(result: dict[str, Any], as_json: bool = False) -> str:
    if as_json:
        return json.dumps(result, indent=2, sort_keys=True) + "\n"
    lines = [f"Project: {result['project']}", f"Status: {result['overall_status']}", ""]
    lines.append("tool             detected   minimum   selected   status       path")
    lines.append("---------------- ---------  --------  ---------  -----------  ----")
    for tool in result["tools"]:
        lines.append(
            f"{tool['name']:<16} {str(tool['detected'] or '-'):9}  "
            f"{str(tool['minimum'] or '-'):8}  {str(tool['selected'] or '-'):9}  "
            f"{tool['status']:<11}  {tool['path'] or '-'}"
        )
        if tool["error"]:
            lines.append(f"  error: {tool['error']}")
    return "\n".join(lines) + "\n"
