from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse
import subprocess, tempfile, os, re
from urllib.parse import quote

app = FastAPI()

# Read YouTube cookies from an env var and persist to a temp file for yt-dlp
COOKIES_ENV = os.environ.get("YTDLP_COOKIES")
COOKIE_PATH = None
if COOKIES_ENV:
    COOKIE_PATH = "/tmp/cookies.txt"
    with open(COOKIE_PATH, "w") as f:
        f.write(COOKIES_ENV)

def sanitize(name: str, ext: str = "mp3") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "", name or "").strip()
    return f"{(name[:120] or 'episode')}.{ext}"

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/convert")
def convert(
    url: str = Query(..., description="YouTube URL"),
    title: str = Query("episode"),
    description: str = Query("")
):
    # Make a temporary work folder for this request
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = os.path.join(tmpdir, "out")  # yt-dlp will set extension
        cmd = ["yt-dlp"]

        # Use cookies if available to pass YouTube bot checks
        if COOKIE_PATH and os.path.exists(COOKIE_PATH):
            cmd += ["--cookies", COOKIE_PATH]

        # Extract best audio and convert to mp3 on disk (no RAM buffering)
        # Also write ID3 metadata via ffmpeg so Libsyn picks it up
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

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return PlainTextResponse("yt-dlp error:\n" + proc.stderr, status_code=400)

        # Find the resulting mp3 file
        mp3_path = None
        for fn in os.listdir(tmpdir):
            if fn.startswith("out.") and fn.endswith(".mp3"):
                mp3_path = os.path.join(tmpdir, fn)
                break
        if not mp3_path or not os.path.exists(mp3_path):
            return PlainTextResponse("No MP3 produced", status_code=500)

        # Stream the file from disk (low memory)
        filename = sanitize(title, "mp3")
        return FileResponse(
            mp3_path,
            media_type="audio/mpeg",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'}
        )
