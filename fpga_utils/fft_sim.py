import cocotb
import logging
import numpy as np

from cocotb.handle import HierarchyObject
from cocotbext.axi import AxiStreamBus, AxiStreamSink, AxiStreamSource, AxiStreamFrame


# Pack complex numbers into 16 bit samples
def fft_pack_complex(data: np.ndarray):
    data = data.astype(np.complex128)
    data = data * 128
    data_re = data.real.astype(np.int16).astype(np.uint16)
    data_im = data.imag.astype(np.int16).astype(np.uint16)
    data_bits = (data_re & 0xFF) | ((data_im & 0xFF) << 8)
    data_bits = [int(x) for x in data_bits]

    return data_bits


# Unpack 16 bit samples into complex numbers
def fft_unpack_complex(data) -> np.ndarray:
    data = np.array(data, dtype=np.uint16)
    data_re = (data & 0xFF).astype(np.int8)
    data_im = ((data >> 8) & 0xFF).astype(np.int8)

    data_complex = data_re + data_im * 1j
    data_complex = data_complex.astype(np.complex128) / 128

    return data_complex


class FFT_Sim:
    def __init__(
        self,
        module: HierarchyObject,
        size: int,
        arch: int,
        delay: int = 0,
        store: bool = False,
    ):
        """Simulate Xilinx FFT core.

        Args:
            module (cocotb.handle.HierarchyObject): Object referencing Verilog instance of FFT module. Must be an instance of XilinxFFT.
            size (int): Log2 of size of FFT.
            arch (int): 1=radix 4, 2=radix 2, 3=pipelined, 4=radix 2 lite
            delay (int, optional): Processing delay of core. Defaults to 0.
            store (bool, optional): If True, store all inputs and outputs for debugging. Defaults to False.
        """

        self.module = module
        self.log = logging.getLogger(f"cocotb.Xilinx_FFT")

        # Only FFT simulation needs the platform-specific bit-accurate C model.
        # Packing helpers are also used by simulations that do not use that IP.
        from gps import xilinx_fft

        # Create xilinx_fft module to use bit accurate C model
        self.size_log = size
        self.size = 2**size
        self.fft = xilinx_fft.Fft(size, arch)

        self.delay = delay  # TODO: implement delay
        self.fft_inv = False

        self.store = store
        self.past_inputs = []
        self.past_outputs = []

        self.config_axis = AxiStreamSink(
            AxiStreamBus.from_prefix(module, "s_axis_config"),
            module.aclk,
            module.aresetn,
            False,
        )
        self.config_axis.log.setLevel(logging.WARNING)  # Get rid of log messages

        self.data_in_axis = AxiStreamSink(
            AxiStreamBus.from_prefix(module, "s_axis_data"),
            module.aclk,
            module.aresetn,
            False,
            byte_size=16,
        )
        self.data_in_axis.log.setLevel(logging.WARNING)  # Get rid of log messages
        assert self.data_in_axis.width == 16

        self.data_out_axis = AxiStreamSource(
            AxiStreamBus.from_prefix(module, "m_axis_data"),
            module.aclk,
            module.aresetn,
            False,
        )
        self.data_out_axis.log.setLevel(logging.WARNING)  # Get rid of log messages

        self.status_axis = AxiStreamSource(
            AxiStreamBus.from_prefix(module, "m_axis_status"),
            module.aclk,
            module.aresetn,
            False,
        )
        self.status_axis.log.setLevel(logging.WARNING)  # Get rid of log messages

        self.event_lines = {
            "frame_started": module.event_frame_started,
            "tlast_missing": module.event_tlast_missing,
            "tlast_unexpected": module.event_tlast_unexpected,
            "data_in_channel_halt": module.event_data_in_channel_halt,
            "data_out_channel_halt": module.event_data_out_channel_halt,
            "status_channel_halt": module.event_status_channel_halt,
        }

        cocotb.start_soon(self._handle_config())
        cocotb.start_soon(self._handle_data())

    async def _handle_config(self):
        """Process config packets as they come in on the config bus."""
        while True:
            frame = await self.config_axis.recv()

            self.fft_inv = int(frame.tdata[0]) == 1
            dir_str = "forward" if self.fft_inv else "inverse"
            self.log.info("FFT direction set to " + dir_str)

    async def _handle_data(self):
        """Run FFT on data packets."""
        while True:
            frame = await self.data_in_axis.recv()
            self.log.info("Received data")
            data_complex = fft_unpack_complex(frame.tdata)
            assert len(data_complex) == self.size, len(data_complex)
            data_res = self.fft.run(data_complex, not self.fft_inv)
            data_bits = fft_pack_complex(data_res)

            data_packed = []

            for x in data_bits:
                data_packed.append(x & 0xFF)
                data_packed.append((x >> 8) & 0xFF)

            out_frame = AxiStreamFrame(
                tdata=data_packed, tuser=[self.fft.outputs.blk_exp] * 4096
            )

            await self.data_out_axis.send(out_frame)
            self.log.info("Sent data")

            if self.store:
                self.past_inputs.append((data_complex.copy(), self.fft_inv))
                self.past_outputs.append((data_res.copy(), self.fft.outputs.blk_exp))
