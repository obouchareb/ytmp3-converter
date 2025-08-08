from fastapi import FastAPI, Query, Response
from fastapi.responses import StreamingResponse, PlainTextResponse
import subprocess, tempfile, os, io, re
from pydub import AudioSegment

app = FastAPI()

# Read cookies from an environment variable and write to a temp file
COOKIES_ENV = os.environ.get("YTDLP_COOKIES")
COOKIE_PATH = None
if COOKIES_ENV:
    COOKIE_PATH = "/tmp/cookies.txt"
    with open(COOKIE_PATH, "w") as f:
        f.write(COOKIES_ENV)

def sanitize(name: str, ext: str = "mp3") -> str:
    # Remove filesystem-unsafe chars and trim length
    name = re.sub(r'[\\/:*?"<>|]+', "", name or "").strip()
    if len(name) > 120:
        name = name[:120]
    return f"{name or 'episode'}.{ext}"

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/convert")
def convert(
    url: str = Query(..., description="YouTube URL"),
    title: str = Query("episode"),
    description: str = Query(""),
    filename: str = Query(None)
):
    # Ensure ffmpeg is available (needed by pydub)
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=False)
    except Exception as e:
        return PlainTextResponse(
            f"ffmpeg not available: {e}\nInstall ffmpeg on the server.",
            status_code=500
        )

    # Download best audio using yt-dlp to a temp file
    with tempfile.TemporaryDirectory() as tmp:
        download_path = os.path.join(tmp, "audio")

        cmd = ["yt-dlp"]
        # Use cookies if present to bypass YouTube bot checks
        if COOKIE_PATH and os.path.exists(COOKIE_PATH):
            cmd += ["--cookies", COOKIE_PATH]

        # Best available audio, write to temp with actual extension
        cmd += ["-f", "bestaudio/best", "-o", download_path + ".%(ext)s", url]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return PlainTextResponse(
                "yt-dlp error:\n" + proc.stderr,
                status_code=400
            )

        # Find the downloaded file (webm/m4a/opus)
        downloaded = None
        for fn in os.listdir(tmp):
            if fn.startswith("audio."):
                downloaded = os.path.join(tmp, fn)
                break

        if not downloaded or not os.path.exists(downloaded):
            return PlainTextResponse("No audio file downloaded", status_code=400)

        # Convert to mp3 and embed basic tags
        try:
            audio = AudioSegment.from_file(downloaded)
        except Exception as e:
            return PlainTextResponse(f"Could not read downloaded audio: {e}", status_code=500)

        mp3_bytes = io.BytesIO()
        # Libsyn reads ID3 tags; title and comment are enough for now
        try:
            audio.export(
                mp3_bytes,
                format="mp3",
                tags={"title": title or "episode", "comment": description or ""}
            )
        except Exception as e:
            return PlainTextResponse(f"MP3 export failed: {e}", status_code=500)

        mp3_bytes.seek(0)
        out_name = sanitize(filename or title, "mp3")
        headers = {"Content-Disposition": f'attachment; filename="{out_name}"'}
        return StreamingResponse(mp3_bytes, media_type="audio/mpeg", headers=headers)
