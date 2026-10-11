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

COPY . /app

ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
