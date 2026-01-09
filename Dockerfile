FROM python:3.12-slim

WORKDIR /app

# Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
RUN mkdir -p data/temp

CMD ["python", "-m", "src.main"]
