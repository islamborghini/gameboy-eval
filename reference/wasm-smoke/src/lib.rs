//! Minimal `wasm32-unknown-unknown` cdylib used to validate two things in M1:
//!  1. the Rust -> wasm toolchain produces a loadable module, and
//!  2. the host-side wasmtime path that the grader will use to read a framebuffer
//!     out of the module's linear `memory` actually works.

use core::ptr::addr_of_mut;

static mut BUF: [u8; 16] = [0u8; 16];

#[no_mangle]
pub extern "C" fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[no_mangle]
pub extern "C" fn answer() -> i32 {
    42
}

/// Return the linear-memory offset of a small static buffer.
#[no_mangle]
pub extern "C" fn smoke_buffer() -> u32 {
    addr_of_mut!(BUF) as u32
}

/// Fill that buffer with the low byte of `v`; the host reads it back to confirm it can
/// access module memory at a returned pointer (the framebuffer mechanism).
#[no_mangle]
pub extern "C" fn smoke_fill(v: u32) {
    let p = addr_of_mut!(BUF) as *mut u8;
    for i in 0..16 {
        unsafe { p.add(i).write(v as u8) };
    }
}
