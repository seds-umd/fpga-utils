import cocotb
import numpy as np
from cocotb.handle import HierarchyObject
from fpga_utils import spinal_stream as stream


def encode_phase(phase, width=12):
    assert phase >= 0
    assert phase < 2**width

    effective_width = width - 2

    if phase > 2 ** (effective_width - 1):
        phase = phase + (0b111 << effective_width)

    return phase


def decode_phase(phase, width=12):
    effective_width = width - 2

    if phase > 2**effective_width:
        phase = phase - (0b111 << effective_width)

    return phase


def encode_complex(x, width=9):
    bit_count = int(np.ceil(width / 8)) * 8

    assert x.real >= -1 and x.real <= 1
    assert x.imag >= -1 and x.imag <= 1

    x *= 2 ** (width - 2)

    re = int(x.real)
    im = int(x.imag)

    if re < 0:
        re += 2**bit_count

    if im < 0:
        im += 2**bit_count

    re &= (1 << bit_count) - 1
    im &= (1 << bit_count) - 1

    res = re + (im << bit_count)

    return res


def decode_complex(x, width=9):
    bit_count = int(np.ceil(width / 8)) * 8

    re = x & ((1 << bit_count) - 1)
    x >>= bit_count
    im = x & ((1 << bit_count) - 1)

    if re > 2 ** (bit_count - 1):
        re -= 1 << bit_count

    if im > 2 ** (bit_count - 1):
        im -= 1 << bit_count

    val = re + 1j * im
    val /= 2 ** (width - 2)

    return val


class CordicSim:
    def __init__(
        self, module: HierarchyObject, phase_width: int = 12, dout_width: int = 9
    ):
        self.module = module

        self.phase_width = phase_width
        self.dout_width = dout_width

        self.past_inputs = []
        self.past_outputs = []

        self.phase = stream.SpinalStreamSink.from_prefix(
            self.module, "s_axis_phase", "aclk", "aresetn", axis=True, reset_active_level=False
        )
        self.dout = stream.SpinalStreamSource.from_prefix(
            self.module, "m_axis_dout", "aclk", "aresetn", axis=True, reset_active_level=False
        )

        cocotb.start_soon(self._run())

    def compute(self, phase) -> int:
        phase = decode_phase(phase, self.phase_width)
        phase /= 2 ** (self.phase_width - 2)
        phase *= 2 * np.pi

        val = np.exp(1j * phase)

        self.past_inputs.append(phase)
        self.past_outputs.append(val)

        return encode_complex(val, self.dout_width)

    async def _run(self):
        while True:
            frame = await self.phase.recv()
            payload = frame.payload

            for i in range(len(payload["tdata"])):
                payload["tdata"][i] = self.compute(payload["tdata"][i])

            self.dout.send_nowait(payload)
