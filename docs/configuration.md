# Project Configuration

`rivet.toml` declares project requirements and the fixed jobs available to the
CLI and future Agent runtime. It contains executable names, version constraints,
and repository-relative entrypoints. It must not contain machine-specific
absolute paths or arbitrary shell command strings.

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
