import os, sqlite3, json, uuid, base64, re
from pathlib import Path
from urllib.parse import urlencode
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI
from google import genai

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

DB = BASE / "instapilot.db"
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated"
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")

# Instagram Login credentials are separate from the parent Meta/Facebook app credentials.
INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")

META_REDIRECT_URI = os.getenv("META_REDIRECT_URI", "http://127.0.0.1:5000/auth/meta/callback")
INSTAGRAM_GRAPH_VERSION = os.getenv("INSTAGRAM_GRAPH_VERSION", "v26.0").strip().strip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
META_SCOPES = os.getenv(
    "META_SCOPES",
    "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments,instagram_business_manage_messages"
)

# Optional: use a token obtained from Graph API Explorer for local testing.
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()

IDEA_BANK = {
    "fitness": [
        "3 mistakes beginners make in the gym", "7-day beginner workout challenge",
        "What I eat before a workout", "Muscle-building myth vs reality",
        "30-day transformation framework", "One exercise, three common mistakes"
    ],
    "business": [
        "The problem our product solves", "Before vs after using our service",
        "Founder story in 5 slides", "3 mistakes businesses make",
        "Customer FAQ carousel", "One customer problem and how we solve it"
    ],
    "restaurant": [
        "Customer favorite dish", "Behind the scenes in our kitchen",
        "3 things to try this weekend", "Limited-time combo offer",
        "Meet the chef", "How one signature dish is made"
    ],
    "fashion": [
        "3 ways to style one outfit", "New collection reveal",
        "Behind the scenes of a photoshoot", "Festival look guide",
        "Customer styling challenge", "One outfit, three occasions"
    ],
    "creator": [
        "A day in my life", "3 lessons I learned recently", "Behind the scenes",
        "Myth vs reality", "Answering follower questions",
        "My unpopular opinion about my niche"
    ],
    "real estate": [
        "5 things to check before buying a flat", "Property walkthrough in 30 seconds",
        "Locality price snapshot", "3 mistakes first-time buyers make",
        "Home-buying checklist", "What ₹X budget can buy in this locality"
    ]
}


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS account(
                id INTEGER PRIMARY KEY,
                ig_user_id TEXT,
                username TEXT,
                access_token TEXT,
                connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS drafts(
                id INTEGER PRIMARY KEY,
                idea TEXT,
                niche TEXT,
                goal TEXT,
                caption TEXT,
                hashtags TEXT,
                media TEXT,
                status TEXT DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # If Graph API Explorer credentials are present, make the account
        # immediately available to the UI. OAuth can still replace it later.
        if INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN:
            existing = c.execute("SELECT id FROM account LIMIT 1").fetchone()
            if not existing:
                username = ""
                try:
                    r = requests.get(
                        f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/me",
                        params={
                            "fields": "id,user_id,username",
                            "access_token": INSTAGRAM_ACCESS_TOKEN,
                        },
                        timeout=20,
                    )
                    if r.ok:
                        username = r.json().get("username", "")
                except Exception:
                    pass
                c.execute(
                    "INSERT INTO account(ig_user_id,username,access_token) VALUES(?,?,?)",
                    (INSTAGRAM_USER_ID, username, INSTAGRAM_ACCESS_TOKEN),
                )


def ai_text(prompt):
    if not openai_client:
        return None
    response = openai_client.responses.create(model=OPENAI_MODEL, input=prompt)
    return response.output_text


def generate_image(prompt):
    """Generate a square Instagram visual with Gemini 3.1 Flash Image.

    Uses the current Gemini Interactions API. The legacy generate_content
    fallback is intentionally configuration-free so it cannot hit the
    response_format/GenerateContentConfig validation error seen in older
    project versions.
    """
    if not gemini_client:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    image_data = None

    # Current Gemini image-generation path. Google documents response_format
    # on the Interactions API for Gemini 3.1 Flash Image.
    if hasattr(gemini_client, "interactions"):
        interaction = gemini_client.interactions.create(
            model=GEMINI_IMAGE_MODEL,
            input=prompt,
            response_format={
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": "1:1",
                "image_size": "1K",
            },
        )
        output_image = getattr(interaction, "output_image", None)
        image_data = getattr(output_image, "data", None) if output_image else None

        # Some SDK versions expose the generated image only through steps.
        if not image_data:
            for step in getattr(interaction, "steps", []) or []:
                if getattr(step, "type", None) != "model_output":
                    continue
                for block in getattr(step, "content", []) or []:
                    if getattr(block, "type", None) == "image" and getattr(block, "data", None):
                        image_data = block.data
                        break
                if image_data:
                    break
    else:
        # Compatibility fallback: request the image only and let Gemini use
        # its default square/1K output. Do NOT pass response_format to
        # GenerateContentConfig because some installed SDKs reject it.
        response = gemini_client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
        )
        for part in getattr(response, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, bytes):
                    image_data = base64.b64encode(data).decode("ascii")
                else:
                    image_data = data
                break

    if not image_data:
        raise RuntimeError("Gemini did not return image data.")

    filename = f"{uuid.uuid4().hex}.png"
    path = GENERATED / filename
    if isinstance(image_data, bytes):
        path.write_bytes(image_data)
    else:
        path.write_bytes(base64.b64decode(image_data))

    relative_url = f"/generated/{filename}"
    public_url = f"{PUBLIC_BASE_URL}{relative_url}" if PUBLIC_BASE_URL else relative_url
    return relative_url, public_url


def meta_authorized():
    # The Instagram Login OAuth flow is authorized by the Instagram App
    # credentials, not the parent Meta/Facebook App credentials.
    return bool(INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET)


@app.get("/")
def home():
    with get_db() as c:
        account = c.execute("SELECT * FROM account LIMIT 1").fetchone()
        drafts = c.execute("SELECT * FROM drafts ORDER BY id DESC LIMIT 20").fetchall()
    return render_template("index.html", account=account, drafts=drafts,
                           ai_enabled=bool(OPENAI_API_KEY), meta_enabled=meta_authorized(),
                           image_enabled=bool(GEMINI_API_KEY))


@app.get("/generated/<path:filename>")
def generated_file(filename):
    return send_from_directory(GENERATED, filename)


@app.get("/api/status")
def status():
    with get_db() as c:
        account = c.execute("SELECT * FROM account LIMIT 1").fetchone()
    return jsonify({
        "ai_enabled": bool(OPENAI_API_KEY),
        "ai_model": OPENAI_MODEL,
        "image_enabled": bool(GEMINI_API_KEY),
        "image_model": GEMINI_IMAGE_MODEL,
        "meta_configured": meta_authorized(),
        "instagram_connected": bool(account),
        "instagram_username": account["username"] if account else None,
        "public_base_url_configured": bool(PUBLIC_BASE_URL),
        "public_base_url": PUBLIC_BASE_URL or None,
        "media_upload_enabled": True,
        "graph_api_version": INSTAGRAM_GRAPH_VERSION
    })


@app.post("/api/ideas")
def ideas():
    niche = request.form.get("niche", "business").strip().lower()
    goal = request.form.get("goal", "Grow followers")
    audience = request.form.get("audience", "")
    language = request.form.get("language", "English")
    if openai_client:
        prompt = f"""
You are an expert Instagram content strategist.
Create exactly 10 fresh, practical Instagram content ideas.
Niche: {niche}\nGoal: {goal}\nAudience: {audience or 'general audience'}\nLanguage: {language}
Avoid generic ideas. Make each idea specific enough to become a post or Reel.
Return ONLY a JSON array of strings. No markdown.
"""
        try:
            parsed = json.loads(ai_text(prompt))
            if isinstance(parsed, list):
                return jsonify(ideas=parsed[:10], source="openai")
        except Exception as e:
            return jsonify(error=f"OpenAI request failed: {e}", fallback=IDEA_BANK.get(niche, IDEA_BANK["business"]), source="fallback")
    return jsonify(ideas=IDEA_BANK.get(niche, IDEA_BANK["business"]), source="local")


@app.post("/api/generate")
def generate():
    idea = request.form.get("idea", "").strip()
    niche = request.form.get("niche", "business")
    goal = request.form.get("goal", "Grow followers")
    audience = request.form.get("audience", "")
    language = request.form.get("language", "English")
    tone = request.form.get("tone", "Professional and engaging")
    content_type = request.form.get("content_type", "Carousel")
    if not idea:
        return jsonify(error="Please select or enter an idea."), 400

    if openai_client:
        prompt = f"""
Create an Instagram content package for a {content_type}.
Idea: {idea}\nNiche: {niche}\nGoal: {goal}\nAudience: {audience or 'general audience'}\nLanguage: {language}\nTone: {tone}
Return ONLY valid JSON:
{{
  "hook": "short attention-grabbing opening",
  "caption": "complete Instagram caption",
  "cta": "clear call to action",
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
  "reel_script": "short Reel script",
  "carousel_outline": ["slide 1", "slide 2", "slide 3", "slide 4", "slide 5"],
  "visual_direction": "one detailed visual direction for the main Instagram image"
}}
"""
        try:
            data = json.loads(ai_text(prompt))
            return jsonify(data=data, source="openai")
        except Exception as e:
            return jsonify(error=f"OpenAI request failed: {e}"), 502

    return jsonify(data={
        "hook": idea,
        "caption": f"{idea}\n\nPractical tips for the {niche} audience. Save this post and share it with someone who needs it.",
        "cta": "Save this post and follow for more.",
        "hashtags": [f"#{niche.replace(' ', '')}", "#Instagram", "#ContentCreator", "#Growth", "#India"],
        "reel_script": f"Hook: {idea}\nExplain the key points.\nEnd with the CTA.",
        "carousel_outline": [idea, "Why this matters", "The common mistake", "What to do instead", "Save and share"],
        "visual_direction": f"Premium editorial Instagram visual about {idea}, {niche} aesthetic, clean composition, realistic photography, strong subject separation, no text overlay."
    }, source="local")


@app.post("/api/generate-image")
def generate_image_api():
    prompt = request.form.get("prompt", "").strip()
    idea = request.form.get("idea", "").strip()
    niche = request.form.get("niche", "fitness")
    tone = request.form.get("tone", "Professional and engaging")
    if not prompt:
        prompt = f"""
Create a premium Instagram-ready square visual for this content idea: {idea}.
Niche: {niche}. Tone: {tone}.
Use a polished editorial social-media aesthetic, strong focal subject, cinematic but natural lighting,
clean background, realistic photography, high contrast, tasteful composition and clear negative space.
Do not include logos, watermarks, UI, borders, or readable text.
The image should look like a professional creator/brand Instagram post, not like a stock photo.
"""
    if not gemini_client:
        return jsonify(error="GEMINI_API_KEY is not configured."), 400
    try:
        image_url, public_url = generate_image(prompt)
        return jsonify(
            ok=True,
            image_url=image_url,
            public_url=public_url if PUBLIC_BASE_URL else None,
            model=GEMINI_IMAGE_MODEL,
        )
    except Exception as e:
        return jsonify(error=f"Image generation failed: {e}"), 502


@app.post("/api/upload-media")
def upload_media():
    """Accept an existing local image and make it publishable through PUBLIC_BASE_URL."""
    file = request.files.get("media")
    if not file or not file.filename:
        return jsonify(ok=False, error="Choose an image file first."), 400

    allowed = {"image/jpeg", "image/png", "image/webp"}
    if file.mimetype not in allowed:
        return jsonify(ok=False, error="Please upload a JPG, PNG, or WEBP image."), 400

    try:
        from PIL import Image, UnidentifiedImageError

        image = Image.open(file.stream)
        image.load()
        image = image.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg"
        path = GENERATED / filename
        image.save(path, format="JPEG", quality=92, optimize=True)

        relative_url = f"/generated/{filename}"
        public_url = f"{PUBLIC_BASE_URL}{relative_url}" if PUBLIC_BASE_URL else None

        return jsonify(
            ok=True,
            image_url=relative_url,
            public_url=public_url,
            filename=filename,
            publish_ready=bool(public_url),
            message=(
                "Image uploaded and is ready for Meta."
                if public_url
                else "Image uploaded for preview. Set PUBLIC_BASE_URL for Instagram publishing."
            ),
        )
    except UnidentifiedImageError:
        return jsonify(ok=False, error="The uploaded file is not a valid image."), 400
    except Exception as e:
        return jsonify(ok=False, error=f"Image upload failed: {e}"), 500


@app.post("/api/save")
def save():
    with get_db() as c:
        cur = c.execute("""
            INSERT INTO drafts(idea,niche,goal,caption,hashtags,media,status)
            VALUES(?,?,?,?,?,?,?)
        """, (
            request.form.get("idea"), request.form.get("niche"), request.form.get("goal"),
            request.form.get("caption"), request.form.get("hashtags"), request.form.get("media"), "approved"
        ))
    return jsonify(ok=True, id=cur.lastrowid)


@app.get("/auth/meta")
def meta_login():
    if not META_APP_ID or not META_APP_SECRET:
        return redirect(url_for("home") + "?meta_setup=1")
    params = {
        "client_id": INSTAGRAM_APP_ID,
        "redirect_uri": META_REDIRECT_URI,
        "scope": META_SCOPES,
        "response_type": "code",
        "enable_fb_login": "0",
    }
    return redirect("https://www.instagram.com/oauth/authorize?" + urlencode(params))


@app.get("/auth/meta/callback")
def meta_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("home") + "?meta_error=no_code")
    try:
        token_response = requests.post("https://api.instagram.com/oauth/access_token", data={
            "client_id": INSTAGRAM_APP_ID, "client_secret": INSTAGRAM_APP_SECRET, "grant_type": "authorization_code",
            "redirect_uri": META_REDIRECT_URI, "code": code
        }, timeout=30)
        if not token_response.ok:
            return redirect(url_for("home") + "?meta_error=" + requests.utils.quote(token_response.text[:300]))
        token_data = token_response.json()
        short_token, user_id = token_data["access_token"], token_data["user_id"]
        exchange = requests.get("https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": INSTAGRAM_APP_SECRET, "access_token": short_token
        }, timeout=30)
        token = exchange.json().get("access_token", short_token)
        me = requests.get(f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/me", params={"fields": "id,user_id,username", "access_token": token}, timeout=30)
        if not me.ok:
            return redirect(url_for("home") + "?meta_error=" + requests.utils.quote(me.text[:300]))
        info = me.json()
        instagram_id, username = info.get("user_id") or user_id, info.get("username", "")
        with get_db() as c:
            c.execute("DELETE FROM account")
            c.execute("INSERT INTO account(ig_user_id,username,access_token) VALUES(?,?,?)", (instagram_id, username, token))
        return redirect(url_for("home") + "?connected=1")
    except Exception as e:
        return redirect(url_for("home") + "?meta_error=" + requests.utils.quote(str(e)[:300]))


@app.get("/api/instagram-test")
def instagram_test():
    """Validate the stored Instagram token against the configured Graph API."""
    with get_db() as c:
        account = c.execute("SELECT * FROM account LIMIT 1").fetchone()
    if not account:
        return jsonify(ok=False, error="No Instagram account is connected."), 400
    try:
        r = requests.get(
            f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/me",
            params={
                "fields": "id,user_id,username",
                "access_token": account["access_token"],
            },
            timeout=20,
        )
        try:
            payload = r.json()
        except Exception:
            payload = r.text
        return jsonify(ok=r.ok, status=r.status_code, response=payload)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 502


@app.post("/api/publish")
def publish():
    with get_db() as c:
        account = c.execute("SELECT * FROM account LIMIT 1").fetchone()
    if not account:
        return jsonify(error="Connect Instagram first."), 400
    media_url = request.form.get("media_url", "").strip()
    caption = request.form.get("caption", "")
    if media_url.startswith("/generated/") and PUBLIC_BASE_URL:
        media_url = f"{PUBLIC_BASE_URL}{media_url}"
    if not media_url.startswith("https://"):
        return jsonify(error="No publishable image URL is available. Upload an image and configure PUBLIC_BASE_URL (for example your ngrok HTTPS URL)."), 400
    try:
        # Fail early with a useful message if Meta cannot fetch the media URL.
        media_check = requests.get(media_url, stream=True, timeout=20, allow_redirects=True)
        media_check.raise_for_status()
        media_check.close()
        create = requests.post(f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/{account['ig_user_id']}/media", data={
            "image_url": media_url, "caption": caption, "access_token": account["access_token"]
        }, timeout=30)
        if not create.ok:
            return jsonify(error=create.text), 400
        creation_id = create.json().get("id")
        publish_response = requests.post(f"https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/{account['ig_user_id']}/media_publish", data={
            "creation_id": creation_id, "access_token": account["access_token"]
        }, timeout=30)
        if not publish_response.ok:
            return jsonify(error=publish_response.text), 400
        return jsonify(ok=True, result=publish_response.json())
    except Exception as e:
        return jsonify(error=str(e)), 502


@app.get("/health")
def health():
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
