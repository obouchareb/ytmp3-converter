from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse
import subprocess, tempfile, os, re
from urllib.parse import quote

app = FastAPI()

# Load cookies from ENV into a temp file
COOKIES_ENV = os.environ.get("YTDLP_COOKIES")
COOKIE_PATH = None
if COOKIES_ENV:
    COOKIE_PATH = "/tmp/cookies.txt"
    with open(COOKIE_PATH, "w") as f:
        f.write(COOKIES_ENV)

def sanitize(name: str, ext: str = "mp3") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "", name or "").strip()
    return f"{(name[:120] or 'episode')}.{ext}"

def run_ytdlp(url, out_base, title, description, use_cookies=True):
    cmd = ["yt-dlp"]

    # Use cookies if we have them
    if use_cookies and COOKIE_PATH and os.path.exists(COOKIE_PATH):
        cmd += ["--cookies", COOKIE_PATH]

    # Spoof as modern web client to bypass "app" restriction
    cmd += ["--extractor-args", "youtube:player_client=web"]

    # Convert to mp3 with tags on disk (low memory)
    pp_args = f'ffmpeg:-metadata title={title} -metadata comment={description}'
    cmd += [
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist",
        "--postprocessor-args", pp_args,
        "-o", out_base + ".%(ext)s",
        url,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)

@app.get("/convert")
def convert(
    url: str = Query(..., description="YouTube URL"),
    title: str = Query("episode"),
    description: str = Query("")
):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = os.path.join(tmpdir, "out")

        used_cookies = bool(COOKIE_PATH and os.path.exists(COOKIE_PATH))
        proc = run_ytdlp(url, out_base, title, description, use_cookies=used_cookies)

        # Fallback without cookies if needed
        if proc.returncode != 0 and "cookies" in (proc.stderr or "").lower():
            proc = run_ytdlp(url, out_base, title, description, use_cookies=False)

        if proc.returncode != 0:
            return PlainTextResponse(
                "yt-dlp error:\n" + proc.stderr + f"\n(cookies_used={used_cookies})",
                status_code=400
            )

        mp3_path = None
        for fn in os.listdir(tmpdir):
            if fn.startswith("out.") and fn.endswith(".mp3"):
                mp3_path = os.path.join(tmpdir, fn)
                break

        if not mp3_path:
            return PlainTextResponse("No MP3 produced", status_code=500)

        filename = sanitize(title, "mp3")
        return FileResponse(
            mp3_path,
            media_type="audio/mpeg",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'}
        )
