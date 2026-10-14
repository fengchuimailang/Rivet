import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from rivet import runner


@pytest.fixture
def project(tmp_path, monkeypatch):
    benchmark = tmp_path / "benchmarks" / "fifo"
    (benchmark / "rtl").mkdir(parents=True)
    (benchmark / "golden").mkdir()
    (benchmark / "spec").mkdir()
    (benchmark / "rtl/fifo.sv").write_text("module fifo; endmodule\n")
    (benchmark / "golden/acceptance_test.py").write_text("# acceptance\n")
    (benchmark / "spec/basic.yaml").write_text("revision: 1\n")
    manifest = {
        "schema_version": 1, "benchmark_id": "rivet-fifo", "top": "fifo",
        "rtl": "rtl/fifo.sv", "spec": "spec/basic.yaml", "acceptance": "golden/acceptance_test.py",
        "cases": [{"id": "fifo-basic", "parameters": {"DATA_WIDTH": 8, "DEPTH": 3}, "seed": 1001}],
    }
    (benchmark / "manifest.json").write_text(json.dumps(manifest))
    # Deliberately reversed TOML order: execution must still be lint -> compile -> test.
    config = 'schema_version = 1\n[benchmark]\nmanifest = "benchmarks/fifo/manifest.json"\n'
    for name in reversed(runner.JOB_ORDER):
        config += (
            f'[jobs.{name}]\nkind = "{name}"\ntarget = "{name}"\n'
            'entrypoint = "benchmarks/fifo/Makefile"\n'
            'required_tools = ["verilator"]\ntimeout_seconds = 2\n'
        )
    (tmp_path / "rivet.toml").write_text(config)
    (benchmark / "Makefile").write_text(
        '.PHONY: lint compile test\n'
        'lint compile test:\n'
        '\t@echo "$@ $(FIFO_DATA_WIDTH) $(FIFO_DEPTH) $(FIFO_SEED)"\n'
        '\t@echo stderr-$@ >&2\n'
        '\t@echo $@ >> generated.txt\n'
    )
    monkeypatch.setattr(runner, "run_doctor", lambda root: {
        "overall_status": "unvalidated", "tools": [
            {"name": name, "status": "unvalidated", "path": runner.shutil.which(name)}
            for name in ("make", "python", "verilator", "cocotb")
        ],
    })
    return tmp_path


def test_runs_ordered_jobs_in_snapshot_and_records_logs(project):
    result = runner.run_benchmark(project, "fifo", "fifo-basic")
    assert result["status"] == "passed"
    assert [job["name"] for job in result["jobs"]] == list(runner.JOB_ORDER)
    run_dir = Path(result["run_dir"])
    assert json.loads((run_dir / "run.json").read_text()) == result
    for job in result["jobs"]:
        assert job["returncode"] == 0
        assert f'{job["name"]} 8 3 1001' in (run_dir / job["stdout_log"]).read_text()
        assert f'stderr-{job["name"]}' in (run_dir / job["stderr_log"]).read_text()
    assert not (project / "benchmarks/fifo/generated.txt").exists()
    assert len(result["source_tree_sha256"]) == 64
    assert "run.json" in result["artifacts"]
    assert not (Path(result["workspace"]) / ".venv").exists()


def test_failed_lint_skips_later_jobs_and_preserves_error(project):
    (project / "benchmarks/fifo/Makefile").write_text('lint:\n\t@echo bad-rtl >&2\n\t@exit 7\n')
    result = runner.run_benchmark(project, "fifo", "fifo-basic")
    assert result["status"] == "failed"
    assert [job["status"] for job in result["jobs"]] == ["failed", "skipped", "skipped"]
    assert "bad-rtl" in (Path(result["run_dir"]) / result["jobs"][0]["stderr_log"]).read_text()


@pytest.mark.parametrize("value", [True, 0, -1, 3.5, "$(touch unexpected)"])
def test_rejects_invalid_case_parameters_before_creating_run(project, value):
    path = project / "benchmarks/fifo/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["cases"][0]["parameters"]["DEPTH"] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="positive integer"):
        runner.run_benchmark(project, "fifo", "fifo-basic")
    assert not (project / ".rivet").exists()


def test_unknown_case_does_not_create_run(project):
    with pytest.raises(ValueError, match="unknown case"):
        runner.run_benchmark(project, "fifo", "unknown")
    assert not (project / ".rivet").exists()


def test_missing_tool_is_recorded_and_no_jobs_execute(project, monkeypatch):
    monkeypatch.setattr(runner, "run_doctor", lambda root: {"tools": [], "overall_status": "failed"})
    result = runner.run_benchmark(project, "fifo", "fifo-basic")
    assert result["status"] == "failed"
    assert "verilator" in result["precheck"]["unavailable_tools"]
    assert all(job["status"] == "skipped" for job in result["jobs"])
    assert (Path(result["run_dir"]) / "run.json").is_file()


def test_environment_allowlist_excludes_external_make_overrides(monkeypatch):
    monkeypatch.setenv("MAKEFLAGS", "--eval=malicious")
    monkeypatch.setenv("SIM", "unexpected")
    env = runner._case_environment({"id": "case", "parameters": {"DATA_WIDTH": 8, "DEPTH": 4}, "seed": 1})
    assert "MAKEFLAGS" not in env and "SIM" not in env


def test_output_limit_retains_bounded_log(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "LOG_LIMIT_BYTES", 128)
    code, reason, error = runner._execute(
        [sys.executable, "-c", 'print("x" * 1024)'], tmp_path, os.environ.copy(), 2,
        tmp_path / "stdout", tmp_path / "stderr",
    )
    assert reason == "output_limit" and error
    assert (tmp_path / "stdout").stat().st_size <= 128


def test_cancellation_terminates_job(tmp_path, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.selectors.EpollSelector, "select", interrupt)
    code, reason, error = runner._execute(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, os.environ.copy(), 2,
        tmp_path / "stdout", tmp_path / "stderr",
    )
    assert reason == "cancelled" and code == -signal.SIGKILL and error


def test_timeout_terminates_descendant_and_preserves_early_logs(tmp_path):
    script = (
        'import subprocess,sys,time; '
        'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
        'print(child.pid,flush=True); time.sleep(30)'
    )
    started = time.monotonic()
    code, reason, error = runner._execute(
        [sys.executable, "-c", script], tmp_path, os.environ.copy(), 1,
        tmp_path / "stdout", tmp_path / "stderr",
    )
    assert reason == "timeout" and code == -signal.SIGKILL and error
    assert time.monotonic() - started < 5
    child_pid = int((tmp_path / "stdout").read_text().strip())
    stat = Path(f"/proc/{child_pid}/stat")
    if stat.exists():
        assert stat.read_text().split()[2] == "Z"  # Reaping belongs to the host init process.


def test_path_escape_is_rejected(project):
    config_path = project / "rivet.toml"
    config_path.write_text(config_path.read_text().replace("benchmarks/fifo/manifest.json", "../manifest.json"))
    with pytest.raises(ValueError, match="escapes"):
        runner.run_benchmark(project, "fifo", "fifo-basic")
