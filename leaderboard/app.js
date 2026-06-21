// gameboy-eval leaderboard: ranked table + an in-browser runner for the candidate wasm.

// Stacked horizontal bar per model: each bar = the three weighted contributions to the
// composite (0.60·replay + 0.20·audio + 0.20·procedural), so the bar length IS the score and
// you can see *why* a model ranks where it does (e.g. a missing audio segment).
// Greyscale to match the paper style: dark = replay, mid = audio, light = procedural.
const SECTIONS = [["replay", 0.60, "#333"], ["audio", 0.20, "#888"],
                  ["procedural", 0.20, "#ccc"]];

function renderChart(entries) {
  const W = 680, rowH = 30, padL = 150, padR = 50, padT = 26, padB = 8;
  const barW = W - padL - padR, H = padT + entries.length * rowH + padB;
  const x = (v) => padL + v * barW;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="composite score by section">`;
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    s += `<line x1="${x(t)}" y1="${padT - 4}" x2="${x(t)}" y2="${H - padB}" stroke="#ddd"/>` +
         `<text x="${x(t)}" y="${padT - 10}" fill="#888" font-size="10" text-anchor="middle">${t}</text>`;
  }
  entries.forEach((e, i) => {
    const y = padT + i * rowH + 4, h = rowH - 13;
    s += `<text x="${padL - 8}" y="${y + h / 2 + 4}" fill="#333" font-size="12" text-anchor="end">${e.name}</text>`;
    let cx = padL;
    for (const [k, w] of SECTIONS) {
      const wpx = (e.sections[k] || 0) * w * barW;
      s += `<rect x="${cx.toFixed(2)}" y="${y}" width="${wpx.toFixed(2)}" height="${h}" fill="${SECTIONS.find((q) => q[0] === k)[2]}"/>`;
      cx += wpx;
    }
    s += `<text x="${(cx + 6).toFixed(2)}" y="${y + h / 2 + 4}" fill="#111" font-size="11" font-weight="700">${e.overall.toFixed(3)}</text>`;
  });
  document.getElementById("chart").innerHTML = s + "</svg>";
  document.getElementById("legend").innerHTML =
    SECTIONS.map(([k, w, c]) => `<i style="background:${c}"></i>${k}·${w}`).join("");
}

async function renderBoard() {
  const data = await (await fetch("leaderboard.json")).json();
  document.getElementById("gen").textContent = data.generated;
  renderChart(data.entries);
  const tb = document.querySelector("#board tbody");
  data.entries.forEach((e, i) => {
    const s = e.sections;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="rank">${i + 1}</td>
      <td class="name">${e.name}</td>
      <td class="overall">${e.overall.toFixed(4)}
        <div class="bar"><i style="width:${(e.overall * 100).toFixed(1)}%"></i></div></td>
      <td class="band">${e.band}</td>
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
