from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
import subprocess, tempfile, os, re, sys
from urllib.parse import quote

app = FastAPI()

# ── Load cookies from ENV into a temp file for yt-dlp
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
    if use_cookies and COOKIE_PATH and os.path.exists(COOKIE_PATH):
        cmd += ["--cookies", COOKIE_PATH]

    # Write ID3 tags via ffmpeg, convert on disk (low memory)
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

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/debug")
def debug():
    # Quick sanity to see if cookies are present and yt-dlp is installed
    cookie_present = bool(COOKIE_PATH and os.path.exists(COOKIE_PATH))
    cookie_size = os.path.getsize(COOKIE_PATH) if cookie_present else 0
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        ytdlp_ver = (v.stdout or v.stderr).strip()
    except Exception as e:
        ytdlp_ver = f"error: {e}"
    return JSONResponse({
        "cookie_present": cookie_present,
        "cookie_size_bytes": cookie_size,
        "ytdlp_version": ytdlp_ver,
    })

@app.get("/convert")
def convert(
    url: str = Query(..., description="YouTube URL"),
    title: str = Query("episode"),
    description: str = Query("")
):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = os.path.join(tmpdir, "out")

        # 1) Try with cookies if we have them
        used_cookies = bool(COOKIE_PATH and os.path.exists(COOKIE_PATH))
        proc = run_ytdlp(url, out_base, title, description, use_cookies=used_cookies)

        # 2) If cookies fail or are invalid, try again without them
        if proc.returncode != 0 and "cookies" in (proc.stderr or "").lower():
            proc = run_ytdlp(url, out_base, title, description, use_cookies=False)

        if proc.returncode != 0:
            msg = "yt-dlp error:\n" + proc.stderr
            # make it obvious in the response whether cookies were used
            msg += f"\n(cookies_used={used_cookies})"
            return PlainTextResponse(msg, status_code=400)

        # Find resulting mp3
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
