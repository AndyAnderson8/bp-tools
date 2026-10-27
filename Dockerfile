FROM python:3.14-slim

LABEL org.opencontainers.image.source="https://github.com/AndyAnderson8/bp-tools" \
      net.unraid.docker.icon="https://raw.githubusercontent.com/AndyAnderson8/bp-tools/dev/assets/logo.png?v=20261024-2"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY bp_tools/ ./bp_tools/
RUN python -m pip install --no-cache-dir .

RUN mkdir /config && chown 99:100 /config
# Give UID 99 a passwd entry so tools like bash show a name instead of
# "I have no name!" when the container is opened in a console.
RUN echo "bp-tools:x:99:100::/config:/bin/bash" >> /etc/passwd
USER 99:100
# Keep Python's import path on the code baked into the image. The mounted
# /config directory may contain an old checkout from previous deployments.
WORKDIR /app

CMD ["python", "-m", "bp_tools", "--config", "/config/config.yaml"]
