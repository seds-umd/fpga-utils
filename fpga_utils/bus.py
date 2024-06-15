import numpy as np
import logging
from cocotbext import axi


# Random pause generator for AXI bus
def random_pause():
    while True:
        yield np.random.choice([0, 1])


def stream_axis_bus(dut, prefix: str, fragment: bool = False, user: bool = False):
    axi_bus = axi.AxiStreamBus(dut)

    # Add signals to bus

    if fragment:
        # Janky way to handle different names for payload by seeing which one actually exists
        data_name = ""

        for element in dut:
            if element._name == prefix + "payload_fragment":
                data_name = "payload_fragment"
                break

            if element._name == prefix + "payload_data":
                data_name = "payload_data"
                break

        assert len(data_name) > 0

        axi_bus._add_signal("tdata", prefix + data_name)
        axi_bus._add_signal("tlast", prefix + "payload_last")
    else:
        axi_bus._add_signal("tdata", prefix + "payload")

    axi_bus._add_signal("tvalid", prefix + "valid")
    axi_bus._add_signal("tready", prefix + "ready")

    if user:
        axi_bus._add_signal("tuser", prefix + "payload_user")

    return axi_bus


def axis_sink(dut, prefix: str, fragment: bool = False, user: bool = False, **kwargs):
    bus = stream_axis_bus(dut, prefix, fragment, user)
    sink = axi.AxiStreamSink(bus, dut.clk, dut.reset, **kwargs)
    sink.log.setLevel(logging.WARNING)

    return sink


def axis_source(dut, prefix: str, fragment: bool = False, user: bool = False, **kwargs):
    bus = stream_axis_bus(dut, prefix, fragment, user)
    source = axi.AxiStreamSource(bus, dut.clk, dut.reset, **kwargs)
    source.log.setLevel(logging.WARNING)

    return source
