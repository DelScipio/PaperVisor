# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (keep minimal; add more only if needed for wheels)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
    \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . ./

# Defaults for container runtime
ENV PAPERVISOR_HOST=0.0.0.0 \
    PAPERVISOR_PORT=8080 \
    PAPERVISOR_RELOAD=0

EXPOSE 8080

# Optional migrations + start
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "main.py"]
