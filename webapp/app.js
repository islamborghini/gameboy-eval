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
      <p class="hint">Needs Docker running and the <code>gameboy-eval-gen</code> image built:
        <code>docker build -t gameboy-eval-gen -f env/Dockerfile .</code></p>
      <button class="act" id="go">Run generation</button>`;
    document.getElementById("go").onclick = (e) => runJob("generate", {
      model: document.getElementById("model").value,
      iters: document.getElementById("iters").value,
      minutes: document.getElementById("minutes").value,
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
    const rows = await getJSON("/api/candidates");
    document.getElementById("c").innerHTML = rows.length ? `
      <table><thead><tr><th>candidate</th><th>model</th><th>best score</th>
        <th>artifact</th></tr></thead><tbody>
        ${rows.map((c) => `<tr>
          <td>${esc(c.name)}</td><td>${esc(c.model ?? "—")}</td>
          <td>${c.best_score == null ? "—" : Number(c.best_score).toFixed(4)}</td>
          <td>${c.artifact ? "yes" : "—"}</td></tr>`).join("")}
      </tbody></table>` : `<p class="hint">No candidates yet. Run a generation.</p>`;
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
    const p = await getJSON("/api/status").then((s) => s.provider);
    document.getElementById("pv").innerHTML = `
      <p class="hint">Held in memory for spawned jobs only — never written to disk. Precedence:
        OpenRouter → OpenAI-compatible → Ollama. Leave a field blank to clear it.</p>
      <div class="kv"><b>active</b> <span class="badge">${esc(p.active)}</span></div>
      <label>OpenRouter API key ${p.openrouter_key_set ? "(set)" : ""}</label>
      <input id="ork" type="password" placeholder="sk-or-..." />
      <label>OpenAI-compatible base URL</label>
      <input id="obu" value="${esc(p.openai_base_url)}" placeholder="https://host/v1" />
      <label>OpenAI-compatible API key ${p.openai_key_set ? "(set)" : ""}</label>
      <input id="ok" type="password" placeholder="sk-..." />
      <label>Ollama URL</label>
      <input id="olu" value="${esc(p.ollama_url)}" />
      <br><button class="act" id="save">Save</button>`;
    document.getElementById("save").onclick = async (e) => {
      e.target.disabled = true;
      await postJSON("/api/provider", {
        openrouter_key: document.getElementById("ork").value,
        openai_base_url: document.getElementById("obu").value,
        openai_key: document.getElementById("ok").value,
        ollama_url: document.getElementById("olu").value,
      });
      views.provider();
    };
  },
};

// --- nav -------------------------------------------------------------------
const MENU = [["dashboard", "Dashboard"], ["generate", "Generate"], ["grade", "Grade"],
              ["candidates", "Candidates"], ["leaderboard", "Leaderboard"],
              ["provider", "Provider"]];

const nav = document.getElementById("nav");
function show(key, btn) {
  clearInterval(pollTimer);
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
