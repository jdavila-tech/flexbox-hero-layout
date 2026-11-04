# StyleShift

Turn your photo into the style of any image you love.

1. **Inspiration image:** upload, drag-and-drop, paste, or link any picture. Claude reads it in the background and produces a complete style JSON (art style, background, colors, lighting, mood, composition, negative prompt). The JSON is shown and editable.
2. **Your photo:** upload one, or take one on the spot with your webcam or phone camera (live preview, flip camera, 3-second timer, retake).
3. **Convert:** applies the style JSON to your photo while keeping your face and identity, then shows a before/after with Download and Regenerate.

## How it works

| Step | Service | Why |
|---|---|---|
| Image → style JSON | Claude (`claude-opus-5-5`, vision + structured outputs) | Guarantees the JSON always has the same complete schema |
| Your photo + JSON → new image | Google Gemini image model (default) or OpenAI `gpt-image-1` | Claude analyzes images but doesn't generate them, so an image-editing model does the drawing |

The server builds the generation prompt from the JSON. It deliberately leaves out the inspiration image's face and hair description, so you keep your own likeness, and applies everything else. Two toggles control whether to copy the outfit and pose, and whether to send the inspiration image as an extra visual reference.

Photos are processed in memory and never written to disk.

## Setup

```bash
cd style-transfer-app
npm install
cp .env.example .env     # optional: you can also enter keys in the app's Settings
npm start                # http://localhost:4000
```

You need:
- An **Anthropic API key** from https://console.anthropic.com/settings/keys
- A **Gemini API key** (free tier available) from https://aistudio.google.com/apikey, **or** an OpenAI key

Keys can be added from the ⚙️ **Settings** button in the app. They're saved to `.env` on the server and never sent back to the browser.

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `4000` | Port the app listens on |
| `ANTHROPIC_API_KEY` | none | Style extraction |
| `IMAGE_PROVIDER` | auto | `gemini` or `openai` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | none | Image generation |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for style extraction |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` | Gemini image model |
| `OPENAI_IMAGE_MODEL` | `gpt-image-1` | OpenAI image model |
| `ACCESS_CODE` | none | If set, visitors must enter this code (protects your API credits on a public server) |

## Using the camera from your phone

Browsers only allow live camera access on `https://` pages or `localhost`. Options:
- Put the app behind HTTPS (for example `npx localtunnel --port 4000`, `cloudflared tunnel --url http://localhost:4000`, or a reverse proxy with a certificate).
- Over plain `http://`, the **Take photo** button falls back to your phone's native camera picker, which still lets you snap a photo.

If you expose the app to the internet, set `ACCESS_CODE` so strangers can't use your API keys.

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/config` | none | Which keys are set and which provider is in use |
| `POST` | `/api/config` | `{anthropicKey?, geminiKey?, openaiKey?, imageProvider?}` | Updated config |
| `POST` | `/api/fetch-image` | `{url}` | `{dataUrl}` |
| `POST` | `/api/analyze` | `{image: dataUrl}` | `{styleJson}` |
| `POST` | `/api/convert` | `{selfie, styleImage?, styleJson, matchOutfit, useStyleReference}` | `{image: dataUrl, provider}` |
