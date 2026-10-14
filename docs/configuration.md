# Project Configuration

`rivet.toml` declares project requirements and the fixed jobs available to the
CLI and future Agent runtime. It contains executable names, version constraints,
and repository-relative entrypoints. It must not contain machine-specific
absolute paths or arbitrary shell command strings.

Benchmark manifests use JSON so the CLI can parse them with Python's standard
library and generated cases remain straightforward for tools to write.

## Tools

Each tool declares its command or Python import name, a minimum supported
version, and versions validated by maintainers. A detected version below the
minimum is unsupported. A version that meets the minimum but is absent from
`validated_versions` may be tried, but each run must be marked `unvalidated`.
An empty validated list means no version has yet been validated for that tool.

The cocotb 2.1.0 Verilator backend requires Verilator 5.036 or newer, so the
project's minimum Verilator version reflects this dependency.

Python packages are managed with `uv` and pinned by `uv.lock`. The configured
`uv` environment is authoritative for Python and cocotb checks; a system Python
package installation does not count as satisfying the project dependency.

The MVP is not packaged as an installed wheel yet. Run the development CLI from
the repository with `PYTHONPATH=src uv run --no-sync python -m rivet.cli doctor`.
The install workflow is available through the same command:

```console
PYTHONPATH=src uv run --no-sync python -m rivet.cli install
```

This synchronizes the locked Python development dependencies with `uv sync
--dev`, runs the environment check, and prints a system package hint when
Verilator, Yosys, or Make is missing. It never runs `sudo` or changes system
packages. Use `--python-only` to skip the check, or `--check` to inspect an
existing environment without changing it. Future CLI packaging can reuse the
same `rivet.cli:main` entrypoint without changing the doctor output contract.

## Jobs

Only `lint`, `compile`, and `test` are declared for the FIFO MVP. Each job names
a repository-relative Makefile entrypoint, a fixed target, required tools, and a
timeout. Job arguments such as FIFO width, depth, and random seed are structured
values supplied by the benchmark case. The runner is responsible for validating
those values and constructing the process invocation; callers do not supply
shell command strings.

## Validated Tool Matrix

`tools/validated-matrix.toml` records complete environments tested by
maintainers. Each entry should include a stable ID, operating system, CPU
architecture, exact Python/uv/Verilator/Yosys/cocotb/make versions, validation
date, benchmark revision, and any known limitations. Do not add an entry until
the declared FIFO jobs pass on that environment.

An environment can satisfy all minimum versions and still be outside the
validated matrix. Such runs are allowed by policy but must be reported as
`unvalidated`, with the detected versions preserved in the run result.

## Local Runner

Run a declared case with the development CLI:

```console
PYTHONPATH=src uv run --no-sync python -m rivet.cli run --benchmark fifo --case fifo-basic
```

The runner validates required tools, copies the benchmark into an isolated
workspace, then executes configured jobs in order. Each run is stored under
`.rivet/runs/<run-id>/` with a `run.json`, per-job stdout/stderr logs, and the
workspace snapshot. The runner invokes fixed `make` targets from `rivet.toml`;
callers cannot provide shell commands.

The FIFO manifest provides `fifo-basic`, `fifo-depth-1`, `fifo-depth-3`,
`fifo-width-1`, and `fifo-random-32x16`. `DATA_WIDTH` and `DEPTH` must be positive
integers, and seeds must be nonnegative integers. Parameters are applied to both
RTL compilation and the acceptance model. Jobs always run in the order `lint`,
`compile`, `test`; after a failure, remaining jobs are recorded as `skipped`.
Missing or unsupported required tools produce a failed precheck in `run.json`.

The runner reuses the Python/cocotb environment of its interpreter without
installing dependencies or creating a virtual environment per run. It passes
only selected environment variables to jobs and limits each job's combined
stdout/stderr to 4 MiB. Timeout, output limit, and Ctrl+C terminate the process
group. Results record exit codes, signals, termination reasons, durations,
input hashes, tool versions, and a relative artifact index. Exit codes are `0`
for passed runs, `1` for failed runs, `2` for invalid configuration or arguments,
and `130` for cancellation during job execution.

Execution status and toolchain validation status are separate: a run may pass
while its tools remain `unvalidated`. The current runner supports the FIFO
benchmark on Linux/WSL and uses trusted repository Makefiles and acceptance
tests. Workspace copies separate build artifacts from sources; they are not an
operating-system sandbox.

Run the Runner regression tests with `uv run --no-sync pytest -q`.
