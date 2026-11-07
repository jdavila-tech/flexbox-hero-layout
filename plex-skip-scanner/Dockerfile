FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "from nudenet import NudeDetector; NudeDetector()"

COPY app ./app
COPY config.yaml /config/config.yaml

ENV DATA_DIR=/data MOVIES_DIR=/media/movies TV_DIR=/media/tv CONFIG_PATH=/config/config.yaml PYTHONUNBUFFERED=1
EXPOSE 6091
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-6091}"]
