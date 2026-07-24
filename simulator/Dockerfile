from python:3.10-slim

workdir /app

run apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

copy requirements.txt .
run pip install --no-cache-dir -r requirements.txt
copy . .
cmd ["python", "simulator.py"]