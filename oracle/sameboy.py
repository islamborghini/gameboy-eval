"""Drive the SameBoy reference as a black box via its libretro core (ctypes).

For M2/M3 (metric validation) we drive the core *in-process*: it is the simplest way to
get exact one-frame stepping + input injection + framebuffer/audio readout, and it lets
`OracleEmu` satisfy the same `Emulator` protocol as the WASM candidate. The HTTP black-box
wrapper (so the agent can't see the binary) is added at M5 around this same driver.

Pixel output is normalized to uint8 [144,160,4] RGBA to match spec/ABI.md.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path

import numpy as np

# --- libretro constants ----------------------------------------------------
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_SET_PIXEL_FORMAT = 10
ENV_GET_VARIABLE = 15
ENV_SET_VARIABLES = 16
ENV_GET_VARIABLE_UPDATE = 17
ENV_GET_LOG_INTERFACE = 27
ENV_GET_SAVE_DIRECTORY = 31

# libretro enum: 0RGB1555=0, XRGB8888=1, RGB565=2
PIXEL_FORMAT_XRGB8888 = 1

DEVICE_JOYPAD = 1
# RETRO_DEVICE_ID_JOYPAD_* id  ->  our spec/ABI.md joypad bit
JOYPAD_ID_TO_BIT = {
    8: 0,  # A
    0: 1,  # B
    2: 2,  # Select
    3: 3,  # Start
    7: 4,  # Right
    6: 5,  # Left
    4: 6,  # Up
    5: 7,  # Down
}

# Force the original Game Boy (DMG) so behavior + boot ROM match the candidate.
CORE_OPTIONS = {b"sameboy_model": b"Game Boy"}

# --- libretro structs ------------------------------------------------------
class retro_game_info(C.Structure):
    _fields_ = [
        ("path", C.c_char_p),
        ("data", C.c_void_p),
        ("size", C.c_size_t),
        ("meta", C.c_char_p),
    ]


class retro_variable(C.Structure):
    _fields_ = [("key", C.c_char_p), ("value", C.c_char_p)]


class retro_game_geometry(C.Structure):
    _fields_ = [
        ("base_width", C.c_uint), ("base_height", C.c_uint),
        ("max_width", C.c_uint), ("max_height", C.c_uint),
        ("aspect_ratio", C.c_float),
    ]


class retro_system_timing(C.Structure):
    _fields_ = [("fps", C.c_double), ("sample_rate", C.c_double)]


class retro_system_av_info(C.Structure):
    _fields_ = [("geometry", retro_game_geometry), ("timing", retro_system_timing)]


# --- callback function types ----------------------------------------------
environment_t = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
video_refresh_t = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
audio_sample_t = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
audio_batch_t = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
input_poll_t = C.CFUNCTYPE(None)
input_state_t = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
log_printf_t = C.CFUNCTYPE(None, C.c_int, C.c_char_p)  # variadic; extra args ignored


class retro_log_callback(C.Structure):
    _fields_ = [("log", log_printf_t)]


FB_W, FB_H = 160, 144

# Library + boot-ROM dir are env-overridable so the same driver runs against a macOS .dylib
# (host) or a Linux .so (the oracle container).
_HERE = Path(__file__).resolve().parent
DEFAULT_DYLIB = os.environ.get("SAMEBOY_LIB", str(_HERE / "SameBoy/build/bin/sameboy_libretro.dylib"))
# Directory the core scans for an external boot ROM (dmg_boot.bin). Pointing it here
# makes boot-ROM choice explicit instead of relying on the embedded fallback.
BOOTROM_DIR = os.environ.get("SAMEBOY_BOOTROMS", str(_HERE / "SameBoy/build/bin/BootROMs"))


class SameBoyCore:
    """Thin ctypes wrapper around a single instance of the SameBoy libretro core."""

    def __init__(self, dylib: str | Path = DEFAULT_DYLIB):
        self.lib = C.CDLL(str(dylib))
        self._bind()
        self.pixel_format = PIXEL_FORMAT_XRGB8888
        self.sample_rate = 0.0
        self.fps = 0.0
        self._keymask = 0
        self._frame = np.zeros((FB_H, FB_W, 4), dtype=np.uint8)
        self._audio_chunks: list[np.ndarray] = []
        self._value_bufs: list[bytes] = []  # keep GET_VARIABLE strings alive
        self._sysdir_buf = None  # keep the system-directory path alive
        self._log_cb = log_printf_t(lambda level, fmt: None)  # swallow core logs
        self._rom_buf = None  # keep ROM bytes alive across retro_run
        self._install_callbacks()
        self.lib.retro_init()
        self._loaded = False

    # -- binding -----------------------------------------------------------
    def _bind(self):
        L = self.lib
        L.retro_set_environment.argtypes = [environment_t]
        L.retro_set_video_refresh.argtypes = [video_refresh_t]
        L.retro_set_audio_sample.argtypes = [audio_sample_t]
        L.retro_set_audio_sample_batch.argtypes = [audio_batch_t]
        L.retro_set_input_poll.argtypes = [input_poll_t]
        L.retro_set_input_state.argtypes = [input_state_t]
        L.retro_load_game.argtypes = [C.POINTER(retro_game_info)]
        L.retro_load_game.restype = C.c_bool
        L.retro_get_system_av_info.argtypes = [C.POINTER(retro_system_av_info)]
        for fn in ("retro_init", "retro_deinit", "retro_run", "retro_reset",
                   "retro_unload_game"):
            getattr(L, fn).argtypes = []

    # -- callbacks ---------------------------------------------------------
    def _install_callbacks(self):
        self._cb_env = environment_t(self._on_environment)
        self._cb_video = video_refresh_t(self._on_video)
        self._cb_audio = audio_sample_t(self._on_audio_sample)
        self._cb_batch = audio_batch_t(self._on_audio_batch)
        self._cb_poll = input_poll_t(lambda: None)
        self._cb_input = input_state_t(self._on_input_state)
        self.lib.retro_set_environment(self._cb_env)
        self.lib.retro_set_video_refresh(self._cb_video)
        self.lib.retro_set_audio_sample(self._cb_audio)
        self.lib.retro_set_audio_sample_batch(self._cb_batch)
        self.lib.retro_set_input_poll(self._cb_poll)
        self.lib.retro_set_input_state(self._cb_input)

    def _on_environment(self, cmd, data):
        # NOTE: `data` is a raw integer address; read it with `from_address`,
        # not `ctypes.cast` (which misreads an int argument).
        if not data:
            return False
        if cmd == ENV_SET_PIXEL_FORMAT:
            self.pixel_format = C.c_int.from_address(data).value
            return self.pixel_format == PIXEL_FORMAT_XRGB8888
        if cmd == ENV_GET_VARIABLE:
            var = retro_variable.from_address(data)
            val = CORE_OPTIONS.get(var.key)
            if val is None:
                return False
            self._value_bufs.append(val)  # keep the bytes alive for the core
            var.value = val
            return True
        if cmd == ENV_GET_VARIABLE_UPDATE:
            C.c_bool.from_address(data).value = False
            return True
        if cmd == ENV_SET_VARIABLES:
            return True
        if cmd == ENV_GET_LOG_INTERFACE:
            retro_log_callback.from_address(data).log = self._log_cb
            return True
        if cmd in (ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY):
            if self._sysdir_buf is None:
                self._sysdir_buf = C.create_string_buffer(str(BOOTROM_DIR).encode())
            C.c_void_p.from_address(data).value = C.addressof(self._sysdir_buf)
            return True
        return False

    def _on_video(self, data, width, height, pitch):
        if not data:
            return
        raw = C.string_at(data, pitch * height)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, pitch)
        arr = arr[:, : width * 4].reshape(height, width, 4)  # bytes: B,G,R,X
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[..., 0] = arr[..., 2]  # R
        rgba[..., 1] = arr[..., 1]  # G
        rgba[..., 2] = arr[..., 0]  # B
        rgba[..., 3] = 255
        self._frame = rgba

    def _on_audio_sample(self, left, right):
        self._audio_chunks.append(np.array([[left, right]], dtype=np.int16))

    def _on_audio_batch(self, data, frames):
        raw = C.string_at(data, frames * 2 * 2)
        self._audio_chunks.append(
            np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).copy()
        )
        return frames

    def _on_input_state(self, port, device, index, id_):
        if port != 0 or device != DEVICE_JOYPAD:
            return 0
        bit = JOYPAD_ID_TO_BIT.get(id_)
        if bit is None:
            return 0
        return 1 if (self._keymask >> bit) & 1 else 0

    # -- public API --------------------------------------------------------
    def load(self, rom: bytes) -> None:
        self._rom_buf = (C.c_ubyte * len(rom)).from_buffer_copy(rom)
        info = retro_game_info(
            path=None, data=C.cast(self._rom_buf, C.c_void_p), size=len(rom), meta=None
        )
        if not self.lib.retro_load_game(C.byref(info)):
            raise RuntimeError("retro_load_game failed")
        av = retro_system_av_info()
        self.lib.retro_get_system_av_info(C.byref(av))
        self.fps = av.timing.fps
        self.sample_rate = av.timing.sample_rate
        self._loaded = True

    def reset(self) -> None:
        self.lib.retro_reset()

    def set_keys(self, mask: int) -> None:
        self._keymask = mask & 0xFF

    def run_frame(self) -> None:
        self._audio_chunks = []
        self.lib.retro_run()

    def framebuffer(self) -> np.ndarray:
        return self._frame

    def audio(self) -> np.ndarray:
        if not self._audio_chunks:
            return np.zeros((0, 2), dtype=np.int16)
        return np.concatenate(self._audio_chunks, axis=0)


class OracleEmu:
    """`Emulator`-protocol adapter over `SameBoyCore` (boot ROM is embedded in the core)."""

    def __init__(self, dylib: str | Path = DEFAULT_DYLIB):
        self.core = SameBoyCore(dylib)

    def load(self, rom: bytes, boot_rom: bytes | None = None) -> None:
        self.core.load(rom)  # core supplies its own open DMG boot ROM

    def reset(self) -> None:
        self.core.reset()

    def set_keys(self, mask: int) -> None:
        self.core.set_keys(mask)

    def run_frame(self) -> None:
        self.core.run_frame()

    def framebuffer(self) -> np.ndarray:
        return self.core.framebuffer()

    def audio(self) -> np.ndarray:
        return self.core.audio()
