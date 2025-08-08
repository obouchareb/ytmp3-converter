FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY converter.py .
ENV PORT=8000
CMD uvicorn converter:app --host 0.0.0.0 --port ${PORT}
