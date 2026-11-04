import Anthropic from "@anthropic-ai/sdk";

const MODEL = process.env.CLAUDE_MODEL || "claude-opus-5-5";

const str = { type: "string" };
const strArr = { type: "array", items: { type: "string" } };
const obj = (properties) => ({
  type: "object",
  properties,
  required: Object.keys(properties),
  additionalProperties: false,
});

/** JSON schema for the style description (structured outputs guarantee this shape). */
export const STYLE_SCHEMA = obj({
  prompt_type: str,
  title: str,
  main_prompt: str,
  subject: obj({
    type: str,
    pose: str,
    face: obj({ features: str, facial_hair: str, skin_details: str }),
    hair: str,
    headwear: obj({ item: str, details: str }),
    clothing: obj({ item: str, details: str }),
  }),
  background: obj({ base: str, elements: strArr, composition: str }),
  color_accents: obj({ palette: strArr, style: str, placement: str, contrast: str }),
  art_style: obj({ medium: str, techniques: strArr, influences: str, detail_level: str }),
  lighting: obj({ type: str, shading: str }),
  mood: str,
  composition: obj({ framing: str, aspect_ratio: str, focus: str }),
  quality: strArr,
  negative_prompt: str,
});

const SYSTEM = `You are an expert art director and prompt engineer. You look at an image and write a complete, highly detailed JSON description that an image-generation model could use to recreate its exact look.

Rules:
- Capture everything about the visual style: medium, techniques, linework, textures, background elements, color palette and where colors appear, lighting, shading, mood, framing, aspect ratio.
- "main_prompt" is one rich paragraph that could stand alone as a generation prompt.
- Describe any person only generically (e.g. "adult man with a short beard"). Never name or guess the identity of a real person.
- Use "none" for fields that don't apply (e.g. no headwear). Use "image_generation" for prompt_type.
- "quality" holds short quality tags; "negative_prompt" lists things to avoid.`;

let client;
function getClient() {
  // Recreate if the key changed via Settings.
  if (!client || client.apiKey !== process.env.ANTHROPIC_API_KEY) {
    client = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
      baseURL: process.env.CLAUDE_BASE_URL || "https://api.anthropic.com",
    });
  }
  return client;
}

export async function extractStyleJson({ mediaType, base64 }) {
  let response;
  try {
    response = await getClient().beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: SYSTEM,
      output_config: {
        effort: "medium",
        format: { type: "json_schema", schema: STYLE_SCHEMA },
      },
      messages: [
        {
          role: "user",
          content: [
            { type: "image", source: { type: "base64", media_type: mediaType, data: base64 } },
            { type: "text", text: "Write the complete style JSON for this image." },
          ],
        },
      ],
    });
  } catch (err) {
    throw toFriendlyError(err);
  }

  if (response.stop_reason === "refusal") {
    const e = new Error("Claude declined to analyze this image. Try a different picture.");
    e.status = 422;
    throw e;
  }
  if (response.stop_reason === "max_tokens") {
    const e = new Error("The style description was cut off. Please try again.");
    e.status = 502;
    throw e;
  }

  const text = response.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("");
  try {
    return JSON.parse(text);
  } catch {
    const e = new Error("Couldn't read the style description. Please try again.");
    e.status = 502;
    throw e;
  }
}

function toFriendlyError(err) {
  let message = "Claude request failed.";
  let status = 502;
  if (err instanceof Anthropic.AuthenticationError) {
    message = "Your Anthropic API key was rejected. Check it in Settings.";
    status = 401;
  } else if (err instanceof Anthropic.RateLimitError) {
    message = "Claude is rate-limited right now. Wait a moment and try again.";
    status = 429;
  } else if (err instanceof Anthropic.BadRequestError) {
    message = `Claude rejected the request: ${err.error?.error?.message || err.message}`;
    status = 400;
  } else if (err instanceof Anthropic.APIStatusError) {
    message = `Claude API error (${err.status}). Please try again.`;
  } else if (err instanceof Anthropic.APIConnectionError) {
    message = "Couldn't reach the Claude API. Check the server's internet connection.";
  }
  const e = new Error(message);
  e.status = status;
  e.cause = err;
  console.error("[claude]", err?.status, err?.message);
  return e;
}
