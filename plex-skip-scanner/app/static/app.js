"use strict";

const $ = (s, el = document) => el.querySelector(s);
const state = { view: "movies", movies: [], tv: [], selected: new Set(), openTitle: null, jobsTimer: null };

const CATEGORY_LABELS = {
  explicit_nudity: "Explicit nudity",
  partial_nudity: "Partial nudity",
  sexual_activity_no_nudity: "Sexual scene, no nudity",
  swimwear_or_underwear: "Swimwear / underwear",
  shirtless_male: "Shirtless man",
  artwork_or_statue: "Artwork / statue",
  medical_or_breastfeeding: "Medical / breastfeeding",
  infant_or_child_nonsexual: "Baby / child (non-sexual)",
  skin_tone_clothing_or_false_positive: "False alarm",
  unclear: "Unclear",
  manual: "Added by you",
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTime(sec) {
  sec = Math.max(0, sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function parseTime(str) {
  const parts = String(str).trim().split(":").map(Number);
  if (!parts.length || parts.some((n) => Number.isNaN(n))) return NaN;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

/* ---------- status chips ---------- */
function chipsFor(f) {
  if (f.job === "running") return `<span class="chip busy">Scanning…</span>`;
  if (f.job === "queued") return `<span class="chip busy">Queued</span>`;
  if (!f.scanned) return `<span class="chip">Not scanned</span>`;
  const out = [];
  out.push(f.skips ? `<span class="chip skip">${f.skips} skip${f.skips > 1 ? "s" : ""}</span>` : `<span class="chip keep">No skips</span>`);
  if (f.review) out.push(`<span class="chip review">${f.review} to review</span>`);
  if (f.has_family_edit) out.push(`<span class="chip">Family Edit</span>`);
  return out.join("");
}

function matchesFilter(f) {
  switch ($("#filter").value) {
    case "new": return !f.scanned;
    case "review": return f.scanned && f.review > 0;
    case "skips": return f.scanned && f.skips > 0;
    case "clean": return f.scanned && !f.skips;
    default: return true;
  }
}

function fileRow(f, label) {
  const checked = state.selected.has(f.path) ? "checked" : "";
  return `<div class="row">
    <input type="checkbox" data-path="${esc(f.path)}" ${checked} aria-label="Select ${esc(label)}">
    <div class="info"><button class="open" data-open="${esc(f.path)}">
      <div class="name">${esc(label)}</div>
      <div class="chips">${chipsFor(f)}</div>
    </button></div>
  </div>`;
}

/* ---------- library rendering ---------- */
function renderMovies() {
  const q = $("#search").value.trim().toLowerCase();
  const items = state.movies
    .map((m) => ({ ...m, files: m.files.filter(matchesFilter) }))
    .filter((m) => m.files.length && (!q || m.title.toLowerCase().includes(q)));
  if (!items.length) return emptyMsg(state.movies.length ? "No titles match." : "No movies found in the Movies folder.");
  return items.map((m) => {
    const rows = m.files.map((f) => fileRow(f, m.files.length > 1 ? `${m.title} — ${f.name}` : m.title)).join("");
    return `<div class="card">${rows}</div>`;
  }).join("");
}

function renderTv() {
  const q = $("#search").value.trim().toLowerCase();
  const shows = state.tv
    .filter((s) => !q || s.title.toLowerCase().includes(q))
    .map((s) => ({ ...s, seasons: s.seasons.map((se) => ({ ...se, episodes: se.episodes.filter(matchesFilter) })).filter((se) => se.episodes.length) }))
    .filter((s) => s.seasons.length);
  if (!shows.length) return emptyMsg(state.tv.length ? "No shows match." : "No shows found in the TV folder.");
  return shows.map((s) => {
    const all = s.seasons.flatMap((se) => se.episodes.map((e) => e.path));
    const scanned = s.seasons.flatMap((se) => se.episodes).filter((e) => e.scanned).length;
    const seasons = s.seasons.map((se) => {
      const paths = se.episodes.map((e) => e.path);
      return `<details class="season">
        <summary><input type="checkbox" data-group='${esc(JSON.stringify(paths))}' ${allSelected(paths)} aria-label="Select all in ${esc(se.title)}"><span>${esc(se.title)}</span><span class="muted">${se.episodes.length} episode${se.episodes.length === 1 ? "" : "s"}</span></summary>
        ${se.episodes.map((e) => fileRow(e, e.name)).join("")}
      </details>`;
    }).join("");
    return `<details class="card show"${q ? " open" : ""}>
      <summary><input type="checkbox" data-group='${esc(JSON.stringify(all))}' ${allSelected(all)} aria-label="Select all of ${esc(s.title)}"><span class="name">${esc(s.title)}</span><span class="muted">${scanned}/${all.length} scanned</span></summary>
      ${seasons}
    </details>`;
  }).join("");
}

function allSelected(paths) {
  return paths.length && paths.every((p) => state.selected.has(p)) ? "checked" : "";
}

function emptyMsg(t) { return `<div class="empty">${esc(t)}</div>`; }

function renderLibrary() {
  const openShows = [...document.querySelectorAll("details[open] > summary .name, details.season[open] > summary span:first-of-type")].map((n) => n.textContent);
  $("#library").innerHTML = state.view === "movies" ? renderMovies() : renderTv();
  document.querySelectorAll("#library details").forEach((d) => {
    const label = d.querySelector(":scope > summary .name, :scope > summary span:first-of-type");
    if (label && openShows.includes(label.textContent)) d.open = true;
  });
  updateActionBar();
}

function updateActionBar() {
  const n = state.selected.size;
  $("#actionbar").hidden = n === 0 || state.view === "queue";
  $("#sel-count").textContent = `${n} selected`;
}

async function loadLibrary() {
  try {
    if (state.view === "movies") state.movies = await api("/api/library/movies");
    else if (state.view === "tv") state.tv = await api("/api/library/tv");
    renderLibrary();
  } catch (e) {
    $("#library").innerHTML = emptyMsg("Could not load the library: " + e.message);
  }
}

/* ---------- queue ---------- */
async function loadJobs() {
  const jobs = await api("/api/jobs");
  const active = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  const c = $("#queue-count");
  c.hidden = !active;
  c.textContent = active;
  if (state.view === "queue") {
    $("#jobs").innerHTML = jobs.length ? jobs.map((j) => {
      const label = j.kind === "export" ? "Family Edit" : "Scan";
      const status = { queued: "Waiting", running: j.stage || "Working", done: "Done", error: "Failed", cancelled: "Cancelled" }[j.status];
      const canCancel = j.status === "queued" || j.status === "running";
      return `<div class="card job">
        <div><div class="name">${esc(j.name)}</div><div class="stage">${label} · ${esc(status)}${j.status === "running" ? ` · ${Math.round(j.progress * 100)}%` : ""}</div></div>
        ${canCancel ? `<button class="btn small" data-cancel="${j.id}">Cancel</button>` : j.status === "done" && j.kind === "scan" ? `<button class="btn small" data-open="${esc(j.path)}">Review</button>` : "<span></span>"}
        ${j.status === "running" ? `<div class="bar"><div style="width:${Math.round(j.progress * 100)}%"></div></div>` : ""}
        ${j.error ? `<div class="error">${esc(j.error)}</div>` : ""}
      </div>`;
    }).join("") : emptyMsg("Nothing in the queue. Select titles on the Movies or TV tab and press Scan.");
  }
  return active;
}

function scheduleJobs() {
  clearTimeout(state.jobsTimer);
  state.jobsTimer = setTimeout(async () => {
    let active = 0;
    try { active = await loadJobs(); } catch { /* ignore */ }
    if (active && state.view !== "queue") loadLibrary();
    scheduleJobs();
  }, state.view === "queue" ? 2000 : 6000);
}

/* ---------- detail dialog ---------- */
async function openTitle(path) {
  state.openTitle = path;
  const data = await api("/api/title?path=" + encodeURIComponent(path));
  renderDetail(data);
  const dlg = $("#detail");
  if (!dlg.open) dlg.showModal();
}

function renderDetail(data) {
  const rec = data.record;
  $("#d-title").textContent = data.name;
  const sub = rec
    ? `Scanned ${esc((rec.scanned_at || "").replace("T", " "))} · ${rec.frames_checked ?? "?"} frames checked${rec.review_model ? ` · reviewed by ${esc(rec.review_model)}` : " · not reviewed by Claude"}${rec.subtitles ? " · subtitles used" : ""}`
    : "Not scanned yet.";
  $("#d-sub").innerHTML = sub;

  const skipsN = rec ? rec.segments.filter((s) => s.final === "skip").length : 0;
  $("#d-actions").innerHTML = `
    <button class="btn" data-act="scan">${rec ? "Scan again" : "Scan now"}</button>
    ${rec && skipsN ? `<button class="btn" data-act="export">${data.file.has_family_edit ? "Rebuild" : "Create"} Plex Family Edit</button>` : ""}`;

  if (!rec) { $("#d-body").innerHTML = emptyMsg("Press Scan now to look for scenes to skip."); return; }
  if (rec.edl_status === "edl.new") {
    $("#d-body").innerHTML = `<div class="notice">You edited the .edl file by hand, so it was left alone. The updated skips were saved as <b>.edl.new</b> next to the video.</div>`;
  } else { $("#d-body").innerHTML = ""; }

  const segs = rec.segments;
  const review = segs.filter((s) => s.needs_review && !s.user_decision).length;
  const summary = `<div class="summary">
    <span class="chip skip">${skipsN} skipped</span>
    <span class="chip keep">${segs.filter((s) => s.final === "keep").length} kept</span>
    ${review ? `<span class="chip review">${review} need your review</span>` : ""}
  </div>`;
  if (!segs.length) { $("#d-body").innerHTML += summary + emptyMsg("Nothing was flagged in this title."); return; }

  const order = (s) => (s.needs_review && !s.user_decision ? 0 : 1);
  const html = [...segs].sort((a, b) => order(a) - order(b) || a.start - b.start).map((s) => {
    const r = s.review || {};
    const conf = r.confidence != null && s.source !== "manual" ? ` · ${Math.round(r.confidence * 100)}% sure` : "";
    const who = s.user_decision ? "your choice" : s.needs_review ? `waiting for review (default: ${s.final})` : "automatic";
    const thumb = s.source === "manual" ? "" :
      `<button class="thumb" data-reveal aria-label="Show picture"><img loading="lazy" alt="" src="/api/thumb?path=${encodeURIComponent(data.path)}&seg=${s.id}"><span>Tap to show</span></button>`;
    return `<div class="card seg${s.source === "manual" ? " manual-seg" : ""}" data-seg="${s.id}" data-final="${s.final}">
      ${thumb}
      <div>
        <div class="when">${fmtTime(s.start)} – ${fmtTime(s.end)} <span class="muted">(${Math.round(s.end - s.start)}s)</span></div>
        <div class="chips"><span class="chip ${s.final}">${s.final === "skip" ? "Skip" : "Keep"}</span><span class="chip ${s.needs_review && !s.user_decision ? "review" : ""}">${esc(CATEGORY_LABELS[r.category] || r.category)}</span></div>
        <div class="why">${esc(r.reason_short || "")}${conf} · ${who}</div>
        <div class="buttons">
          <button class="btn small ${s.user_decision === "skip" ? "on-skip" : ""}" data-decide="skip">Skip</button>
          <button class="btn small ${s.user_decision === "keep" ? "on-keep" : ""}" data-decide="keep">Keep</button>
          ${s.user_decision && s.source !== "manual" ? `<button class="btn small ghost" data-decide="auto">Undo my choice</button>` : ""}
          <button class="btn small ghost" data-adjust>Adjust times</button>
          ${s.source === "manual" ? `<button class="btn small ghost" data-delete>Delete</button>` : ""}
        </div>
        <form class="adjust" hidden>
          <input name="start" value="${fmtTime(s.start)}" aria-label="Start">
          <span>to</span>
          <input name="end" value="${fmtTime(s.end)}" aria-label="End">
          <button class="btn small primary">Save</button>
        </form>
      </div>
    </div>`;
  }).join("");
  $("#d-body").innerHTML += summary + html;
}

async function decide(segId, decision, start, end) {
  const body = { path: state.openTitle, seg_id: segId, decision: decision === "auto" ? null : decision };
  if (start != null) Object.assign(body, { start, end });
  await api("/api/decision", { method: "POST", body });
  await openTitle(state.openTitle);
  loadLibrary();
}

/* ---------- events ---------- */
document.addEventListener("click", async (e) => {
  const t = e.target;
  const tab = t.closest(".tab");
  if (tab) {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === tab));
    state.view = tab.dataset.view;
    $("#view-library").hidden = state.view === "queue";
    $("#view-queue").hidden = state.view !== "queue";
    $("#search").value = "";
    if (state.view === "queue") loadJobs(); else loadLibrary();
    updateActionBar();
    scheduleJobs();
    return;
  }
  const open = t.closest("[data-open]");
  if (open) { openTitle(open.dataset.open).catch((err) => toast(err.message)); return; }
  const cancel = t.closest("[data-cancel]");
  if (cancel) { await api(`/api/jobs/${cancel.dataset.cancel}/cancel`, { method: "POST" }); loadJobs(); return; }
  if (t.closest("[data-close]")) { $("#detail").close(); return; }
  const reveal = t.closest("[data-reveal]");
  if (reveal) { reveal.classList.toggle("revealed"); return; }

  const seg = t.closest("[data-seg]");
  if (seg) {
    const id = seg.dataset.seg;
    const d = t.closest("[data-decide]");
    if (d) { decide(id, d.dataset.decide).catch((err) => toast(err.message)); return; }
    if (t.closest("[data-adjust]")) { $(".adjust", seg).hidden = !$(".adjust", seg).hidden; return; }
    if (t.closest("[data-delete]")) {
      await api("/api/manual/delete", { method: "POST", body: { path: state.openTitle, seg_id: id } });
      openTitle(state.openTitle); loadLibrary();
      return;
    }
  }
  const act = t.closest("[data-act]");
  if (act) {
    const kind = act.dataset.act === "export" ? "export" : "scan";
    const r = await api("/api/jobs", { method: "POST", body: { paths: [state.openTitle], kind } });
    toast(r.added ? (kind === "export" ? "Family Edit added to the queue" : "Added to the queue") : "Already in the queue");
    loadJobs(); loadLibrary();
  }
});

document.addEventListener("change", (e) => {
  const t = e.target;
  if (t.matches("input[type=checkbox][data-path]")) {
    t.checked ? state.selected.add(t.dataset.path) : state.selected.delete(t.dataset.path);
    renderLibrary();
  } else if (t.matches("input[type=checkbox][data-group]")) {
    const paths = JSON.parse(t.dataset.group);
    paths.forEach((p) => (t.checked ? state.selected.add(p) : state.selected.delete(p)));
    renderLibrary();
  }
});

// Clicking a checkbox inside <summary> should not open/close the folder.
document.addEventListener("click", (e) => {
  if (e.target.matches("summary input[type=checkbox]")) e.stopPropagation();
}, true);

document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    if (f.id === "manual-form") {
      const start = parseTime(f.start.value), end = parseTime(f.end.value);
      if (!(end > start)) throw new Error("Use times like 1:02:03, with the end after the start");
      await api("/api/manual", { method: "POST", body: { path: state.openTitle, start, end, note: f.note.value } });
      f.reset();
      toast("Skip added");
      await openTitle(state.openTitle);
      loadLibrary();
    } else if (f.classList.contains("adjust")) {
      const start = parseTime(f.start.value), end = parseTime(f.end.value);
      if (!(end > start)) throw new Error("Use times like 1:02:03, with the end after the start");
      const segEl = f.closest("[data-seg]");
      await decide(segEl.dataset.seg, segEl.dataset.final, start, end);
    }
  } catch (err) { toast(err.message); }
});

$("#search").addEventListener("input", renderLibrary);
$("#filter").addEventListener("change", renderLibrary);
$("#refresh").addEventListener("click", loadLibrary);
$("#sel-clear").addEventListener("click", () => { state.selected.clear(); renderLibrary(); });
$("#clear-jobs").addEventListener("click", async () => { await api("/api/jobs/clear", { method: "POST" }); loadJobs(); });
$("#sel-scan").addEventListener("click", async () => {
  try {
    const r = await api("/api/jobs", { method: "POST", body: { paths: [...state.selected], kind: "scan" } });
    toast(`${r.added} added to the queue${r.already_queued ? `, ${r.already_queued} already there` : ""}`);
    state.selected.clear();
    loadJobs(); loadLibrary();
  } catch (err) { toast(err.message); }
});

async function init() {
  try {
    const s = await api("/api/status");
    const pill = $("#review-pill");
    pill.textContent = s.review ? "Claude review on" : "Claude review off";
    pill.className = "pill " + (s.review ? "on" : "off");
    pill.title = s.review ? `Using ${s.model}` : `${s.review_off_reason}. Until this is fixed, every flagged scene waits for your review.`;
    const warn = [];
    if (!s.movies_ok) warn.push(`Movies folder not found (${s.movies_dir}).`);
    if (!s.tv_ok) warn.push(`TV folder not found (${s.tv_dir}).`);
    $("#library-warning").hidden = !warn.length;
    $("#library-warning").textContent = warn.join(" ");
  } catch (e) { toast(e.message); }
  loadLibrary();
  loadJobs().catch(() => {});
  scheduleJobs();
}

init();
