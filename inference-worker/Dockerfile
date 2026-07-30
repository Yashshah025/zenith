from python:3.10-slim

workdir /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 && rm -rf /var/lib/apt/lists/*

copy requirements.txt .
run pip install --no-cache-dir -r requirements.txt

copy . .
cmd ["python", "worker.py"]