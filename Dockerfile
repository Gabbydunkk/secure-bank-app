# =============================================================================
# Dockerfile - Secure Bank Application Backend
# Multi-stage build: minimise attack surface, run as non-root user
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Dependencies (cached layer)
# ---------------------------------------------------------------------------
    FROM python:3.11-slim AS deps

    WORKDIR /app
    
    # Install system dependencies required for psycopg2 and cryptography
    RUN apt-get update && \
        apt-get install -y --no-install-recommends gcc libpq-dev curl && \
        rm -rf /var/lib/apt/lists/*
    
    COPY requirements.txt .
    RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
    
    # ---------------------------------------------------------------------------
    # Stage 2: Runtime (minimal image - CIS Benchmark Compliant)
    # ---------------------------------------------------------------------------
    FROM python:3.11-slim AS runtime
    
    WORKDIR /app
    
    # Install only runtime system dependencies
    RUN apt-get update && \
        apt-get install -y --no-install-recommends libpq5 curl && \
        rm -rf /var/lib/apt/lists/*
    
    # Copy installed Python packages from deps stage
    COPY --from=deps /install /usr/local
    
    # Create non-root user for banking security compliance (No Shell Access)
    RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
    
    # Copy application code
    COPY . .
    
    # Change ownership to non-root user
    RUN chown -R appuser:appuser /app
    
    # Switch to non-root user
    USER appuser
    
    # Expose the application port
    EXPOSE 8000
    
    # Container-level health check (complements ALB health check)
    HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
        CMD curl -f http://localhost:8000/health || exit 1
    
    # Start Command: Auto-Migrate Database (Alembic) THEN start FastAPI
    # Using 'sh -c' allows us to chain commands together.
    CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]