# ============================================================================
# Dockerfile — RUHI JI BOT
# Production Ready | Render Compatible | Lightweight
# ============================================================================

# Python 3.11 slim image use karo (lightweight + fast)
FROM python:3.11-slim

# Metadata
LABEL maintainer="@RUHI_VIG_QNR"
LABEL description="Ruhi Ji - Advanced AI Telegram Bot"
LABEL version="3.0.0"

# System dependencies install karo
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Working directory set karo
WORKDIR /app

# Requirements file copy karo pehle (Docker cache ke liye)
COPY requirements.txt .

# Python dependencies install karo
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pura code copy karo
COPY . .

# Data folder banao (SQLite database ke liye)
RUN mkdir -p /app/data

# Non-root user banao (security ke liye)
RUN useradd -m -r botuser && \
    chown -R botuser:botuser /app
USER botuser

# Environment variables (defaults - Render pe override hoga)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000 \
    BOT_TOKEN="" \
    ADMIN_ID="0" \
    DATABASE_URL="sqlite:///data/ruhi_bot.db"

# Port expose karo
EXPOSE ${PORT}

# Health check (Render + Docker ke liye)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Bot start karo
CMD ["python", "main.py"]
