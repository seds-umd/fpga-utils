#!/usr/bin/env python

import cocotb

from fpga_utils import spinal_stream as stream, test_runner


@cocotb.test()
async def test_stream(dut):
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
    f_in = stream.SpinalStreamSource.from_prefix(dut, "io_f_in")
    f_out = stream.SpinalStreamSink.from_prefix(dut, "io_f_out")

    # 1b bits fragment flow
    g_in = stream.SpinalStreamSource.from_prefix(dut, "io_g_in")
    g_out = stream.SpinalStreamSink.from_prefix(dut, "io_g_out")

    await a_in.write([0, 1, 2, 3, 4, 5, 6, 7])

    print(await a_out.read())


if __name__ == "__main__":
    test_runner.run_wrapper(
        top_level="StreamExample",
        package="fpga_utils_tests",
        proj_dir="../..",
        source_dir="tests/spinal",
        gen_dir="tests/gen",
        spinal_sources=["Blank"],
    )
