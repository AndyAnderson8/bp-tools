FROM python:3.14-slim

LABEL org.opencontainers.image.source="https://github.com/AndyAnderson8/bp-tools"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY bp_tools/ ./bp_tools/
RUN python -m pip install --no-cache-dir .

RUN mkdir /config && chown 99:100 /config
USER 99:100
WORKDIR /config

CMD ["python", "-m", "bp_tools", "--config", "/config/config.yaml"]
