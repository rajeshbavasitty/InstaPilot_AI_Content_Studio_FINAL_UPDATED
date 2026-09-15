# InstaPilot AI — Full Content Studio

This is the full InstaPilot AI project: strategy → AI copy → Gemini image → live Instagram-style preview → approval → Instagram publishing.

## Important fixes in this version

- Keeps the full Content Studio UI; this is **not** a generate-image-only demo.
- Uses Gemini `gemini-3.1-flash-image` through the current Google GenAI Interactions API.
- Removes the broken `GenerateContentConfig(response_format=...)` image configuration that caused the `response_format Extra inputs are not permitted` error.
- Pins `google-genai==2.23.0` so the project uses a known current SDK version.
- Stores generated images under `generated/` and serves them from `/generated/...` for the local preview.
- Supports `PUBLIC_BASE_URL` so a public HTTPS URL can be returned for Instagram publishing.
- Supports `INSTAGRAM_USER_ID` + `INSTAGRAM_ACCESS_TOKEN` from Graph API Explorer for local testing.
- Includes `/api/instagram-test` to validate the stored Instagram token.

## Run on Windows PowerShell

```powershell
cd path\to\InstaPilot_AI_Content_Studio
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

Fill `.env` with your real keys. Do not commit `.env` to source control.

Start:

```powershell
python app.py
```

Open:

- http://127.0.0.1:5000/
- http://127.0.0.1:5000/api/health
- http://127.0.0.1:5000/api/status
- http://127.0.0.1:5000/api/instagram-test

## Gemini image generation

Set:

```text
GEMINI_API_KEY=your_key
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
```

Click **Generate content**, then **Generate image**. The generated PNG is saved in `generated/` and shown in the live Instagram preview.

## Public URL for Instagram publishing

A browser can display `http://127.0.0.1:5000/generated/...`, but Instagram's servers cannot fetch localhost. For publishing, expose the local server through a public HTTPS tunnel or deploy the app.

Example with ngrok:

```powershell
ngrok http 5000
```

If ngrok gives you:

```text
https://abc123.ngrok-free.app
```

put this in `.env`:

```text
PUBLIC_BASE_URL=https://abc123.ngrok-free.app
```

Restart Flask. After the next image generation, the app will return the public URL as well as the local preview URL.

## Instagram credentials

If you already have a Graph API Explorer token and user ID, set:

```text
INSTAGRAM_USER_ID=...
INSTAGRAM_ACCESS_TOKEN=...
```

The app seeds the local account automatically on startup.

For OAuth connection instead, set `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, and the exact `META_REDIRECT_URI` configured in Meta.


## Smooth Instagram image publishing

Image generation is optional. You can now upload an existing JPG, PNG, or WEBP image from the Content Studio.

The app converts uploads to JPEG, stores them under `generated/`, and automatically creates the public media URL from `PUBLIC_BASE_URL`. The manual public media URL field is no longer required.

For local testing:

1. Start Flask with `python app.py`.
2. In a second terminal run `ngrok http 5000`.
3. Put the HTTPS forwarding URL into `.env`:
   `PUBLIC_BASE_URL=https://YOUR-NGROK-DOMAIN`
4. Restart Flask.
5. Upload an image in the studio.
6. Approve the draft and click Publish to Instagram.

The app also checks that the public media URL is reachable before calling Meta. For production, replace ngrok with a permanent HTTPS deployment/storage URL.
