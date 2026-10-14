"""Independent cocotb acceptance test for the Rivet FIFO benchmark."""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadWrite, RisingEdge

from reference_model import FifoModel


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@cocotb.test()
async def acceptance_test(dut):
    data_width = _int_env("FIFO_DATA_WIDTH", 8)
    depth = _int_env("FIFO_DEPTH", 4)
    seed = _int_env("FIFO_SEED", 1001)
    rng = random.Random(seed)
    model = FifoModel(data_width, depth)
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst.value = 1
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.w_data.value = 0
    await RisingEdge(dut.clk)
    await ReadWrite()
    model.reset()
    assert int(dut.empty.value) == 1
    assert int(dut.full.value) == 0
    assert int(dut.r_data.value) == 0

    dut.rst.value = 0
    for _ in range(200):
        wr_en = bool(rng.getrandbits(1))
        rd_en = bool(rng.getrandbits(1))
        w_data = rng.getrandbits(data_width)
        dut.wr_en.value = int(wr_en)
        dut.rd_en.value = int(rd_en)
        dut.w_data.value = w_data
        old_empty = model.empty
        old_r_data = model.r_data
        model.step(wr_en=wr_en, rd_en=rd_en, w_data=w_data)
        await RisingEdge(dut.clk)
        await ReadWrite()
        assert int(dut.empty.value) == int(model.empty)
        assert int(dut.full.value) == int(model.full)
        expected_r_data = model.r_data if rd_en and not old_empty else old_r_data
        assert int(dut.r_data.value) == expected_r_data
