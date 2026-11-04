/**
 * Image generation providers. Claude can analyze images but not create them,
 * so the "Convert" step uses an image-editing model that accepts reference photos.
 * Each provider: (opts) => Promise<{ mediaType, base64 }>
 */

export const PROVIDERS = {
  gemini: { label: "Google Gemini", envKey: "GEMINI_API_KEY", run: runGemini },
  openai: { label: "OpenAI gpt-image", envKey: "OPENAI_API_KEY", run: runOpenAI },
};

export async function generateStyledImage(provider, opts) {
  const prompt = buildPrompt(opts.styleJson, { matchOutfit: opts.matchOutfit, hasStyleImage: Boolean(opts.styleImage) });
  return PROVIDERS[provider].run({ ...opts, prompt });
}

const val = (v) => (Array.isArray(v) ? v.filter(Boolean).join(", ") : v && v !== "none" ? String(v) : "");
const line = (label, ...parts) => {
  const text = parts.map(val).filter(Boolean).join("; ");
  return text ? `- ${label}: ${text}` : "";
};

/**
 * Turn the style JSON into an instruction that keeps the user's identity
 * and applies everything else. The JSON's face/hair description belongs to the
 * person in the inspiration image, so it is deliberately left out.
 */
export function buildPrompt(s, { matchOutfit, hasStyleImage }) {
  const sub = s.subject || {};
  const lines = [
    `Redraw the person in the FIRST image as a new artwork. This is the most important rule: preserve their exact likeness and identity — face shape, facial features, eyes, nose, mouth, skin tone, age, hairline and hair (or baldness), and facial hair exactly as they appear in their photo. Do not replace them with someone else and do not copy the face of anyone in a style reference.`,
    hasStyleImage
      ? `The SECOND image is only a style reference. Copy its art style, medium, background, colors, lighting and composition — never its person's face or identity.`
      : "",
    ``,
    `Target style (${val(s.title) || "custom style"}):`,
    val(s.main_prompt) ? `Overall: ${s.main_prompt} (Apply this to the person from the first image, not the person described.)` : "",
    line("Art style", s.art_style?.medium, s.art_style?.techniques, s.art_style?.influences, s.art_style?.detail_level),
    line("Background", s.background?.base, s.background?.elements, s.background?.composition),
    line("Color accents", s.color_accents?.palette, s.color_accents?.style, s.color_accents?.placement, s.color_accents?.contrast),
    line("Lighting", s.lighting?.type, s.lighting?.shading),
    line("Mood", s.mood),
    line("Composition", s.composition?.framing, s.composition?.focus, s.composition?.aspect_ratio && `aspect ratio ${s.composition.aspect_ratio}`),
    matchOutfit ? line("Pose", sub.pose) : "",
    matchOutfit ? line("Headwear", sub.headwear?.item, sub.headwear?.details) : "",
    matchOutfit ? line("Clothing", sub.clothing?.item, sub.clothing?.details) : "- Keep the person's own clothing from their photo, rendered in the target style.",
    line("Stylized details on the skin (keep the underlying face unchanged)", sub.face?.skin_details),
    line("Quality", s.quality),
    line("Avoid", s.negative_prompt, "changing the person's identity or face"),
  ];
  return lines.filter((l) => l !== "").join("\n");
}

function providerError(name, status, detail) {
  let message = `${name} image generation failed${status ? ` (HTTP ${status})` : ""}.`;
  if (status === 401 || status === 403 || /api key not valid|invalid api key|incorrect api key/i.test(detail || "")) message = `Your ${name} API key was rejected. Check it in Settings.`;
  else if (status === 429) message = `${name} is rate-limited or out of quota. Wait a moment or check your billing.`;
  else if (detail) message += ` ${detail}`;
  const e = new Error(message);
  e.status = /rejected/.test(message) ? 401 : status && status < 500 ? status : 502;
  return e;
}

// ---------- Google Gemini ----------
async function runGemini({ prompt, selfie, styleImage }) {
  const model = process.env.GEMINI_IMAGE_MODEL || "gemini-2.5-flash-image";
  const parts = [{ inline_data: { mime_type: selfie.mediaType, data: selfie.base64 } }];
  if (styleImage) parts.push({ inline_data: { mime_type: styleImage.mediaType, data: styleImage.base64 } });
  parts.push({ text: prompt });

  const resp = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": process.env.GEMINI_API_KEY },
    body: JSON.stringify({
      contents: [{ role: "user", parts }],
      generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
    }),
    signal: AbortSignal.timeout(180000),
  }).catch((err) => {
    console.error("[gemini]", err);
    throw providerError("Gemini", 0, "Couldn't reach the Gemini API.");
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    console.error("[gemini]", resp.status, data?.error?.message);
    throw providerError("Gemini", resp.status, data?.error?.message);
  }
  const outParts = data?.candidates?.[0]?.content?.parts || [];
  const img = outParts.find((p) => p.inlineData || p.inline_data);
  if (!img) {
    const reason = data?.candidates?.[0]?.finishReason || data?.promptFeedback?.blockReason;
    const text = outParts.map((p) => p.text).filter(Boolean).join(" ").slice(0, 200);
    throw providerError("Gemini", 0, reason ? `Reason: ${reason}.` : text || "No image was returned. Try again.");
  }
  const d = img.inlineData || img.inline_data;
  return { mediaType: d.mimeType || d.mime_type || "image/png", base64: d.data };
}

// ---------- OpenAI gpt-image ----------
async function runOpenAI({ prompt, selfie, styleImage, styleJson }) {
  const model = process.env.OPENAI_IMAGE_MODEL || "gpt-image-1";
  const form = new FormData();
  form.append("model", model);
  form.append("prompt", prompt);
  const ar = String(styleJson?.composition?.aspect_ratio || "1:1");
  form.append("size", /^(9:16|2:3|3:4|4:5)$/.test(ar) ? "1024x1536" : /^(16:9|3:2|4:3|5:4)$/.test(ar) ? "1536x1024" : "1024x1024");
  form.append("quality", process.env.OPENAI_IMAGE_QUALITY || "high");
  const toBlob = ({ mediaType, base64 }) => new Blob([Buffer.from(base64, "base64")], { type: mediaType });
  const ext = (t) => t.split("/")[1].replace("jpeg", "jpg");
  form.append("image[]", toBlob(selfie), `selfie.${ext(selfie.mediaType)}`);
  if (styleImage) form.append("image[]", toBlob(styleImage), `style.${ext(styleImage.mediaType)}`);

  const resp = await fetch("https://api.openai.com/v1/images/edits", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
    body: form,
    signal: AbortSignal.timeout(240000),
  }).catch((err) => {
    console.error("[openai]", err);
    throw providerError("OpenAI", 0, "Couldn't reach the OpenAI API.");
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    console.error("[openai]", resp.status, data?.error?.message);
    throw providerError("OpenAI", resp.status, data?.error?.message);
  }
  const b64 = data?.data?.[0]?.b64_json;
  if (!b64) throw providerError("OpenAI", 0, "No image was returned. Try again.");
  return { mediaType: "image/png", base64: b64 };
}
