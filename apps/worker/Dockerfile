FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system dependencies (Tesseract OCR для пайплайна: OCR → нормализация → сегментация)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the worker
CMD ["python", "-m", "worker"]
