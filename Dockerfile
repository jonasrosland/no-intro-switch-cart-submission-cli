# Batch No-Intro Switch cart submission XML generator (no_intro_switch_cart_submission_cli).
#
# Build (linux/amd64 — release zip is ubuntu_x86_64):
#   docker build -t no-intro-switch-cart-submission-cli .
#
# Run from your working folder (contains dumps, prod.keys, config):
#   docker run --rm -v "$PWD:/data" no-intro-switch-cart-submission-cli \
#     --config /data/no_intro_submit.json \
#     --root "/data/Cyber Shadow"
#
# Config: mount a folder that contains no_intro_submit.json, prod.keys, and dumps — see README (Docker).

FROM python:3.12-slim-bookworm

ARG NSTOOL_VERSION=1.9.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget unzip tesseract-ocr \
    && wget -q "https://github.com/jakcron/nstool/releases/download/v${NSTOOL_VERSION}/nstool-v${NSTOOL_VERSION}-ubuntu_x86_64.zip" -O /tmp/nstool.zip \
    && unzip -q /tmp/nstool.zip -d /tmp/nstool-extract \
    && install -m755 /tmp/nstool-extract/nstool /opt/nstool \
    && rm -rf /tmp/nstool.zip /tmp/nstool-extract \
    && apt-get purge -y --auto-remove wget unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY no_intro_switch_cart_submission_cli/ ./no_intro_switch_cart_submission_cli/
COPY no_intro_batch_submit.py .

COPY no_intro_submit.example.json /app/no_intro_submit.example.json

WORKDIR /data

ENTRYPOINT ["python3", "/app/no_intro_batch_submit.py"]
CMD ["--help"]
