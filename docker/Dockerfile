# Imagen CPU de HearMe.
#
# Build multietapa: las dependencias se resuelven en una capa aparte para que
# cambiar el código fuente no invalide la instalación de paquetes.

FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Extras incluidos en la imagen. Se dejan como argumento porque el equilibrio
# entre tamaño y funciones depende del despliegue:
#
#   documents   parsers de PDF, EPUB, DOCX… imprescindible
#   tts-piper   voz en 25+ idiomas, ONNX, ligero
#   translate   ctranslate2 + transformers. Unos 200 MB, sin torch
#   tts-kokoro  voz más natural, pero arrastra torch: más de 2 GB
#
# Kokoro queda fuera por defecto a propósito: multiplicar por cinco el tamaño de
# la imagen para todo el mundo, cuando Piper ya cubre los idiomas, no compensa.
# Para incluirlo:
#   docker compose build --build-arg HEARME_EXTRAS=documents,tts-piper,translate,tts-kokoro
ARG HEARME_EXTRAS=documents,tts-piper,translate

# Solo los metadatos primero: esta capa se cachea mientras no cambien las deps.
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    VIRTUAL_ENV=/opt/venv uv pip install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy unsafe-best-match \
        ".[${HEARME_EXTRAS}]"

# Nota sobre torch: el índice de CPU de PyTorch se añade arriba a propósito. La
# rueda por defecto de PyPI arrastra las bibliotecas de CUDA —unos 2,5 GB— que
# un servidor sin acelerador no llega a usar nunca. La de CPU ronda los 200 MB.

COPY src ./src
# Instalación normal, NO editable, y es importante.
#
# `pip install -e` escribe en site-packages un .pth con la ruta absoluta del
# código (/build/src). En la etapa siguiente el código va a /app/src y /build ya
# no existe, así que esa ruta apunta al vacío: `import hearme` falla con
# ModuleNotFoundError, el proceso muere al arrancar y el contenedor se queda
# «unhealthy» sin decir por qué. Una instalación normal copia el paquete dentro
# del venv y el venv es autosuficiente.
#
# No se pierde caché de capas: las dependencias siguen en su capa anterior y
# esta solo reinstala el propio paquete, que es instantáneo.
RUN --mount=type=cache,target=/root/.cache/uv \
    VIRTUAL_ENV=/opt/venv uv pip install --no-deps .


FROM python:3.12-slim AS runtime

# ffmpeg: exportación mp3/m4b. tesseract + ghostscript: OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ocrmypdf \
        tesseract-ocr \
        tesseract-ocr-spa \
        tesseract-ocr-eng \
        ghostscript \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: el contenedor no necesita root para nada.
RUN useradd --create-home --uid 1000 hearme

# Solo el venv: con la instalación no editable, el paquete ya vive dentro. No se
# copia el código aparte para que no haya dos copias que puedan divergir.
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HEARME_DATA_DIR=/data \
    HEARME_API_HOST=0.0.0.0

WORKDIR /app
RUN mkdir -p /data && chown -R hearme:hearme /data /app
USER hearme

VOLUME ["/data"]
EXPOSE 8000

# start-period generoso: el arranque carga los plugins, detecta la capacidad del
# nodo y crea el esquema. Si el healthcheck falla antes de tiempo, compose aborta
# el stack entero y el motivo real queda enterrado.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["hearme", "serve"]
