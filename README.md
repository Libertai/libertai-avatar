# LibertAI Avatar

Open-source browser avatar chat system backed by LibertAI and designed for Aleph Cloud deployment.

## What ships in this MVP

- Next.js web app with a 3D VRM avatar, phoneme-accurate lipsync, blinking, gaze and speech gestures.
- **Scenarios**: named avatars with their own rules, dataset, voice and tools, each on its own link.
- **MCP tools**: an avatar can call any MCP server for live data, over stdio, HTTP or SSE.
- Local neural speech (Piper) in English, French, Spanish, German and Arabic, plus browser voices.
- Click-to-talk speech recognition, transcribed locally with Whisper by default.
- FastAPI gateway that calls LibertAI's OpenAI-compatible chat completions API.
- SQLite for scenarios and the MCP registry; conversations are never persisted.
- Two credential modes:
  - `LIBERTAI_API_KEY` on the API server.
  - Optional bring-your-own key from the browser for self-hosted demos.

## Local setup

Install frontend dependencies:

```bash
npm install
```

Create API environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
cp apps/api/.env.example apps/api/.env
```

Set `LIBERTAI_API_KEY` in your shell or `apps/api/.env` if you want the server-key mode.

Run the API:

```bash
npm run api:dev
```

Run the web app in another shell:

```bash
npm run dev
```

Open `http://localhost:3000`.

## Notes

- Browser speech recognition is currently best supported in Chromium-based browsers. The UI falls back to typed chat when unavailable.
- The microphone is click-to-start, click-to-stop. Recording continues through pauses, the live transcript fills the composer, and the message is sent when you stop.
- Speech speed (0.75x/1x/1.5x) and a stop button sit in the composer, and apply to both engines.
- Speech output has two engines, selectable in settings. Browser voices (`speechSynthesis`) are preferred; the server engine is used automatically when the browser reports no voices.
- Chromium only exposes system voices when started with `--enable-speech-dispatcher` and with `libspeechd.so.2` on its library path, so browser voices are often empty on Linux.

## Scenarios

A scenario is a named avatar — its rules, dataset, voice, language, avatar model and tools — served at its own link, `/s/pizzeria`. Send a client the link and they talk to it. Nothing to install, nothing to explain.

Four ship as examples, each with its own MCP server:

| Link | Scenario | Language | Live data |
|---|---|---|---|
| `/s/pizzeria` | Tony's Pizzeria — phone orders | English | delivery estimate, order status |
| `/s/clinic` | Clinique Saint-Jean — appointments | French | availability, booking, lookup |
| `/s/telecom` | Nova Telecom — billing and support | English | account, network, upgrades |
| `/s/flights` | Aviva Air — flight booking | English | search, booking, lookup |

Manage them at **`/scenarios`**: create, edit, duplicate, publish, copy link, delete. Register MCP servers at **`/scenarios/servers`**, with a **Test connection** button that opens a real session and lists the tools it found — worth clicking before a demo.

Scenarios live in SQLite (`AVATAR_DB`, default `apps/api/avatar.db`). The JSON files in `apps/api/scenarios/` are the versioned examples, seeded into the database on first start; seeding only inserts what is missing, so an edited scenario is never overwritten by its shipped version.

**Rules and data never reach a browser.** `GET /scenarios/{slug}` returns presentation only — name, description, language, voice, avatar, greeting, speed. `POST /chat` takes `{"scenario": "pizzeria"}` and the server composes the prompt, so a visitor cannot read the dataset or rewrite the rules.

Static facts (menus, prices, policies) belong in the dataset, injected whole into the prompt — exact, debuggable, no retrieval step to get wrong. Reach for MCP only when the answer depends on live state.

Drafts (`published: false`) are hidden from the public list but stay reachable by direct link, so a scenario can be previewed before it is announced.

### Admin access

Scenario and MCP editing decide which prompts run and which servers the API contacts, so they are administrative. Set `ADMIN_TOKEN` and the endpoints require an `X-Admin-Token` header; the UI keeps the token in the browser only.

Left unset, the endpoints stay open — convenient locally, and the scenarios page shows a standing warning so an unprotected deployment is obvious rather than silent. `GET /health` reports `admin_protected` for a deployment check.

### MCP tools

MCP servers have nothing to do with LibertAI: they are ordinary MCP servers, run by anyone. A scenario can draw on **several at once** — a booking system, a pricing service, a public data server — and three transports are supported: `http` (what remote servers normally speak), `sse` (older remote servers), and `stdio` (a local process, for servers shipped alongside the API).

Credentials are **encrypted at rest** with a key that lives outside the database (`AVATAR_SECRET_KEY`, or a generated `apps/api/.secret_key`), and are masked in every API response — the editor can change a server without ever receiving its token back. Write `Bearer ${AGENDA_TOKEN}` instead to resolve it from the environment at call time, and nothing is stored at all.

Rules that matter when composing several servers:

- **Servers are queried in the order listed, and the first to claim a tool name wins.** A later server cannot shadow an earlier one's tool — put the most trusted first.
- A scenario's tool allowlist is deny-by-default, checked again before execution. A server may expose far more than a given avatar should be able to call.
- **The browser can never name a server, URL, or command.** That would mean arbitrary process execution on the API host and requests to arbitrary internal addresses.
- Tool discovery is cached for `MCP_DISCOVERY_TTL` (300s) per server. Without it every message re-handshakes with every server — measured at ~840ms against a local one, worse over the network.
- Tool calls are capped at 3 rounds per reply, each with a `MCP_TOOL_TIMEOUT` (15s) limit. A server that fails to start is skipped rather than taking the conversation down.
- Tool results reach the browser in `tool_calls` and render beside the reply, so a wrong lookup is visible rather than plausible.
- While a tool runs the avatar says "let me check that for you" in the conversation's language, because a silent talking head reads as broken.

Third-party servers are untrusted on two axes: what they return (prompt injection — the system prompt tells the model to treat results as data, never instructions) and whether they answer at all (hence the timeouts and skip-on-failure).

Two things to know when writing scenario rules: the demo datasets are deliberately fake, and no conversation is persisted — an order is summarized on screen and discarded. Keep it that way, or the doctor and telecom scenarios start collecting real personal data.

### Streaming and the call summary

`POST /chat/stream` sends the reply as server-sent events — `delta` for text, `tool` when a lookup completes, `done` at the end — and the web app speaks each sentence as it finishes rather than waiting for the whole reply. Chunks are synthesized in order and queued, so a streamed answer is heard as one continuous utterance. `POST /chat` still returns a whole reply for non-browser callers.

A scenario's `collect` field lists what the call is meant to come away with (`["phone", "items", "total"]`). **End call** then asks the model once, at the end, to extract those fields from the transcript, and the recap shows which were filled and which the caller never gave. Nothing is persisted: the summary is shown and discarded with the page.

If you deploy behind a proxy, make sure it does not buffer `text/event-stream`, or the reply will arrive all at once and the streaming gain is lost.

## Speech to text

`POST /stt/transcribe` transcribes a recording with Whisper (`faster-whisper`) on the same machine as everything else. The browser's own recognition is a cloud service — Chromium sends the audio to Google — which sits badly with a stack whose point is that inference stays where you put it, so the server engine is the default and the browser one is a fallback.

The model is chosen with `WHISPER_MODEL` (default `base`, ~150MB) and downloads on first use. Measured on CPU with `int8`: 3.6s of speech transcribed in 0.6s once the model is warm, correctly hearing a spoken postcode. `GET /stt/status` reports whether the server can transcribe, and the microphone falls back to browser recognition when it cannot.

Recording uses the microphone stream the level meter already opens, in whatever container the browser supports (`webm/opus` in Chromium). Whisper decodes it through PyAV, so no ffmpeg binary is needed.

## Avatar animation

- **Lipsync.** `POST /tts/speak` returns a viseme timeline alongside the audio, built from Piper's per-phoneme sample counts. IPA phonemes collapse onto VRM's five mouth shapes (`aa`, `ih`, `ou`, `ee`, `oh`) in `apps/api/visemes.py`; the web app looks up the shape for the current playback position and damps toward it. Browser voices expose no phoneme timing, so they fall back to amplitude-driven jaw movement.
- **Face.** Randomized blinking (every 2–6s) and `vrm.lookAt` aimed at the camera, so the eyes track the viewer.
- **Body.** Overlapping sine layers drive beat gestures, head nods, and weight shifts, amplified while speaking. The two arms run on different frequencies so they do not move as a mirrored pair.
- **Gesture clips.** Settings takes a `.vrma` file (VRM Animation), retargeted onto the avatar's humanoid rig via `@pixiv/three-vrm-animation`. A loaded clip drives the bones and replaces the procedural motion; the face and lipsync keep running on top. VRoid publishes free sample clips — check the licence of any pack before shipping it.

A realistic (non-anime) avatar generally comes from Avaturn, Ready Player Me, or Character Creator, then through Blender's VRM add-on to map humanoid bones and expressions. Without a full humanoid rig the model loads but stays frozen, and without the five mouth expressions it will not lipsync.

## Server speech (Piper)

`POST /tts/speak` synthesizes WAV audio locally with [Piper](https://github.com/OHF-Voice/piper1-gpl); `GET /tts/voices` lists what is installed. Nothing is sent to a third party.

Voices are `.onnx` files (plus their `.onnx.json` config) in `apps/api/voices`, overridable with `PIPER_VOICES_DIR`. They are gitignored — download one to enable the engine:

```bash
mkdir -p apps/api/voices && cd apps/api/voices
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium
curl -LO $BASE/en_US-amy-medium.onnx -O $BASE/en_US-amy-medium.onnx.json
```

Browse the full catalogue at https://huggingface.co/rhasspy/piper-voices — 175 voices across 30+ languages, in `low`/`medium`/`high` quality. `high` voices sound noticeably more natural and are worth the extra download.

Some voices bundle many speakers in one file (`en_US-libritts-high` has 904, `fr_FR-mls-medium` has 125). The API reports the count and `/tts/speak` accepts a `speaker` index, which the settings panel exposes as a Speaker dropdown.

Each loaded voice holds roughly 100MB of RSS, and synthesis is CPU-bound, so `/tts/speak` runs in FastAPI's threadpool.

The Language setting drives three things at once: which voices are offered, the microphone's recognition language, and the language the avatar is asked to reply in. The list is built from the voices actually installed, so adding a `de_DE-*.onnx` file makes German appear.

On NixOS the `onnxruntime`/`numpy` wheels need libraries that aren't on the default path:

```bash
export LD_LIBRARY_PATH=$(nix-build '<nixpkgs>' -A stdenv.cc.cc.lib --no-out-link)/lib:$(nix-build '<nixpkgs>' -A zlib --no-out-link)/lib
```
- The app starts with a curated CC0 VRM avatar from the Open Source Avatars 100Avatars collection, hosted on Arweave. Pick another preset or paste a hosted `.vrm` asset URL in settings.
- Avatar source: https://github.com/ToxSam/open-source-avatars

## Deployment

The API is a plain ASGI app at `apps.api.main:app`. Four things it needs that a plain proxy did not:

- **Writable storage** for `AVATAR_DB` (scenarios and the MCP registry) and `AVATAR_SECRET_KEY_FILE`. Set `AVATAR_SECRET_KEY` from the environment instead of relying on the generated key file, or a redeploy onto fresh storage makes stored MCP credentials unreadable.
- **Voice files**, if you want server speech. They are gitignored and total a few hundred MB; ship them in the image or mount them and point `PIPER_VOICES_DIR` at them.
- **A Whisper model**, if you want local transcription. It downloads on first use into the HuggingFace cache, so give that a writable, persistent path or bake it into the image.
- **`ADMIN_TOKEN`**, before the API is reachable from anywhere but your laptop.

### MCP servers on a serverless host

The demo servers default to `stdio`, which means the API spawns them as subprocesses. **A serverless function generally cannot do that.** Each server can also listen over HTTP:

```bash
MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8081 python apps/api/mcp_servers/clinic.py
```

Deploy them as their own services and register them by URL (`transport: "http"`, `url: "https://…/mcp"`) instead of by command. Verified working end to end: a server started this way lists its tools and answers calls through the same client the stdio path uses.

Set `LIBERTAI_API_KEY`, `LIBERTAI_BASE_URL` and `LIBERTAI_DEFAULT_MODEL` as before. Keep the web app as a Next deployment and point `NEXT_PUBLIC_API_BASE_URL` at the API, and `CORS_ALLOW_ORIGINS` at the web origin.
