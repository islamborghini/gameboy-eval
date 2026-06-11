"""Source-agnostic emulator seam.

The lockstep grader drives everything through the `Emulator` protocol so it never
special-cases whether it is talking to the WASM *candidate* or the SameBoy *oracle*.

- `WasmEmu`  drives a candidate `gb_emu.wasm` (the graded artifact) via wasmtime.
- `OracleEmu` (see oracle/) drives the SameBoy reference.

Framebuffers are returned as uint8 [144, 160, 4] RGBA; audio as int16 [n, 2] @ 48 kHz.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from wasmtime import Engine, Instance, Module, Store

FB_W, FB_H = 160, 144
FB_BYTES = FB_W * FB_H * 4

# Joypad bit layout — must match spec/ABI.md (1 = pressed).
BTN = {
    "A": 0, "B": 1, "SELECT": 2, "START": 3,
    "RIGHT": 4, "LEFT": 5, "UP": 6, "DOWN": 7,
}


def keymask(*names: str) -> int:
    m = 0
    for n in names:
        m |= 1 << BTN[n.upper()]
    return m


@runtime_checkable
class Emulator(Protocol):
    """Everything the lockstep driver needs from either side."""

    def load(self, rom: bytes, boot_rom: bytes | None = None) -> None: ...
    def reset(self) -> None: ...
    def set_keys(self, mask: int) -> None: ...
    def run_frame(self) -> None: ...
    def framebuffer(self) -> np.ndarray: ...  # uint8 [144, 160, 4] RGBA
    def audio(self) -> np.ndarray: ...        # int16 [n, 2]


class WasmEmu:
    """Drive a candidate `gb_emu.wasm` through the ABI in spec/ABI.md via wasmtime."""

    def __init__(self, wasm_path: str | Path):
        self.engine = Engine()
        self.store = Store(self.engine)
        self.module = Module.from_file(self.engine, str(wasm_path))
        self.inst = Instance(self.store, self.module, [])
        self.ex = self.inst.exports(self.store)
        self.mem = self.ex["memory"]

    # -- helpers -----------------------------------------------------------
    def _maybe(self, name: str):
        try:
            return self.ex[name]
        except KeyError:
            return None

    def _call(self, name: str, *args):
        return self.ex[name](self.store, *args)

    def _alloc_write(self, data: bytes) -> tuple[int, int]:
        ptr = self._call("alloc", len(data))
        self.mem.write(self.store, data, ptr)
        return ptr, len(data)

    # -- Emulator protocol -------------------------------------------------
    def load(self, rom: bytes, boot_rom: bytes | None = None) -> None:
        init = self._maybe("init")
        if init is not None:
            init(self.store)
        if boot_rom is not None and self._maybe("load_boot_rom") is not None:
            ptr, n = self._alloc_write(boot_rom)
            self._call("load_boot_rom", ptr, n)
        ptr, n = self._alloc_write(rom)
        self._call("load_rom", ptr, n)
        self.reset()

    def reset(self) -> None:
        reset = self._maybe("reset")
        if reset is not None:
            reset(self.store)

    def set_keys(self, mask: int) -> None:
        self._call("set_keys", mask & 0xFF)

    def run_frame(self) -> None:
        self._call("run_frame")

    def framebuffer(self) -> np.ndarray:
        ptr = self._call("framebuffer")
        buf = self.mem.read(self.store, ptr, ptr + FB_BYTES)
        return np.frombuffer(bytes(buf), dtype=np.uint8).reshape(FB_H, FB_W, 4)

    def audio(self) -> np.ndarray:
        if self._maybe("audio") is None or self._maybe("audio_len") is None:
            return np.zeros((0, 2), dtype=np.int16)
        n = self._call("audio_len")
        if n == 0:
            return np.zeros((0, 2), dtype=np.int16)
        ptr = self._call("audio")
        buf = self.mem.read(self.store, ptr, ptr + n * 2)
        return np.frombuffer(bytes(buf), dtype=np.int16).reshape(-1, 2)
