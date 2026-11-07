FROM python:3.12-slim

# ffmpeg for reading video; Node.js for Claude Code (the `claude` command)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg nodejs npm ca-certificates \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "from nudenet import NudeDetector; NudeDetector()"

COPY app ./app
COPY config.yaml /config/config.yaml

ENV DATA_DIR=/data MOVIES_DIR=/media/movies TV_DIR=/media/tv CONFIG_PATH=/config/config.yaml \
    HOME=/data/claude-home DISABLE_AUTOUPDATER=1 PYTHONUNBUFFERED=1
EXPOSE 6091
CMD ["sh", "-c", "mkdir -p \"$HOME\" && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-6091}"]
