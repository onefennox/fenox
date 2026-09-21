# Fenox hub, headless. The client brings adb and the Flutter SDK; this image
# serves the dashboard and API. Persist the data directory with a volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FENOX_DATA_DIR=/data \
    FENOX_HOST=0.0.0.0 \
    FENOX_PORT=8787

WORKDIR /app

COPY pyproject.toml README.md VERSION ./
COPY src ./src
RUN pip install .

VOLUME ["/data"]
EXPOSE 8787

# Bind to all interfaces inside the container; the reverse proxy or the
# user's own network rules decide what is actually reachable.
ENTRYPOINT ["fenox", "serve", "--no-browser", "--host", "0.0.0.0"]
