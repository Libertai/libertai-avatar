# LibertAI Avatar

Open-source browser avatar chat system backed by LibertAI and designed for Aleph Cloud deployment.

## What ships in this MVP

- Next.js web app with a 3D avatar stage, chat panel, browser speech recognition, and browser speech synthesis.
- FastAPI gateway that calls LibertAI's OpenAI-compatible chat completions API.
- Browser-local memory only. The server does not persist conversations.
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
- Browser TTS uses local system voices through `speechSynthesis`.
- The app starts with a local procedural 3D avatar so it works offline. Paste a hosted `.vrm` asset URL in settings to use a VRM character.

## Aleph Cloud

The API is a plain ASGI app at `apps.api.main:app`, which is the intended deployment unit for Aleph Cloud functions. For v1, package the `apps/api` directory with its Python dependencies and configure:

- `LIBERTAI_API_KEY`
- `LIBERTAI_BASE_URL=https://api.libertai.io`
- `LIBERTAI_DEFAULT_MODEL=hermes-3-8b-tee`

Keep the web app as a static/Next deployment and point `NEXT_PUBLIC_API_BASE_URL` at the deployed function URL.
