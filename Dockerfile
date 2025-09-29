FROM python:3.12-slim

WORKDIR /app

# Install build dependencies for compiling packages like chroma-hnswlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}

