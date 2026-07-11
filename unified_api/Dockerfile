FROM python:3.11-slim@sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3

# Install system dependencies for PDF parsing, OCR, and PostgreSQL
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libpq-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY unified_api/requirements.txt unified_api/requirements.lock ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# Download spaCy model for NER
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY unified_api/ ./unified_api/
COPY src/ ./src/
COPY agent/ ./agent/

# Record the exact checkout in the image. Dokploy builds from its Git checkout,
# so this gives post-deployment verification an immutable target.
COPY .git/HEAD /tmp/onebd-git/HEAD
COPY .git/refs/ /tmp/onebd-git/refs/
RUN head_value="$(cat /tmp/onebd-git/HEAD)" && \
    case "$head_value" in \
      "ref: "*) cat "/tmp/onebd-git/${head_value#ref: }" ;; \
      *) printf '%s\n' "$head_value" ;; \
    esac > /app/BUILD_COMMIT && \
    rm -rf /tmp/onebd-git

# Create storage directory
RUN mkdir -p /app/storage /app/data

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "unified_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
