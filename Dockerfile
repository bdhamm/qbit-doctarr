FROM python:3.11-slim

# Install gosu for PUID/PGID privilege dropping, tzdata so TZ env var takes effect
RUN apt-get update && apt-get install -y --no-install-recommends gosu tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Make entrypoint executable
RUN chmod +x /app/docker-entrypoint.sh

# Create config directory
RUN mkdir -p /config

# Expose the port
EXPOSE 5000

# Health check: hit the lightweight /api/health endpoint, which verifies
# the Flask app responds and the scheduler thread is alive without doing
# DB or network work. Uses Python stdlib — no curl/wget in slim image.
# start-period=30s lets waitress boot before failures count.
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3).status==200 else 1)"

# Set entrypoint
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default command
CMD ["python", "run.py"]
