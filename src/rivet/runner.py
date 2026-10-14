from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sysconfig
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .doctor import run_doctor

JOB_ORDER = ("lint", "compile", "test")
LOG_LIMIT_BYTES = 4 * 1024 * 1024
ENVIRONMENT_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "VERILATOR_ROOT")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _relative_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError(f"expected a repository-relative path: {value}")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes project root: {value}")
    return path


def _write_result(path: Path, result: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _copy_workspace(source: Path, destination: Path) -> None:
    ignored = shutil.ignore_patterns("__pycache__", "obj_dir", "sim_build", "results.xml", "*.pyc")
    shutil.copytree(source, destination, ignore=ignored)


def _validate_manifest(root: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("benchmark_id") != "rivet-fifo":
        raise ValueError("this runner supports only schema_version 1 and benchmark_id rivet-fifo")
    if manifest.get("top") != "fifo":
        raise ValueError("FIFO benchmark top must be fifo")
    for name, expected in {"rtl": "rtl/fifo.sv", "acceptance": "golden/acceptance_test.py"}.items():
        if manifest.get(name) != expected:
            raise ValueError(f"FIFO {name} must be {expected}")
    for name in ("spec", "rtl", "acceptance"):
        if not _relative_path(root, manifest.get(name)).is_file():
            raise ValueError(f"missing benchmark file: {manifest.get(name)}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest must define at least one case")
    identifiers: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("case must be an object with a string id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", case["id"]) or case["id"] in identifiers:
            raise ValueError(f"invalid or duplicate case id: {case['id']}")
        identifiers.add(case["id"])
        _case_environment(case)


def _validate_jobs(root: Path, benchmark_root: Path, jobs: dict[str, Any]) -> None:
    if not isinstance(jobs, dict) or set(jobs) != set(JOB_ORDER):
        raise ValueError("jobs must define exactly lint, compile, and test")
    for name in JOB_ORDER:
        job = jobs[name]
        if not isinstance(job, dict) or job.get("kind") != name or job.get("target") != name:
            raise ValueError(f"job {name} must use kind and target {name}")
        entrypoint = _relative_path(root, job.get("entrypoint"))
        if entrypoint != benchmark_root / "Makefile" or not entrypoint.is_file():
            raise ValueError(f"job {name} must use the selected benchmark Makefile")
        timeout = job.get("timeout_seconds")
        if type(timeout) is not int or timeout <= 0:
            raise ValueError(f"job {name} timeout_seconds must be a positive integer")
        required = job.get("required_tools")
        if not isinstance(required, list) or not all(isinstance(tool, str) for tool in required):
            raise ValueError(f"job {name} required_tools must be a list of tool names")


def _source_hash(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(workspace).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _case_environment(case: dict[str, Any]) -> dict[str, str]:
    environment = {key: os.environ[key] for key in ENVIRONMENT_KEYS if key in os.environ}
    scripts = sysconfig.get_path("scripts")
    environment["PATH"] = scripts + os.pathsep + environment.get("PATH", os.defpath)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    parameters = case.get("parameters")
    if not isinstance(parameters, dict) or set(parameters) != {"DATA_WIDTH", "DEPTH"}:
        raise ValueError(f"case {case.get('id')} must define DATA_WIDTH and DEPTH")
    for name, value in parameters.items():
        if type(value) is not int or value < 1:
            raise ValueError(f"case {case.get('id')}: {name} must be a positive integer")
        environment[f"FIFO_{name}"] = str(value)
    if type(case.get("seed")) is not int or case["seed"] < 0:
        raise ValueError(f"case {case.get('id')}: seed must be a nonnegative integer")
    environment["FIFO_SEED"] = str(case["seed"])
    return environment


def _execute(command: list[str], cwd: Path, environment: dict[str, str], timeout: int,
             stdout_path: Path, stderr_path: Path) -> tuple[int | None, str, str | None]:
    """Stream bounded logs and terminate the whole Linux process group on interruption."""
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            return None, "launch_error", str(exc)
        reason = "exit"
        error = None
        deadline = time.monotonic() + timeout
        written = 0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            try:
                while selector.get_map() or process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        reason, error = "timeout", f"timed out after {timeout} seconds"
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = LOG_LIMIT_BYTES - written
                        key.data.write(chunk[:available])
                        written += min(len(chunk), available)
                        if len(chunk) > available:
                            reason, error = "output_limit", f"logs exceeded {LOG_LIMIT_BYTES} bytes"
                            break
                    if reason != "exit":
                        break
            except KeyboardInterrupt:
                reason, error = "cancelled", "run interrupted by user"
            finally:
                if reason != "exit":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait()
                process.stdout.close()
                process.stderr.close()
        if reason == "exit" and process.returncode < 0:
            reason = "signal"
        return process.returncode, reason, error


def _run_job(
    *,
    root: Path,
    workspace: Path,
    job_name: str,
    config: dict[str, Any],
    environment: dict[str, str],
    logs: Path,
    make_command: str,
    makefiles: Path,
) -> dict[str, Any]:
    entrypoint = _relative_path(root, config["entrypoint"])
    copied_benchmark = workspace / entrypoint.parent.relative_to(root)
    command = [make_command, "-f", entrypoint.name, config["target"],
               f"VENV_BIN={sysconfig.get_path('scripts')}", f"COCOTB_MAKEFILES={makefiles}",
               "SIM=verilator"]
    command.extend(f"{key}={environment[key]}" for key in ("FIFO_DATA_WIDTH", "FIFO_DEPTH", "FIFO_SEED"))
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    stdout_path = logs / f"{job_name}.stdout.log"
    stderr_path = logs / f"{job_name}.stderr.log"
    returncode, reason, error = _execute(command, copied_benchmark, environment,
                                       config["timeout_seconds"], stdout_path, stderr_path)
    status = "passed" if returncode == 0 and reason == "exit" else "failed"
    if reason == "cancelled":
        status = "cancelled"
    return {
        "name": job_name,
        "status": status,
        "command": command,
        "cwd": str(copied_benchmark),
        "started_at": started_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "returncode": returncode,
        "termination_reason": reason,
        "signal": -returncode if returncode is not None and returncode < 0 else None,
        "timeout_seconds": config["timeout_seconds"],
        "timed_out": reason == "timeout",
        "error": error,
        "stdout_log": str(stdout_path.relative_to(logs.parent)),
        "stderr_log": str(stderr_path.relative_to(logs.parent)),
    }


def run_benchmark(root: Path, benchmark: str, case_id: str) -> dict[str, Any]:
    if os.name != "posix":
        raise ValueError("the local runner currently supports Linux/WSL only")
    root = root.resolve()
    config_path = root / "rivet.toml"
    with config_path.open("rb") as stream:
        project_config = tomllib.load(stream)
    if project_config.get("schema_version") != 1:
        raise ValueError("unsupported project schema_version")
    manifest_path = _relative_path(root, project_config["benchmark"]["manifest"])
    manifest = _load_json(manifest_path)
    _validate_manifest(manifest_path.parent, manifest)
    benchmark_name = manifest["benchmark_id"].removeprefix("rivet-")
    if benchmark != benchmark_name:
        raise ValueError(f"unknown benchmark '{benchmark}'; available benchmark: {benchmark_name}")
    cases = {case["id"]: case for case in manifest.get("cases", [])}
    if case_id not in cases:
        raise ValueError(f"unknown case '{case_id}'; choose one of: {', '.join(cases)}")
    jobs = project_config.get("jobs", {})
    _validate_jobs(root, manifest_path.parent, jobs)
    case = cases[case_id]
    environment = _case_environment(case)
    toolchain = run_doctor(root)
    tools = {tool["name"]: tool for tool in toolchain["tools"]}
    required_tools = {"make", "python", "verilator", "cocotb"}
    required_tools.update(tool for job in jobs.values() for tool in job["required_tools"])
    unavailable = sorted(name for name in required_tools
                         if name not in tools or tools[name]["status"] in {"missing", "unsupported"})
    if not unavailable:
        from cocotb_tools.config import makefiles_dir

    benchmark_source = manifest_path.parent
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = root / ".rivet" / "runs" / run_id
    workspace = run_dir / "workspace"
    logs = run_dir / "logs"
    workspace.mkdir(parents=True)
    logs.mkdir()
    _copy_workspace(benchmark_source, workspace / benchmark_source.relative_to(root))
    for project_file in ("rivet.toml", "pyproject.toml", "uv.lock"):
        source_file = root / project_file
        if source_file.is_file():
            shutil.copy2(source_file, workspace / project_file)
    result: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "benchmark": benchmark,
        "benchmark_id": manifest["benchmark_id"],
        "case": case,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "run_dir": str(run_dir),
        "workspace": str(workspace),
        "toolchain": toolchain,
        "source_tree_sha256": _source_hash(workspace),
        "spec_sha256": hashlib.sha256(
            (workspace / benchmark_source.relative_to(root) / manifest["spec"]).read_bytes()
        ).hexdigest(),
        "job_schema_version": 1,
        "precheck": {"status": "failed" if unavailable else "passed", "unavailable_tools": unavailable},
        "jobs": [],
    }
    result_path = run_dir / "run.json"
    _write_result(result_path, result)
    result["status"] = "failed" if unavailable else "running"
    for name in JOB_ORDER:
        if result["status"] != "running":
            result["jobs"].append({"name": name, "status": "skipped"})
            continue
        job_config = jobs[name]
        job_result = _run_job(
            root=root,
            workspace=workspace,
            job_name=name,
            config=job_config,
            environment=environment,
            logs=logs,
            make_command=tools["make"]["path"],
            makefiles=makefiles_dir,
        )
        result["jobs"].append(job_result)
        _write_result(result_path, result)
        if job_result["status"] != "passed":
            result["status"] = job_result["status"]
    if result["status"] == "running":
        result["status"] = "passed"
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_seconds"] = round(sum(job.get("duration_seconds", 0) for job in result["jobs"]), 3)
    result["artifacts"] = [
        path.relative_to(run_dir).as_posix() for path in sorted(run_dir.rglob("*")) if path.is_file()
    ]
    _write_result(result_path, result)
    return result
