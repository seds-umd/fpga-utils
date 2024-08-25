#!/usr/bin/env python

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.clock import Clock

from fpga_utils import spinal_stream as stream
from fpga_utils import test_runner

import logging
import numpy as np
import random


async def compare(
    in_bus: stream.SpinalStreamSource,
    out_bus: stream.SpinalStreamSink,
    frame: stream.SpinalStreamFrame,
):
    in_bus.send_nowait(frame)
    await in_bus.wait()
    await ClockCycles(in_bus.clock, 2)
    actual = out_bus.read_nowait()

    # Frames won't be the same because of timestamps
    assert frame.payload == actual.payload


@cocotb.test()
async def test_stream(dut):
    N = 100

    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())

    dut.reset.value = 1
    await ClockCycles(dut.clk, 2)
    dut.reset.value = 0

    # 8b bits stream
    a_in = stream.SpinalStreamSource.from_prefix(dut, "io_a_in")
    a_out = stream.SpinalStreamSink.from_prefix(dut, "io_a_out")

    # 16b sint fragment stream
    b_in = stream.SpinalStreamSource.from_prefix(dut, "io_b_in")
    b_out = stream.SpinalStreamSink.from_prefix(dut, "io_b_out")

    # 2b rgb stream
    c_in = stream.SpinalStreamSource.from_prefix(dut, "io_c_in")
    c_out = stream.SpinalStreamSink.from_prefix(dut, "io_c_out")

    # 2b rgb fragment stream
    d_in = stream.SpinalStreamSource.from_prefix(dut, "io_d_in")
    d_out = stream.SpinalStreamSink.from_prefix(dut, "io_d_out")

    # TBD AXIS stream
    # e tbd - axis

    # 64b bits flow
    # f_in = stream.SpinalStreamSource.from_prefix(dut, "io_f_in")
    # f_out = stream.SpinalStreamSink.from_prefix(dut, "io_f_out")

    # 1b bits fragment flow
    # g_in = stream.SpinalStreamSource.from_prefix(dut, "io_g_in")
    # g_out = stream.SpinalStreamSink.from_prefix(dut, "io_g_out")

    for i in range(N):
        # Make sure we test length 1
        if i == int(N / 2):
            count = 1
        else:
            count = random.randint(1, 100)

        # a
        expected = np.random.randint(0, 2**8, count)
        frame = stream.SpinalStreamFrame(a_in.bus.config, expected)
        await compare(a_in, a_out, frame)

        # b
        expected = np.random.randint(0, 2**16, count)
        frame = stream.SpinalStreamFrame(b_in.bus.config, expected)
        await compare(b_in, b_out, frame)

        # c
        expected = {
            "r": list(np.random.randint(0, 2**2, count)),
            "b": list(np.random.randint(0, 2**2, count)),
            "g": list(np.random.randint(0, 2**2, count)),
        }
        frame = stream.SpinalStreamFrame(c_in.bus.config, expected)
        await compare(c_in, c_out, frame)

        # d
        expected = {
            "r": list(np.random.randint(0, 2**2, count)),
            "b": list(np.random.randint(0, 2**2, count)),
            "g": list(np.random.randint(0, 2**2, count)),
        }
        frame = stream.SpinalStreamFrame(d_in.bus.config, expected)
        await compare(d_in, d_out, frame)


if __name__ == "__main__":
    test_runner.run_wrapper(
        top_level="StreamExample",
        package="fpga_utils_tests",
        proj_dir="../..",
        source_dir="tests/spinal",
        gen_dir="tests/gen",
    )
