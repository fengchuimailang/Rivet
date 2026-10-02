TOPLEVEL_LANG := verilog
SIM ?= verilator

TOPLEVEL := fifo
MODULE := acceptance_test
VERILOG_SOURCES := $(CURDIR)/rtl/fifo.sv
PYTHONPATH := $(CURDIR)/golden
VENV_BIN := $(shell uv run python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')

FIFO_DATA_WIDTH ?= 8
FIFO_DEPTH ?= 4
FIFO_SEED ?= 1001

export PYTHONPATH
export FIFO_DATA_WIDTH FIFO_DEPTH FIFO_SEED
export PATH := $(VENV_BIN):$(PATH)

.PHONY: lint compile test

lint:
	verilator --lint-only --language 1800 \
		-GDATA_WIDTH=$(FIFO_DATA_WIDTH) \
		-GDEPTH=$(FIFO_DEPTH) \
		$(VERILOG_SOURCES)

compile:
	verilator --binary --timing --language 1800 \
		-GDATA_WIDTH=$(FIFO_DATA_WIDTH) \
		-GDEPTH=$(FIFO_DEPTH) \
		$(VERILOG_SOURCES)

test:
	$(MAKE) -f $(shell uv run cocotb-config --makefiles)/Makefile.sim \
		SIM=$(SIM) \
		TOPLEVEL_LANG=$(TOPLEVEL_LANG) \
		TOPLEVEL=$(TOPLEVEL) \
		MODULE=$(MODULE) \
		VERILOG_SOURCES="$(VERILOG_SOURCES)" \
		PYTHONPATH=$(PYTHONPATH) \
		FIFO_DATA_WIDTH=$(FIFO_DATA_WIDTH) \
		FIFO_DEPTH=$(FIFO_DEPTH) \
		FIFO_SEED=$(FIFO_SEED)
