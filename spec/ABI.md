# Candidate ABI — Game Boy (DMG) emulator, `wasm32-unknown-unknown`

This is the **only** fixed contract. The internal design of the emulator is entirely up
to the candidate; the grader interacts with it exclusively through the exports below.

## Artifact

- A Rust **cargo** project whose library crate is named **`gb_emu`** with
  `crate-type = ["cdylib"]`.
- Built with **exactly**:
  ```
  cargo build --release --lib --target wasm32-unknown-unknown
  ```
- Producing the artifact at the **fixed path**:
  ```
  target/wasm32-unknown-unknown/release/gb_emu.wasm
  ```
- **No** `.cargo/config.toml`, **no** custom `RUSTFLAGS`, no build scripts that alter the
  target or linker. The module must export its linear memory as `memory` (the default for
  a `wasm32-unknown-unknown` cdylib).

## Determinism (load-bearing)

The Game Boy has no entropy source. Given the same boot ROM, cartridge ROM, and input
sequence, the emulator **must** produce a bit-identical sequence of framebuffers and audio
on every run. No wall-clock, no time-seeded RNG, no host I/O.

## Memory & data exchange

The host reads results directly from the module's exported linear `memory`. Buffers
returned by `framebuffer()` / `audio()` must remain valid and stable until the next call
to `run_frame()`.

All exports use the C ABI (`#[no_mangle] pub extern "C"`). Pointers are `u32` byte offsets
into linear memory. Integers are little-endian.

## Exports

### Allocation
```
alloc(size: u32) -> u32        // allocate `size` bytes, return offset (ptr); 0 on failure
dealloc(ptr: u32, size: u32)   // free a prior allocation
```
Used by the host to hand ROM bytes to the module: `alloc` a buffer, the host writes bytes
into `memory` at that offset, then calls `load_rom` / `load_boot_rom`.

### Lifecycle
```
init()                         // construct/initialize the emulator instance (call once, first)
load_boot_rom(ptr: u32, len: u32)  // copy the DMG boot ROM (256 bytes). Optional but required
                                   //   for faithful lockstep with the oracle.
load_rom(ptr: u32, len: u32)   // copy the cartridge ROM image
reset()                        // power-cycle. If a boot ROM was loaded, execution begins in it
                               //   (so the boot animation is reproduced); otherwise begin at
                               //   0x0100 with the canonical post-boot register/IO state.
```
Call order for a run: `init()` → `load_boot_rom(...)` → `load_rom(...)` → `reset()`.

### Per-frame stepping (lockstep)
```
set_keys(mask: u32)            // current joypad state; 1 = pressed. Bit layout:
                               //   bit0=A  bit1=B  bit2=Select  bit3=Start
                               //   bit4=Right bit5=Left bit6=Up bit7=Down
run_frame()                    // advance until exactly one video frame has been produced
                               //   (one DMG frame = 70224 T-cycles; return at VBlank onset)
framebuffer() -> u32           // ptr to the completed frame: 160x144 pixels, RGBA8888,
                               //   4 bytes/pixel, row-major from top-left = 92160 bytes.
                               //   Alpha is ignored by the grader (set 255). The candidate may
                               //   use any DMG palette; the grader color-normalizes before SSIM.
audio() -> u32                 // ptr to audio generated during the last run_frame:
audio_len() -> u32             // number of i16 samples (interleaved stereo L,R) in that buffer.
                               //   Sample format: signed 16-bit, 48000 Hz, stereo interleaved.
                               //   (Audio grading is post-M4; until implemented a candidate may
                               //    return audio_len()==0, but the exports must exist.)
```

### Optional debug exports (used only by the internal CPU smoke-test, never by replay grading)
```
cpu_pc() -> u32                // current PC (optional)
cycles() -> u64                // total T-cycles elapsed since reset (optional)
```

## Frame-boundary convention

One `run_frame()` call == one produced video frame. The grader aligns candidate frame *N*
to oracle frame *N*, starting from `reset()`. Frames produced during the boot animation are
included in the sequence. The oracle (SameBoy) is driven through an identically-shaped
session API so that frame *N* means the same thing on both sides.

## Reference skeleton (signatures only — internal design is yours)

```rust
// lib.rs — crate `gb_emu`, crate-type = ["cdylib"]
#[no_mangle] pub extern "C" fn alloc(size: u32) -> u32 { /* ... */ 0 }
#[no_mangle] pub extern "C" fn dealloc(ptr: u32, size: u32) { /* ... */ }
#[no_mangle] pub extern "C" fn init() { /* ... */ }
#[no_mangle] pub extern "C" fn load_boot_rom(ptr: u32, len: u32) { /* ... */ }
#[no_mangle] pub extern "C" fn load_rom(ptr: u32, len: u32) { /* ... */ }
#[no_mangle] pub extern "C" fn reset() { /* ... */ }
#[no_mangle] pub extern "C" fn set_keys(mask: u32) { /* ... */ }
#[no_mangle] pub extern "C" fn run_frame() { /* ... */ }
#[no_mangle] pub extern "C" fn framebuffer() -> u32 { /* ... */ 0 }
#[no_mangle] pub extern "C" fn audio() -> u32 { /* ... */ 0 }
#[no_mangle] pub extern "C" fn audio_len() -> u32 { /* ... */ 0 }
```
