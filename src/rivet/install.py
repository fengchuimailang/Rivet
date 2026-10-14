from __future__ import annotations

import subprocess
from pathlib import Path

from .doctor import render, run_doctor


def _distribution() -> str | None:
    path = Path("/etc/os-release")
    if not path.is_file():
        return None
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value.strip().strip('"')
    return values.get("ID")


def system_package_hint() -> str:
    distribution = _distribution()
    if distribution in {"debian", "ubuntu", "linuxmint", "pop"}:
        command = "sudo apt install verilator yosys make"
    elif distribution in {"fedora", "rhel", "centos", "rocky", "almalinux"}:
        command = "sudo dnf install verilator yosys make"
    elif distribution in {"arch", "manjaro"}:
        command = "sudo pacman -S verilator yosys make"
    elif distribution in {"opensuse-tumbleweed", "opensuse-leap"}:
        command = "sudo zypper install verilator yosys make"
    else:
        command = "install verilator, yosys, and make with your system package manager"
    return (
        "Some system tools are unavailable or unsupported. Install them outside Rivet:\n"
        f"  {command}\n"
        "Then rerun `rivet doctor`."
    )


def sync_python_dependencies(root: Path) -> int:
    try:
        result = subprocess.run(["uv", "sync", "--dev"], cwd=root, check=False)
    except OSError as exc:
        print(f"failed to run uv sync: {exc}")
        return 1
    return result.returncode


def install(root: Path, *, python_only: bool = False, check_only: bool = False) -> int:
    if not check_only:
        status = sync_python_dependencies(root)
        if status:
            return status
        print("Python dependencies are ready.")
        if python_only:
            return 0
    try:
        result = run_doctor(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"doctor failed: {exc}")
        return 1
    print(render(result), end="")
    if not python_only and result["overall_status"] == "failed":
        print()
        print(system_package_hint())
    return 0 if result["overall_status"] != "failed" else 1
