import os
import uuid
import redis
import sys
import threading
import time
import json
import pandas as pd
import xgboost as xgb

# Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = 6379
STREAM_NAME = "eta_requests"
GROUP_NAME = "eta_worker_group"
WORKER_NAME = f"worker_{uuid.uuid4().hex[:8]}"

# Global model pointers
active_model = None
model_version = "v0_baseline_mock"

print(f"Starting {WORKER_NAME}...")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# 1. Initialize Redis Consumer Group
def init_consumer_group():
    try:
        groups = r.xinfo_groups(STREAM_NAME)
        group_exists = any(g['name'] == GROUP_NAME for g in groups)
    except redis.exceptions.ResponseError:
        group_exists = False

    if not group_exists:
        try:
            r.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
            print(f"Created consumer group '{GROUP_NAME}' on stream '{STREAM_NAME}'")
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise e

# 2. Chaos Listener: Listen for simulated container crashes
def listen_for_chaos():
    pubsub = r.pubsub()
    pubsub.subscribe("chaos_channel")
    print(f"[{WORKER_NAME}] Listening for chaos events...")

    for message in pubsub.listen():
        if message["type"] == 'message' and message["data"] == 'shutdown':
            print(f"\n💥 CHAOS RECEIVED: Poison Pill. Worker {WORKER_NAME} is shutting down immediately!")
            sys.exit(0)

# 3. Model Loader Helper
def load_active_model(path):
    global active_model, model_version
    try:
        if os.path.exists(path):
            model_instance = xgb.XGBRegressor()
            model_instance.load_model(path)
            active_model = model_instance
            # Extract version from filename or use a timestamp
            model_version = os.path.basename(path).replace(".bin", "")
            print(f"[WORKER] Successfully loaded model from {path} (version: {model_version})")
            return True
    except Exception as e:
        print(f"[WORKER] Error loading model: {e}")
    return False

# 4. Model Hot-Swapping Listener
def listen_for_model_updates():
    global active_model, model_version
    pubsub = r.pubsub()
    pubsub.subscribe("model_updates")
    print(f"[{WORKER_NAME}] Listening for model update alerts...")

    for message in pubsub.listen():
        if message["type"] == 'message':
            try:
                event_data = json.loads(message['data'])
                new_path = event_data.get("model_path")
                version = event_data.get("version")
                print(f"\n🔄 [{WORKER_NAME}] NEW MODEL DETECTED: {version}. Hot-swapping weights...")

                new_model = xgb.XGBRegressor()
                new_model.load_model(new_path)

                active_model = new_model
                model_version = version
                print(f"[{WORKER_NAME}] Hot-swap successful! Running on version {version}.")
            except Exception as e:
                print(f"[{WORKER_NAME}] Error hot-swapping model weights: {e}")

# 5. ML & Fallback Predictor
def predict_eta_batch(batch_payloads):
    global active_model
    
    # FALLBACK: If no ML model is loaded, run the math formula
    if active_model is None:
        predictions = []
        for payload in batch_payloads:
            pickup_lat = float(payload["pickup_latitude"])
            pickup_lon = float(payload["pickup_longitude"])
            dropoff_lat = float(payload["dropoff_latitude"])
            dropoff_lon = float(payload["dropoff_longitude"])
            
            active_rides = int(payload.get("active_rides_last_10m", 10))
            avg_speed = float(payload.get("avg_speed_last_10m", 15.0))
            ratio = float(payload.get("demand_supply_ratio", 1.0))

            distance_miles = (abs(pickup_lat - dropoff_lat) + abs(pickup_lon - dropoff_lon)) * 69.0
            duration_seconds = (distance_miles / avg_speed) * 3600
            duration_seconds *= (1.0 + (active_rides * 0.02))
            duration_seconds *= ratio

            prediction = max(3.0, min(duration_seconds / 60.0, 45.0))
            predictions.append(prediction)
        return predictions

    # ACTIVE PATH: Predict using XGBoost on the Pandas DataFrame
    features = [
        "pickup_latitude", "pickup_longitude", "dropoff_latitude", "dropoff_longitude",
        "passenger_count", "active_rides_last_10m", "avg_speed_last_10m", "demand_supply_ratio"
    ]
    try:
        df = pd.DataFrame(batch_payloads)
        X = df[features].astype(float)
        predictions = active_model.predict(X)
        return list(predictions)
    except Exception as e:
        print(f"[WORKER] ML prediction failed: {e}. Falling back to math.")
        # Fallback math loop
        fallback_predictions = []
        for payload in batch_payloads:
            pickup_lat = float(payload["pickup_latitude"])
            pickup_lon = float(payload["pickup_longitude"])
            dropoff_lat = float(payload["dropoff_latitude"])
            dropoff_lon = float(payload["dropoff_longitude"])
            active_rides = int(payload.get("active_rides_last_10m", 10))
            avg_speed = float(payload.get("avg_speed_last_10m", 15.0))
            ratio = float(payload.get("demand_supply_ratio", 1.0))
            distance_miles = (abs(pickup_lat - dropoff_lat) + abs(pickup_lon - dropoff_lon)) * 69.0
            duration_seconds = (distance_miles / avg_speed) * 3600
            duration_seconds *= (1.0 + (active_rides * 0.02))
            duration_seconds *= ratio
            prediction = max(3.0, min(duration_seconds / 60.0, 45.0))
            fallback_predictions.append(prediction)
        return fallback_predictions

# 6. Batch Processing & Acknowledgment
def process_batch(batch):
    if not batch:
        return
    message_ids = [item[0] for item in batch]
    payloads = [item[1] for item in batch]

    print(f"[{WORKER_NAME}] Processing batch of size {len(payloads)}...")

    predicted_etas = predict_eta_batch(payloads)

    for i, payload in enumerate(payloads):
        job_id = payload["job_id"]
        eta = predicted_etas[i]

        r.hset(f"job:{job_id}:result", mapping={
            "eta_seconds": f"{eta:.2f}",
            "timestamp": str(time.time()),
            "model_version": model_version  # Dynamic versioning!
        })
        r.expire(f"job:{job_id}:result", 3600)

        r.xack(STREAM_NAME, GROUP_NAME, message_ids[i])
        
    print(f"[{WORKER_NAME}] Successfully processed and acknowledged {len(payloads)} jobs.")

# 7. Crash Recovery (XAUTOCLAIM) Loop
def claim_abandoned_jobs():
    print(f"[{WORKER_NAME}] Starting crash recovery loop...")
    while True:
        try:
            result = r.xautoclaim(
                name=STREAM_NAME,
                groupname=GROUP_NAME,
                consumername=WORKER_NAME,
                min_idle_time=15000,
                start_id="0-0",
                count=10
            )
            
            claimed_messages = result[1]
            if claimed_messages:
                print(f"\n🚨 [{WORKER_NAME}] Auto-Claimed {len(claimed_messages)} abandoned jobs from a dead worker!")
                process_batch(claimed_messages)
                
        except Exception as e:
            print(f"Error in crash recovery loop: {e}")
            
        time.sleep(10)

# 8. Main execution entry
def main():
    init_consumer_group()
    
    # Try to load existing model.bin on startup
    load_active_model("/shared-models/model.bin")

    # Start Pub/Sub threads
    threading.Thread(target=listen_for_chaos, daemon=True).start()
    threading.Thread(target=listen_for_model_updates, daemon=True).start()
    threading.Thread(target=claim_abandoned_jobs, daemon=True).start()

    print(f"[{WORKER_NAME}] Worker is ready and consuming requests...")

    batch_buffer = []
    last_batch_time = time.time()

    while True:
        try:
            response = r.xreadgroup(
                groupname=GROUP_NAME,
                consumername=WORKER_NAME,
                streams={STREAM_NAME: ">"},
                count=10,
                block=10
            )
            if response:
                messages = response[0][1]
                batch_buffer.extend(messages)
            time_since_last_batch = (time.time() - last_batch_time) * 1000

            if batch_buffer and (len(batch_buffer) >= 10 or time_since_last_batch >= 30):
                process_batch(batch_buffer)
                batch_buffer.clear()
                last_batch_time = time.time()
            time.sleep(0.001)

        except Exception as e:
            print(f"Error in main worker loop: {e}")
            time.sleep(2)
            
if __name__ == "__main__":
    time.sleep(3)
    main()