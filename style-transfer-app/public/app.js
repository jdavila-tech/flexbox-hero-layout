// StyleShift front-end
const $ = (id) => document.getElementById(id);

const state = {
  styleImage: null,     // data URL (normalized JPEG)
  styleJson: null,      // parsed JSON from Claude (possibly edited)
  originalJson: null,   // untouched copy for "Reset"
  selfie: null,         // data URL (normalized JPEG)
  analyzing: false,
  converting: false,
  config: null,
};

const MAX_EDGE = 1600;
let accessCode = safeGet("accessCode") || "";

// ---------- utilities ----------
function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", ...(accessCode ? { "x-access-code": accessCode } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (data.needsAccessCode) openSettings("This server needs an access code.");
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2800);
}

function setStatus(el, msg, kind = "") {
  el.hidden = !msg;
  el.textContent = msg || "";
  el.className = `status ${kind}`;
}

/** Load any image (file/blob/dataURL), fix orientation, downscale, return JPEG data URL. */
async function normalizeImage(src) {
  const blob = typeof src === "string" ? await (await fetch(src)).blob() : src;
  if (blob.type && !blob.type.startsWith("image/")) throw new Error("That file isn't an image.");
  if (blob.size > 25 * 1024 * 1024) throw new Error("That image is too large (max 25 MB).");
  let bitmap;
  try {
    bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
  } catch {
    // Fallback for browsers/formats createImageBitmap can't handle
    bitmap = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Couldn't read that image. Try a JPG or PNG."));
      img.src = URL.createObjectURL(blob);
    });
  }
  const w = bitmap.width, h = bitmap.height;
  const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.92);
}

function showPreview(n, dataUrl) {
  const img = $(`preview${n}`);
  img.src = dataUrl;
  img.hidden = false;
  $(`drop${n}`).classList.add("has-image");
}

function updateUI() {
  const has1 = Boolean(state.styleJson);
  const has2 = Boolean(state.selfie);
  const steps = document.querySelectorAll(".stepper li");
  steps[0].className = has1 ? "done" : "active";
  steps[1].className = has2 ? "done" : has1 ? "active" : "";
  steps[2].className = $("result").hidden ? (has1 && has2 ? "active" : "") : "done";

  const ready = has1 && has2 && !state.analyzing && !state.converting;
  $("convertBtn").disabled = !ready;
  $("convertHint").textContent = state.converting
    ? "Working on it…"
    : ready
      ? "Ready! Tap Convert to apply the style to your photo."
      : !has1 && !has2 ? "Complete steps 1 and 2 to unlock."
      : !has1 ? (state.analyzing ? "Waiting for the style analysis…" : "Add an inspiration image in step 1.")
      : "Add your photo in step 2.";
}

// ---------- step 1: inspiration ----------
async function handleStyleImage(src) {
  if (state.analyzing) return;
  try {
    const dataUrl = await normalizeImage(src);
    state.styleImage = dataUrl;
    state.styleJson = null;
    showPreview(1, dataUrl);
    $("jsonPanel").hidden = true;
    await analyze();
  } catch (err) {
    setStatus($("status1"), err.message, "error");
  }
}

async function analyze() {
  state.analyzing = true;
  updateUI();
  $("scan1").hidden = false;
  setStatus($("status1"), "");
  try {
    const { styleJson } = await api("/api/analyze", { image: state.styleImage });
    state.styleJson = styleJson;
    state.originalJson = structuredClone(styleJson);
    renderJson();
    $("jsonPanel").hidden = false;
    setStatus($("status1"), "Style captured. You can tweak the JSON below if you like.", "ok");
    toast("Style extracted ✓");
  } catch (err) {
    setStatus($("status1"), err.message, "error");
    if (/key/i.test(err.message)) refreshConfig();
  } finally {
    state.analyzing = false;
    $("scan1").hidden = true;
    updateUI();
  }
}

function renderJson() {
  $("jsonEditor").value = JSON.stringify(state.styleJson, null, 2);
  $("styleTitle").textContent = state.styleJson?.title || "";
  $("jsonError").hidden = true;
}

$("jsonEditor").addEventListener("input", () => {
  try {
    const parsed = JSON.parse($("jsonEditor").value);
    if (!parsed || typeof parsed !== "object") throw new Error("Must be a JSON object");
    state.styleJson = parsed;
    $("styleTitle").textContent = parsed.title || "";
    $("jsonError").hidden = true;
  } catch (e) {
    state.styleJson = null;
    $("jsonError").hidden = false;
    $("jsonError").textContent = `Invalid JSON: ${e.message}`;
  }
  updateUI();
});
$("copyJson").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("jsonEditor").value); toast("JSON copied"); }
  catch { toast("Couldn't copy. Select the text manually."); }
});
$("resetJson").addEventListener("click", () => {
  if (!state.originalJson) return;
  state.styleJson = structuredClone(state.originalJson);
  renderJson();
  updateUI();
});

$("urlForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("urlInput").value.trim();
  if (!url) return;
  setStatus($("status1"), "Downloading image…");
  try {
    const { dataUrl } = await api("/api/fetch-image", { url });
    $("urlInput").value = "";
    await handleStyleImage(dataUrl);
  } catch (err) {
    setStatus($("status1"), err.message, "error");
  }
});

// ---------- step 2: selfie ----------
async function handleSelfie(src) {
  try {
    state.selfie = await normalizeImage(src);
    showPreview(2, state.selfie);
    updateUI();
    toast("Photo added ✓");
  } catch (err) {
    toast(err.message);
  }
}

$("uploadBtn2").addEventListener("click", () => $("file2").click());

// ---------- drop zones (click, drag & drop, keyboard) ----------
function wireDrop(n, handler) {
  const drop = $(`drop${n}`), input = $(`file${n}`);
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { if (input.files[0]) handler(input.files[0]); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith("image/"));
    if (file) handler(file);
  });
}
wireDrop(1, handleStyleImage);
wireDrop(2, handleSelfie);
$("file2cam").addEventListener("change", (e) => { if (e.target.files[0]) handleSelfie(e.target.files[0]); e.target.value = ""; });

// Paste an image anywhere: goes to step 1 first, then step 2.
document.addEventListener("paste", (e) => {
  if (e.target.closest("textarea, input")) return;
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  const file = item.getAsFile();
  if (!state.styleImage) handleStyleImage(file);
  else handleSelfie(file);
});

// ---------- camera ----------
let stream = null;
let facing = "user";

async function openCamera() {
  // No camera API (e.g. plain-HTTP on a phone): fall back to the native camera picker.
  if (!navigator.mediaDevices?.getUserMedia) {
    $("file2cam").click();
    return;
  }
  $("cameraModal").showModal();
  showCamLive();
  await startStream();
}

async function startStream() {
  stopStream();
  setStatus($("cameraError"), "");
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 1280 } },
      audio: false,
    });
    const v = $("video");
    v.srcObject = stream;
    v.classList.toggle("mirror", facing === "user");
    await v.play().catch(() => {});
  } catch (err) {
    const msg = err.name === "NotAllowedError"
      ? "Camera access was blocked. Allow camera permission in your browser, or use Upload instead."
      : "No camera available. Use Upload instead.";
    setStatus($("cameraError"), msg, "error");
  }
}

function stopStream() {
  stream?.getTracks().forEach((t) => t.stop());
  stream = null;
}

function showCamLive() {
  $("video").hidden = false;
  $("snapPreview").hidden = true;
  $("camLive").hidden = false;
  $("camReview").hidden = true;
  document.querySelector(".face-guide").hidden = false;
}

function capture() {
  const v = $("video");
  if (!v.videoWidth) return;
  const c = $("snapCanvas");
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  const ctx = c.getContext("2d");
  if (facing === "user") { ctx.translate(c.width, 0); ctx.scale(-1, 1); } // save as seen in the mirror
  ctx.drawImage(v, 0, 0);
  const snap = $("snapPreview");
  snap.src = c.toDataURL("image/jpeg", 0.92);
  snap.hidden = false;
  v.hidden = true;
  document.querySelector(".face-guide").hidden = true;
  $("camLive").hidden = true;
  $("camReview").hidden = false;
}

$("cameraBtn").addEventListener("click", openCamera);
$("shutterBtn").addEventListener("click", capture);
$("flipBtn").addEventListener("click", () => { facing = facing === "user" ? "environment" : "user"; startStream(); });
$("timerBtn").addEventListener("click", async () => {
  const cd = $("countdown");
  cd.hidden = false;
  for (const n of [3, 2, 1]) { cd.textContent = n; await new Promise((r) => setTimeout(r, 1000)); }
  cd.hidden = true;
  capture();
});
$("retakeBtn").addEventListener("click", showCamLive);
$("usePhotoBtn").addEventListener("click", async () => {
  const dataUrl = $("snapPreview").src;
  $("cameraModal").close();
  await handleSelfie(dataUrl);
});
$("cameraModal").addEventListener("close", stopStream);

// ---------- step 3: convert ----------
const PROGRESS_MSGS = [
  "Studying your features…",
  "Sketching the linework…",
  "Laying down the background…",
  "Splashing on the color…",
  "Adding final details…",
];

async function convert() {
  if ($("convertBtn").disabled) return;
  state.converting = true;
  updateUI();
  $("result").hidden = true;
  setStatus($("status3"), "");
  $("progress").hidden = false;
  let i = 0;
  $("progressText").textContent = PROGRESS_MSGS[0];
  const timer = setInterval(() => { i = Math.min(i + 1, PROGRESS_MSGS.length - 1); $("progressText").textContent = PROGRESS_MSGS[i]; }, 6000);

  try {
    const { image, provider } = await api("/api/convert", {
      selfie: state.selfie,
      styleImage: state.styleImage,
      styleJson: state.styleJson,
      matchOutfit: $("optOutfit").checked,
      useStyleReference: $("optRef").checked,
    });
    $("resultBefore").src = state.selfie;
    $("resultAfter").src = image;
    const ext = image.startsWith("data:image/jpeg") ? "jpg" : "png";
    $("downloadBtn").href = image;
    $("downloadBtn").download = `styleshift-${Date.now()}.${ext}`;
    $("providerNote").textContent = `Style read by Claude · Image generated by ${provider}`;
    $("result").hidden = false;
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus($("status3"), err.message, "error");
    if (/key/i.test(err.message)) refreshConfig();
  } finally {
    clearInterval(timer);
    $("progress").hidden = true;
    state.converting = false;
    updateUI();
  }
}

$("convertBtn").addEventListener("click", convert);
$("regenBtn").addEventListener("click", () => { $("convertBtn").disabled = false; convert(); });
$("restartBtn").addEventListener("click", () => {
  Object.assign(state, { styleImage: null, styleJson: null, originalJson: null, selfie: null });
  for (const n of [1, 2]) { $(`preview${n}`).hidden = true; $(`preview${n}`).removeAttribute("src"); $(`drop${n}`).classList.remove("has-image"); }
  $("jsonPanel").hidden = true;
  $("result").hidden = true;
  setStatus($("status1"), "");
  setStatus($("status3"), "");
  updateUI();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ---------- settings ----------
function renderConfig(c) {
  state.config = c;
  const missing = [];
  if (!c.anthropicKey) missing.push("an Anthropic key (to read styles)");
  if (!c.imageProvider) missing.push("a Gemini or OpenAI key (to generate images)");
  $("setupBanner").hidden = missing.length === 0;
  $("setupText").textContent = missing.length ? `Add ${missing.join(" and ")}.` : "";
  $("settingsDot").hidden = missing.length === 0;

  const mark = (el, ok) => { el.textContent = ok ? "● saved" : "● not set"; el.className = `key-state ${ok ? "set" : "unset"}`; };
  mark($("stateAnthropic"), c.anthropicKey);
  mark($("stateGemini"), c.geminiKey);
  mark($("stateOpenai"), c.openaiKey);
  if (c.imageProvider) $("providerSelect").value = c.imageProvider;
  $("accessField").hidden = !c.accessCodeRequired;
  syncProviderFields();
}

function syncProviderFields() {
  const p = $("providerSelect").value;
  $("geminiField").hidden = p !== "gemini";
  $("openaiField").hidden = p !== "openai";
}
$("providerSelect").addEventListener("change", syncProviderFields);

async function refreshConfig() {
  try { renderConfig(await api("/api/config")); } catch { /* access code prompt handled in api() */ }
}

function openSettings(msg) {
  setStatus($("settingsStatus"), msg || "", msg ? "error" : "");
  if (msg) $("accessField").hidden = false;
  if (!$("settingsModal").open) $("settingsModal").showModal();
}

$("settingsBtn").addEventListener("click", () => openSettings());
$("setupBtn").addEventListener("click", () => openSettings());

$("settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("accessCode").value.trim();
  if (code) { accessCode = code; safeSet("accessCode", code); }
  const body = {
    anthropicKey: $("keyAnthropic").value.trim(),
    geminiKey: $("keyGemini").value.trim(),
    openaiKey: $("keyOpenai").value.trim(),
    imageProvider: $("providerSelect").value,
  };
  $("saveSettings").disabled = true;
  try {
    const c = await api("/api/config", body);
    renderConfig(c);
    ["keyAnthropic", "keyGemini", "keyOpenai", "accessCode"].forEach((id) => ($(id).value = ""));
    $("settingsModal").close();
    toast(c.ready ? "Settings saved, ready to go ✓" : "Settings saved");
  } catch (err) {
    setStatus($("settingsStatus"), err.message, "error");
  } finally {
    $("saveSettings").disabled = false;
  }
});

document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));

// ---------- init ----------
refreshConfig();
updateUI();
