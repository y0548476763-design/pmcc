FROM python:3.10-slim

WORKDIR /app

# Copy dependencies first for Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Entry point for the Cloud Run Job
CMD ["python", "headless_main.py"]
