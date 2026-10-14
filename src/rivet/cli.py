from __future__ import annotations

import argparse
from pathlib import Path

from .doctor import render, run_doctor
from .install import install


def main() -> int:
    parser = argparse.ArgumentParser(prog="rivet")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="inspect the configured local toolchain")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.add_argument("--root", type=Path, default=Path.cwd(), help="project root containing rivet.toml")
    installer = subparsers.add_parser("install", help="install Python dependencies and inspect system tools")
    installer.add_argument("--python-only", action="store_true", help="only synchronize Python dependencies")
    installer.add_argument("--check", action="store_true", help="only inspect the current environment")
    installer.add_argument("--root", type=Path, default=Path.cwd(), help="project root containing rivet.toml")
    args = parser.parse_args()

    if args.command == "doctor":
        try:
            result = run_doctor(args.root.resolve())
        except (FileNotFoundError, OSError, ValueError) as exc:
            parser.error(str(exc))
        print(render(result, as_json=args.json), end="")
        return 0 if result["overall_status"] != "failed" else 1
    if args.command == "install":
        return install(args.root.resolve(), python_only=args.python_only, check_only=args.check)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
