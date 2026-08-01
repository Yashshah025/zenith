from python:3.10-slim

workdir /app
copy requirements.txt .
run pip install --no-cache-dir -r requirements.txt

copy . .
cmd ["python", "monitor.py"]
