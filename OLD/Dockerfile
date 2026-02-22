FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY agent/ ./agent/

# Create data directory for contracts
RUN mkdir -p /app/data/contracts

# Set Python path
ENV PYTHONPATH=/app

# Default command - run the main application
CMD ["python", "-m", "src.main"]
