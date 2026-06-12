// gameboy-eval control panel — a thin GUI over the harness/grader/leaderboard CLIs.
// Each menu item renders a small form into <main>; "run" actions POST /api/run and then
// poll /api/log, streaming the command's stdout into a black log panel.

const main = document.getElementById("main");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const getJSON = async (u) => (await fetch(u)).json();
const postJSON = async (u, body) =>
  (await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body) })).json();

// --- job runner: stream a command's output into the page -------------------
let pollTimer = null;
let clipTimer = null;
let candTimer = null;

// Candidates table — re-fetches itself every few seconds while a run is in progress, so the
// status column (running / done / stopped) stays live without a manual refresh.
const STATUS_CLASS = { running: "running", stopped: "failed", done: "" };

async function drawCandidates() {
  if (!document.getElementById("c")) return;        // navigated away
  const rows = await getJSON("/api/candidates");
  const c = document.getElementById("c");
  if (!c) return;
  c.innerHTML = rows.length ? `
    <table><thead><tr><th>candidate</th><th>status</th><th>model</th><th>best score</th>
      <th>artifact</th></tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td>${esc(r.name)}</td>
        <td><span class="badge ${STATUS_CLASS[r.status] ?? ""}">${esc(r.status ?? "—")}</span></td>
        <td>${esc(r.model ?? "—")}</td>
        <td>${r.best_score == null ? "—" : Number(r.best_score).toFixed(4)}</td>
        <td>${r.artifact ? "yes" : "—"}</td></tr>`).join("")}
    </tbody></table>
    <p class="hint">Auto-refreshes while a run is in progress.</p>` :
    `<p class="hint">No candidates yet. Run a generation.</p>`;
  clearTimeout(candTimer);
  if (rows.some((r) => r.status === "running")) candTimer = setTimeout(drawCandidates, 3000);
}

// fetch a server-rendered clip and decode its base64 PNGs into <img> frames.
async function loadClip(target, rom, frames, statusEl) {
  statusEl.textContent = `rendering ${target}…`;
  const d = await getJSON(`/api/clip?target=${encodeURIComponent(target)}` +
                          `&rom=${encodeURIComponent(rom)}&frames=${frames}`);
  if (d.error && !(d.frames || []).length) { statusEl.textContent = "error: " + d.error; return { imgs: [] }; }
  const imgs = await Promise.all((d.frames || []).map((b) => new Promise((res) => {
    const im = new Image(); im.onload = () => res(im); im.src = "data:image/png;base64," + b;
  })));
  statusEl.textContent = d.error ? `${imgs.length} frames · stopped: ${d.error}` : `${imgs.length} frames`;
  return { imgs };
}

async function runJob(action, params, anchorEl) {
  if (anchorEl) anchorEl.disabled = true;
  const res = await postJSON("/api/run", { action, ...params });
  if (res.error) { if (anchorEl) anchorEl.disabled = false; return alert(res.error); }

  main.insertAdjacentHTML("beforeend", `
    <div id="job">
      <p style="margin-top:18px">
        <span class="badge running" id="jobstatus">running</span>
        <b>${esc(res.title)}</b>
        <button class="act" id="jobstop" style="margin:0 0 0 10px;padding:2px 10px">stop</button>
      </p>
      <pre class="joblog" id="joblog"></pre>
    </div>`);
  const log = document.getElementById("joblog");
  const badge = document.getElementById("jobstatus");
  document.getElementById("jobstop").onclick = () => postJSON("/api/stop", { id: res.id });

  clearInterval(pollTimer);
  let offset = 0;
  pollTimer = setInterval(async () => {
    const d = await getJSON(`/api/log?id=${res.id}&offset=${offset}`);
    if (d.error) return;
    offset = d.offset;
    if (d.lines.length) {
      log.textContent += d.lines.join("\n") + "\n";
      log.scrollTop = log.scrollHeight;
    }
    if (d.status !== "running") {
      clearInterval(pollTimer);
      badge.textContent = d.status + (d.returncode ? ` (exit ${d.returncode})` : "");
      badge.className = "badge " + d.status;
      if (anchorEl) anchorEl.disabled = false;
    }
  }, 1000);
}

// --- in-browser player: run a candidate's wasm with live keyboard input -----
// Drives the spec/ABI.md exports (same as the grader's WasmEmu), but interactively. The ROM is
// read locally from a file picker — nothing is uploaded to the server.
const PLAY_KEYS = { ArrowRight: 4, ArrowLeft: 5, ArrowUp: 6, ArrowDown: 7,
                    z: 0, x: 1, Shift: 2, Enter: 3 };
let playMask = 0, playRAF = null, audioCtx = null, nextAudioTime = 0;
function cancelPlay() {
  if (playRAF) cancelAnimationFrame(playRAF);
  playRAF = null;
  if (audioCtx) { audioCtx.close(); audioCtx = null; }
}

// queue one run_frame's worth of the candidate's audio (i16 interleaved stereo @ 48kHz) by
// scheduling a small AudioBuffer right after the previous one — emulator output you can hear.
function pushAudio(s) {
  const n = s.ex.audio_len();
  if (!n) return;
  const frames = n >> 1;
  const src = new Int16Array(s.ex.memory.buffer, s.ex.audio(), n);
  const buf = audioCtx.createBuffer(2, frames, 48000);
  const L = buf.getChannelData(0), R = buf.getChannelData(1);
  for (let i = 0; i < frames; i++) { L[i] = src[2 * i] / 32768; R[i] = src[2 * i + 1] / 32768; }
  const node = audioCtx.createBufferSource();
  node.buffer = buf;
  node.connect(audioCtx.destination);
  const now = audioCtx.currentTime;
  if (nextAudioTime < now) nextAudioTime = now + 0.03;   // resync if playback fell behind
  node.start(nextAudioTime);
  nextAudioTime += buf.duration;
}
addEventListener("keydown", (e) => {
  if (playRAF != null && e.key in PLAY_KEYS) { playMask |= 1 << PLAY_KEYS[e.key]; e.preventDefault(); }
});
addEventListener("keyup", (e) => { if (e.key in PLAY_KEYS) playMask &= ~(1 << PLAY_KEYS[e.key]); });

// boot one wasm emulator (candidate or reference) on a ROM via the spec/ABI.md exports.
async function bootEmu(wasmUrl, rom, useboot) {
  const { instance } = await WebAssembly.instantiateStreaming(fetch(wasmUrl), {});
  const ex = instance.exports;
  const mem = () => new Uint8Array(ex.memory.buffer);
  const put = (b) => { const p = ex.alloc(b.length); mem().set(b, p); return [p, b.length]; };
  ex.init?.();
  if (useboot && ex.load_boot_rom) {
    const boot = new Uint8Array(await (await fetch("/leaderboard/demo/boot_rom.bin")).arrayBuffer());
    ex.load_boot_rom(...put(boot));
  }
  ex.load_rom(...put(rom));
  ex.reset();
  return { ex, mem };
}

async function startPlay() {
  cancelPlay();
  const status = document.getElementById("plstatus");
  const file = document.getElementById("rom").files[0];
  if (!file) { status.textContent = "Choose a .gb ROM file first."; return; }
  const useboot = document.getElementById("useboot").checked;
  const vs = document.getElementById("vsref").checked;
  document.getElementById("refpane").style.display = vs ? "" : "none";
  if (document.getElementById("sound").checked) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    nextAudioTime = 0;
  }
  status.textContent = "loading…";
  try {
    const rom = new Uint8Array(await file.arrayBuffer());
    const cand = document.getElementById("cand").value;
    const attach = (id, e) => {
      const ctx = document.getElementById(id).getContext("2d");
      return { ...e, ctx, img: ctx.createImageData(160, 144) };
    };
    const screens = [
      attach("gbcv", await bootEmu(`/candidate/${encodeURIComponent(cand)}/gb_emu.wasm`, rom, useboot)),
    ];
    if (vs) screens.push(attach("gbcv2", await bootEmu("/leaderboard/demo/gb_emu.wasm", rom, useboot)));
    const cv = document.getElementById("gbcv");
    cv.tabIndex = 0; cv.focus();
    status.textContent = `playing ${file.name} — click the left screen, then use the keys` +
      (vs ? " (both run the same input — watch where they diverge)" : "");
    const frame = () => {
      for (const s of screens) {
        s.ex.set_keys(playMask); s.ex.run_frame();
        const ptr = s.ex.framebuffer();
        s.img.data.set(s.mem().subarray(ptr, ptr + 160 * 144 * 4));
        s.ctx.putImageData(s.img, 0, 0);
      }
      if (audioCtx && screens[0].ex.audio_len) pushAudio(screens[0]);
      playRAF = requestAnimationFrame(frame);
    };
    playRAF = requestAnimationFrame(frame);
  } catch (err) {
    status.textContent = "failed: " + err;
  }
}

// --- views -----------------------------------------------------------------
const views = {
  async dashboard() {
    main.innerHTML = `<h2>Dashboard</h2><div id="st">loading…</div>`;
    const s = await getJSON("/api/status");
    const p = s.provider;
    const mark = (b) => b ? "ok" : "no";
    document.getElementById("st").innerHTML = `
      <div class="kv"><b>active provider</b> ${esc(p.active)}</div>
      <div class="kv ${mark(s.docker)}"><b>docker running</b> ${s.docker ? "yes" : "no"}</div>
      <div class="kv ${mark(s.gen_image)}"><b>build image (gameboy-eval-gen)</b> ${s.gen_image ? "built" : "missing"}</div>
      <div class="kv ${mark(s.data_present)}"><b>test ROMs (data/test-roms)</b> ${s.data_present ? "present" : "not fetched"}</div>
      <div class="kv"><b>candidates</b> ${s.candidates}</div>
      <div class="kv"><b>python</b> ${esc(s.python)}</div>
      <p class="hint">Set up the prerequisites once via the Generate page (build image) and
        Leaderboard page, or from the README. Everything below runs the same CLI scripts.</p>
      <button class="act" id="dofetch">Fetch test ROMs (scripts/fetch_data.py)</button>`;
    document.getElementById("dofetch").onclick = (e) => runJob("fetch", {}, e.target);
  },

  generate() {
    main.innerHTML = `
      <h2>Generate</h2>
      <p class="hint">Runs <code>harness/generate.py</code>: ask the model for
        <code>src/lib.rs</code>, build it offline in Docker, grade vs the oracle, feed back.
        The active provider is set on the Provider page.</p>
      <label>Model id</label>
      <input id="model" list="models" placeholder="qwen2.5-coder:7b" />
      <datalist id="models">
        <option value="qwen2.5-coder:7b">
        <option value="qwen3:8b">
        <option value="qwen/qwen-2.5-coder-32b-instruct">
        <option value="anthropic/claude-3.5-sonnet">
        <option value="openai/gpt-4o-mini">
      </datalist>
      <div class="row">
        <div><label>Iterations</label><input id="iters" type="number" value="4" min="1"
             style="min-width:120px" /></div>
        <div><label>or Minutes (continuous; 0 = use iterations)</label>
             <input id="minutes" type="number" value="0" min="0" style="min-width:120px" /></div>
      </div>
      <label style="margin-top:14px"><input type="checkbox" id="untilbuild" checked />
        Keep retrying until it builds — build failures don't burn an iteration (recommended)</label>
      <div><label>Safety cap: max total attempts (until-build mode)</label>
        <input id="maxiters" type="number" value="15" min="1" style="min-width:120px" /></div>
      <p class="hint">With this on, <b>Iterations</b> counts only successful builds; the loop keeps
        fixing compile errors until it builds (or hits the cap). Each attempt is a paid model call,
        so the cap bounds your spend.</p>
      <p class="hint">Needs Docker running and the <code>gameboy-eval-gen</code> image built:
        <code>docker build -t gameboy-eval-gen -f env/Dockerfile .</code></p>
      <button class="act" id="go">Run generation</button>`;
    document.getElementById("go").onclick = (e) => runJob("generate", {
      model: document.getElementById("model").value,
      iters: document.getElementById("iters").value,
      minutes: document.getElementById("minutes").value,
      until_build: document.getElementById("untilbuild").checked,
      max_iters: document.getElementById("maxiters").value,
    }, e.target);
  },

  async grade() {
    main.innerHTML = `<h2>Grade</h2><div id="g">loading candidates…</div>`;
    const cands = await getJSON("/api/candidates");
    const opts = cands.filter((c) => c.artifact)
      .map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
    document.getElementById("g").innerHTML = `
      <p class="hint">Runs <code>grader/grade.py</code> against the SameBoy oracle and writes a
        report into <code>leaderboard/results/</code> (then rebuild the leaderboard).</p>
      <label>Target</label>
      <select id="target">
        <option value="oracle">oracle — self-play sanity (expect ~1.0)</option>
        ${opts}
      </select>
      ${opts ? "" : `<p class="hint">No graded-able candidates with an artifact yet — generate one first.</p>`}
      <br><button class="act" id="go">Grade</button>`;
    document.getElementById("go").onclick = (e) =>
      runJob("grade", { target: document.getElementById("target").value }, e.target);
  },

  async candidates() {
    main.innerHTML = `<h2>Candidates</h2><div id="c">loading…</div>`;
    drawCandidates();
  },

  async leaderboard() {
    main.innerHTML = `<h2>Leaderboard</h2><div id="lb">loading…</div>`;
    const d = await getJSON("/api/leaderboard");
    const table = d && d.entries.length ? `
      <table><thead><tr><th>#</th><th>candidate</th><th>overall</th><th>band</th>
        <th>replay / audio / proc</th></tr></thead><tbody>
        ${d.entries.map((e, i) => `<tr>
          <td>${i + 1}</td><td>${esc(e.name)}</td>
          <td>${e.overall.toFixed(4)}</td><td>${esc(e.band)}</td>
          <td>${e.sections.replay.toFixed(2)} / ${e.sections.audio.toFixed(2)} / ${e.sections.procedural.toFixed(2)}</td>
        </tr>`).join("")}
      </tbody></table>
      <p class="hint">generated ${esc(d.generated)}</p>` : `<p class="hint">No leaderboard.json yet — rebuild it.</p>`;
    document.getElementById("lb").innerHTML = `
      ${table}
      <button class="act" id="rebuild">Rebuild from leaderboard/results/</button>
      <a class="act" href="/leaderboard/index.html" target="_blank"
         style="text-decoration:none;display:inline-block;margin-left:10px">Open full leaderboard ↗</a>`;
    document.getElementById("rebuild").onclick = (e) => runJob("leaderboard", {}, e.target);
  },

  async provider() {
    main.innerHTML = `<h2>Provider</h2><div id="pv">loading…</div>`;
    const p = await getJSON("/api/provider");
    const opt = (v, label) => `<option value="${v}"${v === p.active ? " selected" : ""}>${label}</option>`;
    document.getElementById("pv").innerHTML = `
      <p class="hint">Choose a provider and save its settings — they're <b>persisted to disk</b>
        and reloaded on restart, remembered until you edit or clear them. Only the selected
        provider is used.${p.saved ? "" : " (nothing saved yet — showing what's in the environment.)"}</p>
      <label>Provider</label>
      <select id="prov">
        ${opt("ollama", "Ollama (local)")}${opt("openrouter", "OpenRouter")}${opt("openai", "OpenAI-compatible")}
      </select>
      <div id="fields"></div>
      <br><button class="act" id="save">Save</button>
      <button class="act" id="clear" style="margin-left:8px">Clear saved</button>`;
    const renderFields = () => {
      const prov = document.getElementById("prov").value;
      const saved = (set) => set ? "<b>(saved — leave blank to keep)</b>" : "";
      document.getElementById("fields").innerHTML =
        prov === "ollama" ? `
          <label>Ollama URL</label>
          <input id="olu" value="${esc(p.ollama_url)}" placeholder="http://127.0.0.1:11434" />`
        : prov === "openrouter" ? `
          <label>OpenRouter API key ${saved(p.openrouter_key_set)}</label>
          <input id="ork" type="password" placeholder="sk-or-..." autocomplete="off" />`
        : `
          <label>Base URL</label>
          <input id="obu" value="${esc(p.openai_base_url)}" placeholder="https://host/v1" />
          <label>API key ${saved(p.openai_key_set)}</label>
          <input id="ok" type="password" placeholder="sk-..." autocomplete="off" />`;
    };
    document.getElementById("prov").onchange = renderFields;
    renderFields();
    document.getElementById("save").onclick = async (e) => {
      e.target.disabled = true;
      const prov = document.getElementById("prov").value;
      const body = { provider: prov };
      if (prov === "ollama") body.ollama_url = document.getElementById("olu").value;
      else if (prov === "openrouter") body.openrouter_key = document.getElementById("ork").value;
      else { body.openai_base_url = document.getElementById("obu").value; body.openai_key = document.getElementById("ok").value; }
      await postJSON("/api/provider", body);
      views.provider();
    };
    document.getElementById("clear").onclick = async () => {
      if (confirm("Clear all saved provider settings?")) { await postJSON("/api/provider", { clear: true }); views.provider(); }
    };
  },

  async compare() {
    main.innerHTML = `<h2>Candidate vs the real oracle</h2><div id="cmp">loading…</div>`;
    const [cands, roms] = await Promise.all([getJSON("/api/candidates"), getJSON("/api/roms")]);
    const arts = cands.filter((c) => c.artifact);
    const opt = (v, label, sel) => `<option value="${esc(v)}"${v === sel ? " selected" : ""}>${esc(label)}</option>`;
    const sideOpts = (sel) => [opt("oracle", "SameBoy oracle (reference)", sel)]
      .concat(arts.map((c) => opt(c.name, c.name, sel))).join("");
    const romOpts = roms.map((r) => opt(r.key, r.label, "")).join("");
    document.getElementById("cmp").innerHTML = `
      <p class="hint"><b>The ground-truth view.</b> Renders against the <b>real SameBoy oracle</b>
        (native libretro) — the exact reference your composite score is computed against, not the
        in-browser stand-in the <b>Play</b> page uses. Runs the grader's own drivers server-side on
        the bundled test ROMs and streams the frames; a candidate that traps shows its partial
        output + why. <b>No controller input</b> — for interactive keyboard + audio, use Play.</p>
      <div class="row">
        <div><label>Left (model)</label><select id="left">${sideOpts(arts.length ? arts[0].name : "oracle")}</select></div>
        <div><label>Right (oracle)</label><select id="right">${sideOpts("oracle")}</select></div>
        <div><label>ROM</label><select id="rom">${romOpts}</select></div>
        <div><label>Frames</label><input id="frames" type="number" value="180" min="1" max="600" style="min-width:90px" /></div>
      </div>
      ${romOpts ? "" : `<p class="hint">No ROMs found — run “Fetch test ROMs” on the Dashboard.</p>`}
      ${arts.length ? "" : `<p class="hint">No candidate artifacts yet — generate one to put a model on the left.</p>`}
      <br><button class="act" id="play" ${romOpts ? "" : "disabled"}>▶ Run comparison</button>
      <div class="cmp">
        <figure><figcaption id="lcap">left</figcaption>
          <canvas class="gb" id="lcv" width="160" height="144"></canvas><div class="err" id="lerr"></div></figure>
        <figure><figcaption id="rcap">right</figcaption>
          <canvas class="gb" id="rcv" width="160" height="144"></canvas><div class="err" id="rerr"></div></figure>
      </div>`;
    document.getElementById("play").onclick = async (e) => {
      e.target.disabled = true;
      clearInterval(clipTimer);
      const rom = document.getElementById("rom").value;
      const frames = document.getElementById("frames").value;
      const L = document.getElementById("left").value, R = document.getElementById("right").value;
      document.getElementById("lcap").textContent = L;
      document.getElementById("rcap").textContent = R;
      const lctx = document.getElementById("lcv").getContext("2d");
      const rctx = document.getElementById("rcv").getContext("2d");
      const left = await loadClip(L, rom, frames, document.getElementById("lerr"));
      const right = await loadClip(R, rom, frames, document.getElementById("rerr"));
      e.target.disabled = false;
      if (!left.imgs.length && !right.imgs.length) return;
      const draw = (ctx, c, i) => { if (c.imgs.length) ctx.drawImage(c.imgs[Math.min(i, c.imgs.length - 1)], 0, 0); };
      let i = 0, n = Math.max(left.imgs.length, right.imgs.length);
      clipTimer = setInterval(() => { draw(lctx, left, i); draw(rctx, right, i); if (++i >= n) i = 0; }, 1000 / 30);
    };
  },

  async play() {
    cancelPlay();
    main.innerHTML = `<h2>Play</h2><div id="pl">loading…</div>`;
    const arts = (await getJSON("/api/candidates")).filter((c) => c.artifact);
    const modelOf = Object.fromEntries(arts.map((c) => [c.name, c.model || c.name]));
    document.getElementById("pl").innerHTML = `
      <p class="hint">The real playability test: run a candidate's emulator in your browser with
        live keyboard input. Pick a candidate, choose a Game Boy ROM from your computer
        (homebrew / legal only — none ship with the repo), and play. The ROM runs locally;
        nothing is uploaded.</p>
      ${arts.length ? "" : `<p class="hint">No candidate artifacts yet — generate one first.</p>`}
      <label>Candidate</label>
      <select id="cand">${arts.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}${
        c.best_score != null ? ` — ${Number(c.best_score).toFixed(3)}` : ""}</option>`).join("")}</select>
      <label>ROM file (.gb)</label>
      <input type="file" id="rom" accept=".gb,.gbc,.bin" />
      <label style="margin-top:10px"><input type="checkbox" id="useboot" checked />
        boot the open boot ROM first (recommended)</label>
      <label><input type="checkbox" id="vsref" checked />
        show the reference emulator alongside (same input) to compare</label>
      <label><input type="checkbox" id="sound" checked />
        sound — hear the candidate's audio output</label>
      <br><button class="act" id="go" ${arts.length ? "" : "disabled"}>▶ Load &amp; play</button>
      <p class="hint" id="plstatus"></p>
      <div class="cmp">
        <figure><figcaption id="candcap">${arts.length ? esc(modelOf[arts[0].name]) : "candidate"}</figcaption>
          <canvas class="gb" id="gbcv" width="160" height="144"></canvas></figure>
        <figure id="refpane" style="display:none"><figcaption>reference (≈ oracle)</figcaption>
          <canvas class="gb" id="gbcv2" width="160" height="144"></canvas></figure>
      </div>
      <p class="hint">Keys: arrows = D-pad · <b>Z</b> = A · <b>X</b> = B · <b>Enter</b> = Start ·
        <b>Shift</b> = Select. Click the left screen first so it has keyboard focus; both screens
        receive the same input.</p>`;
    const cand = document.getElementById("cand");
    if (cand) cand.onchange = () => {
      document.getElementById("candcap").textContent = modelOf[cand.value] || "candidate";
    };
    const go = document.getElementById("go");
    if (go) go.onclick = startPlay;
  },
};

// --- nav -------------------------------------------------------------------
const MENU = [["dashboard", "Dashboard"], ["generate", "Generate"], ["grade", "Grade"],
              ["candidates", "Candidates"], ["compare", "Oracle"], ["play", "Play"],
              ["leaderboard", "Leaderboard"], ["provider", "Provider"]];

const nav = document.getElementById("nav");
function show(key, btn) {
  clearInterval(pollTimer);
  clearInterval(clipTimer);
  clearTimeout(candTimer);
  cancelPlay();
  [...nav.children].forEach((b) => b.classList.toggle("active", b === btn));
  views[key]();
}
MENU.forEach(([key, label], i) => {
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = () => show(key, b);
  nav.appendChild(b);
  if (i === 0) show(key, b);
});
