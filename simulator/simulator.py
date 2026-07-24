import redis
import os
import random
import time
import uuid
import math
import threading
import psycopg2

def get_db_connection():
    return psycopg2.connect(
        host = DB_HOST,
        database="zenithride",
        user = "yash",
        password = "1qaz2wsx"
    )

REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
DB_HOST = os.getenv("DB_HOST", "localhost")

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses = True)

try:
    r.ping()
    print("Connected to Redis Successfully")
except Exception as e:
    print(f"Failed to Connect: {e}")

def initialize_feature_store():
    pipe = r.pipeline()
    for zone_id in range(1, 264):
        key = f"zone:{zone_id}:features"
        pipe.hset(key, mapping={
            "active_rides_last_10m": str(random.randint(5, 30)),
            "avg_speed_last_10m": f"{random.uniform(12.0, 22.0):.2f}",
            "demand_supply_ratio": f"{random.uniform(0.9, 1.5):.2f}"
        })
    pipe.execute()

def start_simulation():
    while True:
        time.sleep(0.5)
        job_id = str(uuid.uuid4())
        pickup_zone = random.randint(1, 263)
        dropoff_zone = random.randint(1, 263)

        pickup_lat = random.uniform(40.70, 40.85)
        pickup_lon = random.uniform(-74.02, -73.93)
        dropoff_lat = random.uniform(40.70, 40.85)
        dropoff_lon = random.uniform(-74.02, -73.93)

        distance_miles = (abs(pickup_lat - dropoff_lat) + abs(pickup_lon - dropoff_lon)) * 69.0

        features = r.hgetall(f"zone:{pickup_zone}:features")
        active_rides = int(features.get("active_rides_last_10m", 10))
        avg_speed = float(features.get("avg_speed_last_10m", 15.0))
        ratio = float(features.get("demand_supply_ratio", 1.0))

        r.hincrby(f"zone:{pickup_zone}:features", "active_rides_last_10m", 1)

        base_duration = (distance_miles / avg_speed) * 3600
        actual_duration = base_duration / 60.0

        inject_drift = r.get("inject_drift") == "true"
        if inject_drift:
            actual_duration *= 1.8

        predicted_duration = base_duration / 60.0 
        payload = {
            "job_id": job_id,
            "pickup_zone": str(pickup_zone),
            "dropoff_zone": str(dropoff_zone),
            "pickup_latitude": str(pickup_lat),
            "pickup_longitude": str(pickup_lon),
            "dropoff_latitude": str(dropoff_lat),
            "dropoff_longitude": str(dropoff_lon),
            "passenger_count": str(random.randint(1, 4)),
            "active_rides_last_10m": str(active_rides),
            "avg_speed_last_10m": str(avg_speed),
            "demand_supply_ratio": str(ratio),
            "predicted_duration": str(predicted_duration)
        }

        print(f"[NEW_RIDE] Job: {job_id} | Dist: {distance_miles:.2f}mi | active_rides: {active_rides}")
        r.xadd("eta_requests", payload)
        threading.Thread(target=complete_trip, args=(job_id, payload, actual_duration)).start()

def complete_trip(job_id, payload, actual_duration):
    time.sleep(actual_duration)
    pickup_zone = payload["pickup_zone"]

    r.hincrby(f"zone:{pickup_zone}:features", "active_rides_last_10m", -1)

    r.xadd("trip_completions", 
        {"job_id": job_id,
        "actual_duration": str(actual_duration)
    })

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = """
                INSERT INTO completed_trips (
                job_id, pickup_latitude, pickup_longitude, dropoff_latitude, dropoff_longitude,
                passenger_count, active_rides_last_10m, avg_speed_last_10m, demand_supply_ratio,
                predicted_duration, actual_duration
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        predicted_duration = payload.get("predicted_duration", actual_duration)

        cur.execute(query, (
            job_id, 
            payload["pickup_latitude"], payload["pickup_longitude"],
            payload["dropoff_latitude"], payload["dropoff_longitude"],
            int(payload.get("passenger_count", 1)), 
            int(payload.get("active_rides_last_10m", 10)),
            float(payload.get("avg_speed_last_10m", 15.0)),
            float(payload.get("demand_supply_ratio", 1.0)),
            predicted_duration,
            actual_duration
        ))

        conn.commit()
        cur.close()
        conn.close()
        print(f"[TRIP COMPLETE] Job: {job_id} | Saved to DB.")

    except Exception as e:
        print(f"Error logging trip to db: {e}")    




if __name__ == "__main__":
    # 1. Populate the Redis Feature Store on startup
    initialize_feature_store()
    
    # 2. Start the infinite loop generating ride requests
    start_simulation()

