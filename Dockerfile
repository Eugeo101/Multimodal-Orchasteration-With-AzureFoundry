# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Ahmed-Agent Service
# ─────────────────────────────────────────────────────────────────────────────
# Build:  docker build -t ahmed-agent .
# Run:    docker run -p 8000:8000 --env-file .env ahmed-agent
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# ffmpeg is required by pydub for audio playback/conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create output directories (exist_ok equivalent)
RUN mkdir -p output/Audios output/Images assets

# Expose port
EXPOSE 8000

# Start FastAPI with uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
