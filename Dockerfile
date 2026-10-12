FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
COPY requirements-whisperx.txt /tmp/requirements-whisperx.txt
COPY requirements-ml.txt /tmp/requirements-ml.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio
RUN pip install --no-cache-dir -r /tmp/requirements-whisperx.txt
RUN pip install --no-cache-dir -r /tmp/requirements-ml.txt

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app

COPY --chown=app:app . /app

ENV PORT=7860 \
    HOME=/home/app \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache
EXPOSE 7860

USER app

CMD ["python", "app.py"]
