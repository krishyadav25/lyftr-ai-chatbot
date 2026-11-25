# ==============================================================================
# Stage 1: Builder - Install Python dependencies into an isolated venv
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==============================================================================
# Stage 2: Runtime - Minimal image with only the venv and application code
# ==============================================================================
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create persistent SQLite mount directory
RUN mkdir -p /data && chmod 777 /data

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
