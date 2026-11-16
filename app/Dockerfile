FROM python:3.13-slim

# Debian security fix that is newer than the base image
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# Install the app's dependencies, then remove pip and setuptools: the running app never needs
# them, and pip vendors its own (older) urllib3, certifi and msgpack that scanners flag.
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y pip setuptools

# Run as an unprivileged user that owns only the data directory
RUN useradd --create-home --uid 10001 shop && mkdir -p /app/instance && chown shop:shop /app/instance
COPY shop/ shop/
USER shop

# Render sets PORT; 8000 locally
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)"]
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --access-logfile - 'shop:create_app()'"]
