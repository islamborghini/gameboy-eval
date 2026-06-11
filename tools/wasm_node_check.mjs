// Validate that a candidate gb_emu.wasm runs via the browser WebAssembly API (node has the
// same API). Discovers imports and confirms the ABI produces a real frame from JS.
//   node tools/wasm_node_check.mjs [path/to/gb_emu.wasm]
import { readFileSync } from "fs";

const wasmPath = process.argv[2] || "leaderboard/demo/gb_emu.wasm";
const bytes = readFileSync(wasmPath);
const mod = await WebAssembly.compile(bytes);

const imports = WebAssembly.Module.imports(mod);
console.log("imports:", imports.length ? imports.map((i) => `${i.module}.${i.name}`).join(", ") : "(none)");

// Stub any imports so the module instantiates regardless.
const importObject = {};
for (const imp of imports) {
  (importObject[imp.module] ??= {})[imp.name] = () => 0;
}
const inst = await WebAssembly.instantiate(mod, importObject);
const ex = inst.exports;
const mem = ex.memory;

function load(buf) {
  const ptr = ex.alloc(buf.length);
  new Uint8Array(mem.buffer).set(buf, ptr);
  return [ptr, buf.length];
}

ex.init?.();
ex.load_boot_rom?.(...load(readFileSync("leaderboard/demo/boot_rom.bin")));
ex.load_rom(...load(readFileSync("leaderboard/demo/dmg-acid2.gb")));
ex.reset();
for (let i = 0; i < 220; i++) {
  ex.set_keys(0);
  ex.run_frame();
}
const fbPtr = ex.framebuffer();
const fb = new Uint8Array(mem.buffer, fbPtr, 160 * 144 * 4);

const colors = new Set();
let sum = 0;
for (let i = 0; i < fb.length; i += 4) {
  colors.add((fb[i] << 16) | (fb[i + 1] << 8) | fb[i + 2]);
  sum += fb[i];
}
console.log(`exports: ${WebAssembly.Module.exports(mod).map((e) => e.name).join(", ")}`);
console.log(`framebuffer: luma~${(sum / (160 * 144)).toFixed(1)}, unique colors=${colors.size}`);
console.log(colors.size >= 2 ? "WASM-IN-JS OK" : "BLANK (problem)");
