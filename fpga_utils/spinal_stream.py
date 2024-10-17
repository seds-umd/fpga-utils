"""

Original source: https://github.com/alexforencich/cocotbext-axi/blob/master/cocotbext/axi/axis.py
Copyright (c) 2020 Alex Forencich

Modified to support SpinalHDL style streams
Copyright (c) 2024 Nathan Kerns

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

import logging
import sys
from dataclasses import dataclass

import cocotb
import cocotb.handle
from cocotb.queue import Queue, QueueFull
from cocotb.triggers import RisingEdge, Timer, First, Event
from cocotb.utils import get_sim_time
from cocotb_bus.bus import Bus
from cocotbext.axi.reset import Reset


@dataclass
class SpinalStreamConfig:
    fragment: bool = False
    flow: bool = False
    bundle: dict = None
    ctrl_keys: list = None
    payload_keys: list = None

    @staticmethod
    def create(signals: dict):
        cfg = SpinalStreamConfig()

        cfg.flow = "ready" not in signals.keys()
        cfg.fragment = "last" in signals.keys()

        cfg.bundle = signals
        cfg.ctrl_keys = []
        cfg.payload_keys = []

        for name in signals.keys():
            if name in ["ready", "valid", "last"]:
                cfg.ctrl_keys.append(name)
            else:
                cfg.payload_keys.append(name)

        assert len(cfg.ctrl_keys) > 0
        assert len(cfg.ctrl_keys) < 4
        assert len(cfg.payload_keys) > 0

        return cfg

    def simple(self):
        return len(self.payload_keys) == 1

    def has_last(self):
        return "last" in self.ctrl_keys


class SpinalStreamFrame:
    def __init__(self, config: SpinalStreamConfig, payload=None, tx_complete=None):
        """Create stream frame.

        If stream has a single payload signal, the payload argument can be a
        list of values. If there are multiple signals, argument must be a dict
        with keys matching `config.payload_keys` and values of lists of all the
        same length.

        Args:
            config (SpinalStreamConfig): Stream config.
            payload (list, dict, optional): Frame payload. Defaults to None.
            tx_complete (_type_, optional): _description_. Defaults to None.
        """

        self.config = config

        self.sim_time_start = None
        self.sim_time_end = None
        self.tx_complete = None

        # Decode payload
        if type(payload) is SpinalStreamFrame:
            assert payload.config == self.config

            self.payload = payload.payload
            self.sim_time_start = payload.sim_time_start
            self.sim_time_end = payload.sim_time_end
            self.tx_complete = payload.tx_complete
        elif config.simple():
            # Single payload
            if payload is None:
                self.payload = list()
            else:
                self.payload = list(payload)
        elif type(payload) is dict and payload is not None:
            # Payload bundle dict
            self.payload = payload
        else:
            # Empty dict
            self.payload = {}
            for key in config.payload_keys:
                self.payload[key] = list()

        if tx_complete is not None:
            self.tx_complete = tx_complete

    @staticmethod
    def zero_frame(config: SpinalStreamConfig, size: int = 1):
        payload = {}

        for key in config.payload_keys:
            payload[key] = [0] * size

        frame = SpinalStreamFrame(config, payload)

        return frame

    def handle_tx_complete(self):
        if isinstance(self.tx_complete, Event):
            self.tx_complete.set(self)
        elif callable(self.tx_complete):
            self.tx_complete(self)

    def __eq__(self, other):
        if not isinstance(other, SpinalStreamFrame):
            return False

        if self.config != other.config:
            return False

        if self.payload != other.payload:
            return False

        return True

    def __repr__(self):
        rep = f"{type(self).__name__}("

        if self.config.simple():
            rep += str(self.payload)
            rep += ", "
        else:
            for key in self.config.payload_keys:
                rep += f"{key}={self.payload[key]!r}, "

        rep += f"sim_time_start={self.sim_time_start!r}, "
        rep += f"sim_time_end={self.sim_time_end!r})"
        rep += ")"

        return rep

    def __len__(self):
        if self.config.simple():
            return len(self.payload)
        elif type(self.payload[self.config.payload_keys[0]]) == int:
            return 1
        else:
            return len(self.payload[self.config.payload_keys[0]])

    def __iter__(self):
        return self.payload.__iter__()


def merge_frames(a: SpinalStreamFrame, b: SpinalStreamFrame):
    assert a.config == b.config

    # Timestamps
    a.sim_time_end = b.sim_time_end

    if a.config.simple():
        a.payload.extend(b.payload)
    else:
        for key in a.config.payload_keys:
            if type(b.payload[key]) is int:
                a.payload[key].append(b.payload[key])
            else:
                a.payload[key].extend(b.payload[key])

    return a


class SpinalStreamBus(Bus):
    def __init__(self, config: SpinalStreamConfig, prefix: str, entity=None, **kwargs):
        self.config = config

        super().__init__(entity, prefix, [])

        for sig_short, sig_long in self.config.bundle.items():
            self._add_signal(sig_short, sig_long)


class SpinalStreamBase(Reset):

    _type = "base"

    _init_x = False

    _valid_init = None
    _ready_init = None

    def __init__(
        self,
        bus: SpinalStreamBus,
        clock,
        reset=None,
        reset_active_level=True,
        quiet=True,
        *args,
        **kwargs,
    ):

        self.bus = bus
        self.clock = clock
        self.reset = reset
        if bus._name:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}.{bus._name}")
        else:
            self.log = logging.getLogger(f"cocotb.{bus._entity._name}")

        if quiet:
            self.log.setLevel(logging.WARNING)

        stream_type = "flow" if self.bus.config.flow else "stream"
        self.log.info(f"SpinalHDL {stream_type} {self._type}")

        super().__init__(*args, **kwargs)

        self.active = False
        self.queue = Queue()
        self.dequeue_event = Event()
        self.current_frame = None
        self.idle_event = Event()
        self.idle_event.set()
        self.active_event = Event()
        self.wake_event = Event()

        self.queue_len_bytes = 0
        self.queue_len_frames = 0

        if self._valid_init is not None and hasattr(self.bus, "valid"):
            self.bus.valid.setimmediatevalue(self._valid_init)
        if self._ready_init is not None and hasattr(self.bus, "ready"):
            self.bus.ready.setimmediatevalue(self._ready_init)

        for sig in self.bus._signals.keys():
            if self._init_x and sig not in ("valid", "ready"):
                v = getattr(self.bus, sig).value
                v.binstr = "x" * len(v)
                getattr(self.bus, sig).setimmediatevalue(v)

        self.log.info(f"SpinalHDL {stream_type} {self._type} configuration:")

        for sig in sorted(list(self.bus._signals.keys())):
            if sig not in ("valid", "ready"):
                self.log.info("  %s width: %d bits", sig, len(getattr(self.bus, sig)))

        self._run_cr = None

        self._init_reset(reset, reset_active_level)

    @classmethod
    def from_prefix(
        cls,
        dut: cocotb.handle.SimHandleBase,
        prefix: str,
        clk="clk",
        reset="reset",
        axis=False,
        *args,
        **kwargs,
    ):
        if type(clk) == str:
            clk = getattr(dut, clk)

        if type(reset) == str:
            reset = getattr(dut, reset)

        # Find bus signals
        all_signals = dir(dut)
        ctrl_signals = []
        payload_signals = []

        for sig in all_signals:
            if axis and sig.startswith(f"{prefix}_t"):
                if sig.endswith("ready") or sig.endswith("valid"):
                    ctrl_signals.append(sig)
                else:
                    payload_signals.append(sig)
            elif (
                sig.startswith(f"{prefix}_ready")
                or sig.startswith(f"{prefix}_valid")
                or (sig.startswith(f"{prefix}_payload") and sig.endswith(f"last"))
            ):
                ctrl_signals.append(sig)
            elif sig.startswith(f"{prefix}_payload"):
                payload_signals.append(sig)

        assert len(payload_signals) > 0, "No payload signals found"
        assert len(ctrl_signals) > 0 and len(ctrl_signals) < 4

        # Process signals to get short names
        signal_dict = {}

        for sig in ctrl_signals:
            if sig.endswith("ready"):
                signal_dict["ready"] = sig

            if sig.endswith("valid"):
                signal_dict["valid"] = sig

            if sig.endswith("last"):
                signal_dict["last"] = sig

        for sig in payload_signals:
            sig_name = sig
            sig_name = sig_name.replace(prefix, "")
            sig_name = sig_name.replace("_payload", "")
            sig_name = sig_name.replace("_fragment", "")
            sig_name = sig_name.lstrip("_")

            if len(sig_name) == 0:
                sig_name = "payload"

            signal_dict[sig_name] = sig

        # Create config
        cfg = SpinalStreamConfig.create(signal_dict)

        # Create bus
        bus = SpinalStreamBus(cfg, prefix, dut)

        # Create stream
        stream = cls(bus, clk, reset, *args, **kwargs)

        return stream

    def count(self) -> int:
        return self.queue.qsize()

    def empty(self) -> int:
        return self.queue.empty()

    def clear(self):
        while not self.queue.empty():
            frame: SpinalStreamFrame = self.queue.get_nowait()
            frame.sim_time_end = None
            frame.handle_tx_complete()
        self.dequeue_event.set()
        self.idle_event.set()
        self.active_event.clear()
        self.queue_len_bytes = 0
        self.queue_len_frames = 0

    def _handle_reset(self, state):
        if state:
            # self.log.info("Reset asserted")
            if self._run_cr is not None:
                self._run_cr.kill()
                self._run_cr = None

            self.active = False

            if self.queue.empty():
                self.idle_event.set()
        else:
            # self.log.info("Reset de-asserted")
            if self._run_cr is None:
                self._run_cr = cocotb.start_soon(self._run())

    async def _run(self):
        raise NotImplementedError()


class SpinalStreamPause:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._pause = False
        self._pause_generator = None
        self._pause_cr = None

    def _pause_update(self, val):
        pass

    @property
    def pause(self):
        return self._pause

    @pause.setter
    def pause(self, val):
        if self._pause != val:
            self._pause_update(val)
        self._pause = val

    def set_pause_generator(self, generator=None):
        if self._pause_cr is not None:
            self._pause_cr.kill()
            self._pause_cr = None

        self._pause_generator = generator

        if self._pause_generator is not None:
            self._pause_cr = cocotb.start_soon(self._run_pause())

    def clear_pause_generator(self, pause_val: bool = False):
        self.set_pause_generator(None)
        self.pause = pause_val

    async def _run_pause(self):
        clock_edge_event = RisingEdge(self.clock)

        for val in self._pause_generator:
            self.pause = val
            await clock_edge_event


class SpinalStreamSource(SpinalStreamBase, SpinalStreamPause):

    _type = "source"

    _init_x = True

    _valid_init = 0
    _ready_init = None

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        *args,
        **kwargs,
    ):

        super().__init__(
            bus,
            clock,
            reset,
            reset_active_level,
            *args,
            **kwargs,
        )

        self.queue_limit_bytes = -1
        self.queue_limit_frames = -1

    async def send(self, frame):
        while self.full():
            self.dequeue_event.clear()
            await self.dequeue_event.wait()
        frame = SpinalStreamFrame(self.bus.config, frame)
        await self.queue.put(frame)
        self.idle_event.clear()
        self.active_event.set()
        self.queue_len_bytes += len(frame)
        self.queue_len_frames += 1

    def send_nowait(self, frame):
        if self.full():
            raise QueueFull()
        frame = SpinalStreamFrame(self.bus.config, frame)
        self.queue.put_nowait(frame)
        self.idle_event.clear()
        self.active_event.set()
        self.queue_len_bytes += len(frame)
        self.queue_len_frames += 1

    async def write(self, data):
        await self.send(data)

    def write_nowait(self, data):
        self.send_nowait(data)

    def full(self):
        if self.queue_limit_bytes > 0 and self.queue_len_bytes > self.queue_limit_bytes:
            return True
        elif (
            self.queue_limit_frames > 0
            and self.queue_len_frames > self.queue_limit_frames
        ):
            return True
        else:
            return False

    def idle(self):
        return self.empty() and not self.active

    async def wait(self):
        await self.idle_event.wait()

    def _handle_reset(self, state):
        super()._handle_reset(state)

        if state:
            for sig in self.bus.config.payload_keys:
                getattr(self.bus, sig).value = 0

            if hasattr(self.bus, "valid"):
                self.bus.valid.value = 0
            if hasattr(self.bus, "last"):
                self.bus.last.value = 0

            if self.current_frame:
                self.log.warning("Flushed transmit frame during reset")
                self.current_frame.handle_tx_complete()
                self.current_frame = None

    async def _run(self):
        frame = None
        frame_offset = 0
        self.active = False

        has_ready = hasattr(self.bus, "ready")
        has_valid = hasattr(self.bus, "valid")
        has_last = hasattr(self.bus, "last")

        clock_edge_event = RisingEdge(self.clock)

        while True:
            await clock_edge_event

            # read handshake signals
            ready_sample = (not has_ready) or self.bus.ready.value
            valid_sample = (not has_valid) or self.bus.valid.value

            if (ready_sample and valid_sample) or not valid_sample:
                if not frame and not self.queue.empty():
                    frame: SpinalStreamFrame = self.queue.get_nowait()
                    self.dequeue_event.set()
                    self.queue_len_bytes -= len(frame)
                    self.queue_len_frames -= 1
                    self.current_frame = frame
                    frame.sim_time_start = get_sim_time()
                    frame.sim_time_end = None
                    self.log.info("TX frame: %s", frame)
                    self.active = True
                    frame_offset = 0

                if frame and not self.pause:
                    # TODO: is there a faster way to iterate through payload?
                    if type(frame.payload) == list:
                        payload = frame.payload[frame_offset]
                    else:
                        payload = {
                            key: item[frame_offset]
                            for key, item in frame.payload.items()
                        }
                    frame_offset += 1

                    # Set payload signals
                    if type(frame.payload) == list:
                        # TODO: payload name
                        getattr(self.bus, self.bus.config.payload_keys[0]).value = int(
                            payload
                        )
                    else:
                        for key in self.bus.config.payload_keys:
                            sig: cocotb.handle.BinaryValue = getattr(self.bus, key)
                            sig.value = int(payload[key])

                    # Handle last
                    if frame_offset >= len(frame):
                        last_val = 1
                        frame.sim_time_end = get_sim_time()
                        frame.handle_tx_complete()
                        frame = None
                        self.current_frame = None
                    else:
                        last_val = 0

                    # Set valid and last signals
                    if has_valid:
                        self.bus.valid.value = 1
                    if has_last:
                        self.bus.last.value = last_val
                else:
                    if has_valid:
                        self.bus.valid.value = 0
                    if has_last:
                        self.bus.last.value = 0
                    self.active = bool(frame)
                    if not frame and self.queue.empty():
                        self.idle_event.set()
                        self.active_event.clear()

                        await self.active_event.wait()


class SpinalStreamMonitor(SpinalStreamBase):

    _type = "monitor"

    _init_x = False

    _valid_init = None
    _ready_init = None

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        *args,
        **kwargs,
    ):

        super().__init__(
            bus,
            clock,
            reset,
            reset_active_level,
            *args,
            **kwargs,
        )

        self.read_queue = []

        if hasattr(self.bus, "valid"):
            cocotb.start_soon(self._run_valid_monitor())
        if hasattr(self.bus, "ready"):
            cocotb.start_soon(self._run_ready_monitor())

    def _dequeue(self, frame):
        pass

    def _recv(self, frame) -> SpinalStreamFrame:
        if self.queue.empty():
            self.active_event.clear()
        self.queue_len_bytes -= len(frame)
        self.queue_len_frames -= 1
        self._dequeue(frame)
        return frame

    async def recv(self) -> SpinalStreamFrame:
        frame = await self.queue.get()
        return self._recv(frame)

    def recv_nowait(self) -> SpinalStreamFrame:
        frame = self.queue.get_nowait()
        return self._recv(frame)

    async def read(self, count=-1):
        # TODO: handle bundle
        while not self.read_queue:
            frame = await self.recv()
            if frame.config.simple():
                self.read_queue.extend(frame.payload)
            else:
                self.read_queue.append(frame)
        return self.read_nowait(count)

    def read_nowait(self, count=-1):
        if self.bus.config.has_last():
            return self.recv_nowait()

        while not self.empty():
            frame = self.recv_nowait()

            self.read_queue.append(frame)

        if len(self.read_queue) == 0:
            return None
        elif count < 0:
            count = len(self.read_queue)
        elif len(self.read_queue) < count:
            count = len(self.read_queue)

        data = self.read_queue[:count]
        del self.read_queue[:count]

        if count == 1:
            return data[0]

        res = data.pop(0)

        while len(data) > 0:
            res = merge_frames(res, data.pop(0))

        return res

    def idle(self):
        return not self.active

    async def wait(self, timeout=0, timeout_unit="ns"):
        if not self.empty():
            return
        if timeout:
            await First(self.active_event.wait(), Timer(timeout, timeout_unit))
        else:
            await self.active_event.wait()

    async def _run_valid_monitor(self):
        event = RisingEdge(self.bus.valid)

        while True:
            await event
            self.wake_event.set()

    async def _run_ready_monitor(self):
        event = RisingEdge(self.bus.ready)

        while True:
            await event
            self.wake_event.set()

    async def _run(self):
        frame = None
        self.active = False

        has_ready = hasattr(self.bus, "ready")
        has_valid = hasattr(self.bus, "valid")
        has_last = hasattr(self.bus, "last")

        clock_edge_event = RisingEdge(self.clock)

        wake_event = self.wake_event.wait()

        # TODO: fix all this
        while True:
            await clock_edge_event

            # read handshake signals
            ready_sample = (not has_ready) or self.bus.ready.value
            valid_sample = (not has_valid) or self.bus.valid.value

            if ready_sample and valid_sample:
                if not frame:
                    if self.byte_size == 8:
                        frame = SpinalStreamFrame(self.bus.config)
                    else:
                        frame = SpinalStreamFrame(self.bus.config)
                    frame.sim_time_start = get_sim_time()
                    self.active = True

                for offset in range(self.byte_lanes):
                    frame.tdata.append(
                        (self.bus.tdata.value.integer >> (offset * self.byte_size))
                        & self.byte_mask
                    )

                if not has_last or self.bus.last.value:
                    frame.sim_time_end = get_sim_time()
                    self.log.info("RX frame: %s", frame)

                    self.queue_len_bytes += len(frame)
                    self.queue_len_frames += 1

                    self.queue.put_nowait(frame)
                    self.active_event.set()

                    frame = None
            else:
                self.active = bool(frame)

                self.wake_event.clear()
                await wake_event


class SpinalStreamSink(SpinalStreamMonitor, SpinalStreamPause):

    _type = "sink"

    _init_x = False

    _valid_init = None
    _ready_init = 0

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        *args,
        **kwargs,
    ):

        self.queue_limit_bytes = -1
        self.queue_limit_frames = -1

        super().__init__(
            bus,
            clock,
            reset,
            reset_active_level,
            *args,
            **kwargs,
        )

    def full(self):
        if self.queue_limit_bytes > 0 and self.queue_len_bytes > self.queue_limit_bytes:
            return True
        elif (
            self.queue_limit_frames > 0
            and self.queue_len_frames > self.queue_limit_frames
        ):
            return True
        else:
            return False

    def _handle_reset(self, state):
        super()._handle_reset(state)

        if state:
            if hasattr(self.bus, "ready"):
                self.bus.ready.value = 0

    def _pause_update(self, val):
        self.wake_event.set()

    def _dequeue(self, frame):
        self.wake_event.set()

    async def _run(self):
        frame = None
        self.active = False

        has_ready = hasattr(self.bus, "ready")
        has_valid = hasattr(self.bus, "valid")
        has_last = hasattr(self.bus, "last")

        clock_edge_event = RisingEdge(self.clock)

        wake_event = self.wake_event.wait()

        while True:
            pause_sample = bool(self.pause)

            await clock_edge_event

            # read handshake signals
            ready_sample = (not has_ready) or self.bus.ready.value
            valid_sample = (not has_valid) or self.bus.valid.value

            if ready_sample and valid_sample:
                if not frame:
                    frame = SpinalStreamFrame(self.bus.config)
                    frame.sim_time_start = get_sim_time()
                    self.active = True

                    # if not self.bus.config.simple():
                    #     for key in self.bus.config.payload_keys:
                    #         frame.payload[key] = list()

                if self.bus.config.simple():
                    frame.payload.append(self.bus.payload.value.integer)
                else:
                    for key in self.bus.config.payload_keys:
                        frame.payload[key].append(getattr(self.bus, key).value.integer)

                if not has_last or self.bus.last.value:
                    frame.sim_time_end = get_sim_time()
                    self.log.info("RX frame: %s", frame)

                    self.queue_len_bytes += len(frame)
                    self.queue_len_frames += 1

                    self.queue.put_nowait(frame)
                    self.active_event.set()

                    frame = None
            else:
                self.active = bool(frame)

            if has_ready:
                paused = self.full() or pause_sample

                self.bus.ready.value = not paused

                if (not valid_sample or paused) and (pause_sample == bool(self.pause)):
                    self.wake_event.clear()
                    await wake_event
            else:
                if not valid_sample:
                    self.wake_event.clear()
                    await wake_event
