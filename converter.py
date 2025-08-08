from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, Response
import subprocess, tempfile, os, io, re
from pydub import AudioSegment

app = FastAPI()

def sanitize(name: str, ext: str = "mp3") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', '', name).strip()
    name = name[:120] if len(name) > 120 else name
    return f"{name or 'episode'}.{ext}"

@app.get("/convert")
def convert(url: str = Query(...), title: str = Query("episode"), description: str = Query(""), filename: str = Query(None)):
    with tempfile.TemporaryDirectory() as tmp:
        download_path = os.path.join(tmp, "audio")
        cmd = ["yt-dlp", "-f", "bestaudio/best", "-o", download_path + ".%(ext)s", url]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return Response(status_code=400, content=f"yt-dlp error: {r.stderr}")
        downloaded = None
        for fn in os.listdir(tmp):
            if fn.startswith("audio."):
                downloaded = os.path.join(tmp, fn)
                break
        if not downloaded:
            return Response(status_code=400, content="No audio file downloaded")
        audio = AudioSegment.from_file(downloaded)
        mp3_bytes = io.BytesIO()
        audio.export(mp3_bytes, format="mp3", tags={"title": title, "comment": description})
        mp3_bytes.seek(0)
        out_name = sanitize(filename or title, "mp3")
        headers = {"Content-Disposition": f'attachment; filename="{out_name}"'}
        return StreamingResponse(mp3_bytes, media_type="audio/mpeg", headers=headers)
