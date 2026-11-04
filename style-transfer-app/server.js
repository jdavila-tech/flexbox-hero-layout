import express from "express";
import dotenv from "dotenv";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import https from "node:https";
import { startServer } from "./lib/listen.js";
import { extractStyleJson } from "./lib/analyze.js";
import { generateStyledImage, PROVIDERS } from "./lib/generate.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(__dirname, ".env");
dotenv.config({ path: ENV_PATH, quiet: true });

const PORT = Number(process.env.PORT) || 4000;
const HOST = process.env.HOST || "0.0.0.0";
const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "25mb" }));
app.use(express.static(path.join(__dirname, "public")));

// ---------- helpers ----------

/** Parse a data URL into { mediaType, base64 }, validating type and size. */
function parseDataUrl(dataUrl, label = "image") {
  if (typeof dataUrl !== "string") throw httpError(400, `Missing ${label}.`);
  const m = /^data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)$/.exec(dataUrl);
  if (!m) throw httpError(400, `The ${label} is not a valid image.`);
  const mediaType = m[1].toLowerCase();
  if (!ALLOWED_TYPES.includes(mediaType)) {
    throw httpError(415, `Unsupported ${label} type (${mediaType}). Use JPG, PNG, WEBP or GIF.`);
  }
  const base64 = m[2].replace(/\s/g, "");
  if (Buffer.byteLength(base64, "base64") > MAX_IMAGE_BYTES) {
    throw httpError(413, `The ${label} is larger than 15 MB.`);
  }
  return { mediaType, base64 };
}

function httpError(status, message) {
  const err = new Error(message);
  err.status = status;
  return err;
}

const asyncRoute = (fn) => (req, res) =>
  fn(req, res).catch((err) => {
    const status = err.status || 500;
    if (status >= 500) console.error("[error]", err);
    res.status(status).json({ error: err.expose === false ? "Something went wrong." : err.message });
  });

function configStatus() {
  const provider = resolveProvider();
  return {
    anthropicKey: Boolean(process.env.ANTHROPIC_API_KEY),
    geminiKey: Boolean(process.env.GEMINI_API_KEY),
    openaiKey: Boolean(process.env.OPENAI_API_KEY),
    imageProvider: provider,
    imageProviderLabel: provider ? PROVIDERS[provider].label : null,
    accessCodeRequired: Boolean(process.env.ACCESS_CODE),
    ready: Boolean(process.env.ANTHROPIC_API_KEY) && Boolean(provider),
  };
}

function resolveProvider() {
  const wanted = (process.env.IMAGE_PROVIDER || "").toLowerCase();
  if (wanted && PROVIDERS[wanted] && process.env[PROVIDERS[wanted].envKey]) return wanted;
  if (process.env.GEMINI_API_KEY) return "gemini";
  if (process.env.OPENAI_API_KEY) return "openai";
  return null;
}

/** Persist settings to .env so they survive restarts. */
function saveEnv(updates) {
  let lines = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, "utf8").split("\n") : [];
  for (const [key, value] of Object.entries(updates)) {
    const idx = lines.findIndex((l) => l.startsWith(`${key}=`));
    const line = `${key}=${value}`;
    if (idx >= 0) lines[idx] = line;
    else lines.push(line);
    process.env[key] = value;
  }
  fs.writeFileSync(ENV_PATH, lines.filter((l, i) => l || i < lines.length - 1).join("\n") + "\n", { mode: 0o600 });
}

// Optional access code so strangers can't spend your API credits.
app.use("/api", (req, res, next) => {
  const code = process.env.ACCESS_CODE;
  if (!code || req.path === "/health") return next();
  if (req.get("x-access-code") === code) return next();
  res.status(401).json({ error: "Access code required.", needsAccessCode: true });
});

// ---------- routes ----------

app.get("/api/health", (_req, res) => res.json({ ok: true }));

app.get("/api/config", (_req, res) => res.json(configStatus()));

app.post(
  "/api/config",
  asyncRoute(async (req, res) => {
    const { anthropicKey, geminiKey, openaiKey, imageProvider } = req.body || {};
    const updates = {};
    const clean = (v) => String(v).trim().replace(/[\r\n]/g, "");
    if (anthropicKey) updates.ANTHROPIC_API_KEY = clean(anthropicKey);
    if (geminiKey) updates.GEMINI_API_KEY = clean(geminiKey);
    if (openaiKey) updates.OPENAI_API_KEY = clean(openaiKey);
    if (imageProvider && PROVIDERS[imageProvider]) updates.IMAGE_PROVIDER = imageProvider;
    if (Object.keys(updates).length) saveEnv(updates);
    res.json(configStatus());
  }),
);

// Fetch an image from a URL the user pasted, return it as a data URL.
app.post(
  "/api/fetch-image",
  asyncRoute(async (req, res) => {
    let url;
    try {
      url = new URL(String(req.body?.url || ""));
    } catch {
      throw httpError(400, "That doesn't look like a valid link.");
    }
    if (!["http:", "https:"].includes(url.protocol)) throw httpError(400, "Only http(s) links are supported.");

    const resp = await fetch(url, {
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
      headers: { "User-Agent": "StyleShift/1.0", Accept: "image/*" },
    }).catch(() => {
      throw httpError(502, "Couldn't download that image.");
    });
    if (!resp.ok) throw httpError(502, `Couldn't download that image (HTTP ${resp.status}).`);
    const type = (resp.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
    if (!ALLOWED_TYPES.includes(type)) {
      throw httpError(415, "That link isn't a direct JPG, PNG, WEBP or GIF image. Try 'Copy image address'.");
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    if (buf.length > MAX_IMAGE_BYTES) throw httpError(413, "That image is larger than 15 MB.");
    res.json({ dataUrl: `data:${type};base64,${buf.toString("base64")}` });
  }),
);

// Step 1: inspiration image -> style JSON (Claude vision + structured outputs).
app.post(
  "/api/analyze",
  asyncRoute(async (req, res) => {
    if (!process.env.ANTHROPIC_API_KEY) throw httpError(400, "Add your Anthropic API key in Settings first.");
    const image = parseDataUrl(req.body?.image, "inspiration image");
    const styleJson = await extractStyleJson(image);
    res.json({ styleJson });
  }),
);

// Step 3: user photo + style JSON -> styled image.
app.post(
  "/api/convert",
  asyncRoute(async (req, res) => {
    const provider = resolveProvider();
    if (!provider) throw httpError(400, "Add a Gemini or OpenAI API key in Settings first.");
    const { styleJson, matchOutfit = true, useStyleReference = true } = req.body || {};
    if (!styleJson || typeof styleJson !== "object") throw httpError(400, "Missing style JSON. Upload an inspiration image first.");
    const selfie = parseDataUrl(req.body?.selfie, "your photo");
    const styleImage = useStyleReference && req.body?.styleImage ? parseDataUrl(req.body.styleImage, "inspiration image") : null;

    const result = await generateStyledImage(provider, { selfie, styleImage, styleJson, matchOutfit });
    res.json({ image: `data:${result.mediaType};base64,${result.base64}`, provider: PROVIDERS[provider].label });
  }),
);

startServer(app, { port: PORT, host: HOST, baseDir: __dirname, https }).then(({ urls }) => {
  const s = configStatus();
  console.log(`\n  StyleShift is running:`);
  for (const u of urls) console.log(`    ${u}`);
  console.log(`  Claude key: ${s.anthropicKey ? "set" : "MISSING"} | Image provider: ${s.imageProviderLabel || "MISSING"}\n`);
});
