import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

class TB_Template:
    def __init__(self, dut, main_clk="clk", period=10):
        self.dut = dut
        self.period = period

        self._clk = getattr(self.dut, main_clk)
        cocotb.start_soon(Clock(self._clk, period=period, units="ns").start())

    async def reset(self, delay=2):
        self.dut.reset.value = 0
        await ClockCycles(self._clk, delay)
        self.dut.reset.value = 1
        await ClockCycles(self._clk, delay)
        self.dut.reset.value = 0
        await ClockCycles(self._clk, delay)
