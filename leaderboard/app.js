// gameboy-eval leaderboard: ranked table + an in-browser runner for the candidate wasm.

const BANDS = {
  "Reference (indistinguishable)": "#22c55e",
  "Near-reference": "#22c55e",
  "Mostly playable": "#84cc16",
  "Plays incorrectly": "#eab308",
  "Barely works": "#f97316",
  "Doesn't run": "#ef4444",
};

async function renderBoard() {
  const data = await (await fetch("leaderboard.json")).json();
  document.getElementById("gen").textContent = data.generated;
  const tb = document.querySelector("#board tbody");
  data.entries.forEach((e, i) => {
    const s = e.sections;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="rank">${i + 1}</td>
      <td class="name">${e.name}</td>
      <td class="overall">${e.overall.toFixed(4)}
        <div class="bar"><i style="width:${(e.overall * 100).toFixed(1)}%"></i></div></td>
      <td class="band"><span style="color:${BANDS[e.band] || "#9aa3ad"}">●</span> ${e.band}</td>
      <td class="sections">${s.replay.toFixed(2)} / ${s.audio.toFixed(2)} / ${s.procedural.toFixed(2)}</td>`;
    tb.appendChild(tr);
  });
}

// --- in-browser emulator (drives spec/ABI.md, same as the grader's WasmEmu) ---
const KEYS = { ArrowRight: 4, ArrowLeft: 5, ArrowUp: 6, ArrowDown: 7,
               z: 0, x: 1, Shift: 2, Enter: 3 };
let keymask = 0;

async function makePlayer() {
  const { instance } = await WebAssembly.instantiateStreaming(fetch("demo/gb_emu.wasm"), {});
  const ex = instance.exports;
  const mem = () => new Uint8Array(ex.memory.buffer);

  const put = (bytes) => { const p = ex.alloc(bytes.length); mem().set(bytes, p); return [p, bytes.length]; };
  const fetchBytes = async (u) => new Uint8Array(await (await fetch(u)).arrayBuffer());

  ex.init?.();
  ex.load_boot_rom?.(...put(await fetchBytes("demo/boot_rom.bin")));
  ex.load_rom(...put(await fetchBytes("demo/dmg-acid2.gb")));
  ex.reset();

  const cv = document.getElementById("screen");
  const ctx = cv.getContext("2d");
  const img = ctx.createImageData(160, 144);

  function frame() {
    ex.set_keys(keymask);
    ex.run_frame();
    const ptr = ex.framebuffer();
    img.data.set(mem().subarray(ptr, ptr + 160 * 144 * 4));
    ctx.putImageData(img, 0, 0);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

addEventListener("keydown", (e) => { if (e.key in KEYS) { keymask |= 1 << KEYS[e.key]; e.preventDefault(); } });
addEventListener("keyup", (e) => { if (e.key in KEYS) keymask &= ~(1 << KEYS[e.key]); });

document.getElementById("run").addEventListener("click", (e) => {
  e.target.disabled = true;
  e.target.textContent = "running…";
  makePlayer();
});

renderBoard();
