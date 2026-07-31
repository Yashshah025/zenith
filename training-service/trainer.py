import os
import redis
import psycopg2
import pandas as pd
from sklearn.model_selection import train_test_split
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
import time
import json

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "zenithride"
DB_USER = "yash"
DB_PASSWORD = "1qaz2wsx"
MODEL_DIR = "/shared-models"
MODEL_PATH = f"{MODEL_DIR}/model.bin"

r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def train_and_save_model():
    print("[TRAINER] Starting training loop...")

    try:
        conn = get_db_connection()
        query = "select * from completed_trips"
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        print(f"[TRAINER] Database error: {e}")
        return None

    if len(df) < 100:
        print(f"[TRAINER] Not enough data to train (only {len(df)} rows). Need at least 100.")
        return None
    print(f"[TRAINER] Loaded {len(df)} records for training.")

    features = [
        "pickup_latitude", "pickup_longitude", "dropoff_latitude", "dropoff_longitude",
        "passenger_count", "active_rides_last_10m", "avg_speed_last_10m", "demand_supply_ratio"
    ]
    target = "actaul_duration"

    X = df[features].astype(float)
    y = df[target].astype(float)

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    model = xgb.XGBRegressor(
        n_estimators = 100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_val)

    val_mae = mean_absolute_error(y_val, preds)
    print(f"[TRAINER] Model successfully trained! Validation MAE: {val_mae:.2f} seconds.")

    os.makedirs(MODEL_DIR, exist_ok=True)
    version = int(time.time())
    versioned_path = f"{MODEL_DIR}/model_v{version}.bin"

    model.save_model(versioned_path)
    model.save(MODEL_PATH)
    print(f"[TRAINER] Saved models to registry: {versioned_path} and {MODEL_PATH}")

    r.set("baseline_mae", f"{val_mae:.2f}")

    update_event = {
        "model_path": versioned_path,
        "version": f"v{version}",
        "mae": f"{val_mae:.2f}"
    }
    r.publish("model_updates", json.dumps(update_event))
    print(f"[TRAINER] Broadcasted model update event: {update_event}")
    
    return val_mae

def listen_for_drift():
    pubsub = r.pubsub()
    pubsub.subscribe("drift_alerts")
    print("[TRAINER] Subscribed to 'drift_alerts' channel. Waiting for alerts...")

    for message in pubsub.listen():
        if message["type"] == "message":
            alert_data = message["data"]
            print(f"\n [TRAINER] DRIFT ALERT RECEIVED: {alert_data}")
            print("[TRAINER] Initiating automated retraining...")

            new_mae = train_and_save_model()

            if new_mae:
                print(f"[TRAINER] Retraining complete. New validation MAE: {new_mae:.2f}s.")
                r.set("inject_drift", "false")
                print("[TRAINER] Reset 'inject_drift' setting to false. Pipeline is healthy.")

if __name__ == "__main__":
    time.sleep(3)

    if not os.path.exists(MODEL_PATH):
        print("[TRAINER] No baseline model found in registry. Training initial model...")
        train_and_save_model()
    else:
        print(f"[TRAINER] Existing model found at {MODEL_PATH}. Ready to monitor.")

    listen_for_drift()