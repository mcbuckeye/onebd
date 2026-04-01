FROM python:3.11-slim

# Install system dependencies for PDF parsing, OCR, and PostgreSQL
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libpq-dev \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY unified_api/requirements.txt ./requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Download spaCy model for NER
RUN python -m spacy download en_core_web_sm

# Copy application code
COPY unified_api/ ./unified_api/
COPY src/ ./src/
COPY agent/ ./agent/

# Create storage directory
RUN mkdir -p /app/storage /app/data

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "unified_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
