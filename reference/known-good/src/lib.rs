//! Known-good reference candidate: a thin `spec/ABI.md` shim over the rboy DMG core.
//!
//! Used in M3b to validate the grader end-to-end (a correct emulator must score ~1.0 vs
//! the SameBoy oracle). This is NOT a model submission.

use rboy::device::Device;
use rboy::KeypadKey;

const FB_W: usize = 160;
const FB_H: usize = 144;

static mut ROM: Vec<u8> = Vec::new();
static mut DEV: Option<Device> = None;
static mut FB: Vec<u8> = Vec::new(); // RGBA, FB_W*FB_H*4

fn fb() -> &'static mut Vec<u8> {
    unsafe {
        if FB.is_empty() {
            FB = vec![255u8; FB_W * FB_H * 4];
        }
        &mut *core::ptr::addr_of_mut!(FB)
    }
}

#[no_mangle]
pub extern "C" fn alloc(size: u32) -> u32 {
    let mut v = vec![0u8; size as usize];
    let ptr = v.as_mut_ptr() as u32;
    core::mem::forget(v);
    ptr
}

#[no_mangle]
pub extern "C" fn dealloc(ptr: u32, size: u32) {
    unsafe {
        drop(Vec::from_raw_parts(ptr as *mut u8, size as usize, size as usize));
    }
}

#[no_mangle]
pub extern "C" fn init() {
    let _ = fb();
}

#[no_mangle]
pub extern "C" fn load_boot_rom(_ptr: u32, _len: u32) {
    // rboy has no boot-ROM path; it initializes to post-boot state. Ignored.
}

#[no_mangle]
pub extern "C" fn load_rom(ptr: u32, len: u32) {
    let data = unsafe { core::slice::from_raw_parts(ptr as *const u8, len as usize) }.to_vec();
    unsafe {
        ROM = data;
    }
}

#[no_mangle]
pub extern "C" fn reset() {
    unsafe {
        let rom = ROM.clone();
        DEV = Device::new_from_buffer(rom, true, None).ok();
    }
}

fn apply_keys(dev: &mut Device, mask: u32) {
    let table = [
        (0u32, KeypadKey::A),
        (1, KeypadKey::B),
        (2, KeypadKey::Select),
        (3, KeypadKey::Start),
        (4, KeypadKey::Right),
        (5, KeypadKey::Left),
        (6, KeypadKey::Up),
        (7, KeypadKey::Down),
    ];
    for (bit, key) in table {
        if (mask >> bit) & 1 == 1 {
            dev.keydown(key);
        } else {
            dev.keyup(key);
        }
    }
}

static mut KEYS: u32 = 0;

#[no_mangle]
pub extern "C" fn set_keys(mask: u32) {
    unsafe {
        KEYS = mask;
    }
}

#[no_mangle]
pub extern "C" fn run_frame() {
    unsafe {
        let dev = match DEV.as_mut() {
            Some(d) => d,
            None => return,
        };
        apply_keys(dev, KEYS);
        // Advance until the GPU signals a completed frame.
        let mut guard = 0u32;
        loop {
            dev.do_cycle();
            if dev.check_and_reset_gpu_updated() {
                break;
            }
            guard += 1;
            if guard > 2_000_000 {
                break; // safety against a stuck core
            }
        }
        let rgb = dev.get_gpu_data(); // RGB888, FB_W*FB_H*3
        let out = fb();
        for i in 0..(FB_W * FB_H) {
            out[i * 4] = rgb[i * 3];
            out[i * 4 + 1] = rgb[i * 3 + 1];
            out[i * 4 + 2] = rgb[i * 3 + 2];
            out[i * 4 + 3] = 255;
        }
    }
}

#[no_mangle]
pub extern "C" fn framebuffer() -> u32 {
    fb().as_ptr() as u32
}

#[no_mangle]
pub extern "C" fn audio() -> u32 {
    0
}

#[no_mangle]
pub extern "C" fn audio_len() -> u32 {
    0
}
