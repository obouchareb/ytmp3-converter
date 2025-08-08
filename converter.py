from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse
import subprocess, tempfile, os, re
from urllib.parse import quote

app = FastAPI()

# Load cookies from ENV into a temp file for yt-dlp
COOKIES_ENV = os.environ.get("YTDLP_COOKIES")
COOKIE_PATH = None
if COOKIES_ENV:
    COOKIE_PATH = "/tmp/cookies.txt"
    with open(COOKIE_PATH, "w") as f:
        f.write(COOKIES_ENV)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

def sanitize(name: str, ext: str = "mp3") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "", name or "").strip()
    return f"{(name[:120] or 'episode')}.{ext}"

def ytdlp_cmd(url, out_base, title, description, client: str, use_cookies: bool):
    cmd = ["yt-dlp",
           "--user-agent", UA,
           "--referer", "https://www.youtube.com/"]
    # Choose a modern client
    # client = "android" or "web"
    cmd += ["--extractor-args", f"youtube:player_client={client}"]
    # Cookies?
    if use_cookies and COOKIE_PATH and os.path.exists(COOKIE_PATH):
        cmd += ["--cookies", COOKIE_PATH]
    # Convert to mp3 on disk (low memory) and write tags
    pp_args = f'ffmpeg:-metadata title={title} -metadata comment={description}'
    cmd += [
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-playlist",
        "--postprocessor-args", pp_args,
        "-o", out_base + ".%(ext)s",
        url,
    ]
    return cmd

def try_download(url, out_base, title, description, client, use_cookies):
    cmd = ytdlp_cmd(url, out_base, title, description, client, use_cookies)
    return subprocess.run(cmd, capture_output=True, text=True)

@app.get("/convert")
def convert(
    url: str = Query(..., description="YouTube URL"),
    title: str = Query("episode"),
    description: str = Query("")
):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_base = os.path.join(tmpdir, "out")
        have_cookies = bool(COOKIE_PATH and os.path.exists(COOKIE_PATH))

        # Try in this order:
        # 1) android + cookies   2) web + cookies
        # 3) android no cookies  4) web no cookies
        attempts = [
            ("android", True),
            ("web", True),
            ("android", False),
            ("web", False),
        ]
        last_err = ""
        for client, use_cookies in attempts:
            if use_cookies and not have_cookies:
                continue
            proc = try_download(url, out_base, title, description, client, use_cookies)
            if proc.returncode == 0:
                break
            last_err = f"[client={client} cookies={use_cookies}] {proc.stderr}\n"
        else:
            return PlainTextResponse("yt-dlp error:\n" + last_err, status_code=400)

        # Find mp3
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
