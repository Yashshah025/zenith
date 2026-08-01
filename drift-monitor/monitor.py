import os
import redis
import time
from collections import deque
import numpy as np
import json


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = 6379
COMPLETIONS_STREAM = "trip_completions"
GROUP_NAME = "drift_monitor_group"
CONSUMER_NAME = "drift_monitor_01"

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def init_consumer_group():
    try:
        groups = r.xinfo_groups(COMPLETIONS_STREAM)
        group_exists = any(g['name'] == GROUP_NAME for g in groups)
    except redis.exceptions.ResponseError: 
        group_exists = False

    if not group_exists:
        try:
            r.xgroup_create(COMPLETIONS_STREAM, GROUP_NAME, id="$", mkstream=True)
            print(f"[MONITOR] Created consumer group '{GROUP_NAME}' on '{COMPLETIONS_STREAM}'")
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise e

error_window = deque(maxlen=100)
total_trips_processed = 0

def get_prediction_result(job_id):
    for _ in range(3):
        result = r.hgetall(f"job:{job_id}:result")
        if result:
            return result
        time.sleep(0.1)  # Sleep 100ms
    return None

def process_trip_completion(job_id, actual_duration):
    global total_trips_processed

    result = get_prediction_result(job_id)
    if not result:
        print(f"[MONITOR] Warning: No prediction found for Job {job_id}. Skipping.")
        return None

    predicted_eta = float(result.get("eta_seconds", 0))
    absolute_error = abs(predicted_eta - actual_duration)

    error_window.append(absolute_error)
    total_trips_processed += 1

    rolling_mae = np.mean(error_window)
    return rolling_mae

def main():
    init_consumer_group()
    print("[MONITOR] Drift Monitor is ready and listening for completions...")

    alert_active = False
    while True:
        try:
            response = r.xreadgroup(
                    groupname=GROUP_NAME,
                    consumername=CONSUMER_NAME,
                    streams={COMPLETIONS_STREAM: ">"}, # ">" means: "Read only new completions that have never been delivered to anyone else"
                    count=5,
                    block=100
                )
            if not response:
                continue
            messages = response[0][1]
            for message_id, payload in messages:
                job_id = payload.get("job_id")
                actual_duration = float(payload.get("actual_duration", 0))

                rolling_mae = process_trip_completion(job_id, actual_duration)

                if rolling_mae is None:
                    r.xack(COMPLETIONS_STREAM, GROUP_NAME, message_id)
                    continue


                baseline_mae_str = r.get("baseline_mae")
                baseline_mae = float(baseline_mae_str) if baseline_mae_str else 30.0

                drift_threshold = baseline_mae *1.25
                drift_detected = rolling_mae > drift_threshold

                if drift_detected and not alert_active:
                    print(f"\n [MONITOR] DRIFT ALERT! Rolling MAE ({rolling_mae:.2f}s) crossed threshold ({drift_threshold:.2f}s)!")
                    alert_payload = {
                        "rolling_mae": f"{rolling_mae:.2f}",
                        "baseline_mae": f"{baseline_mae:.2f}",
                        "timestamp": str(time.time())
                    }
                    r.publish("drift_alerts", json.dumps(alert_payload))
                    r.set("drift_detected", "true")
                    alert_active = True

                elif not drift_detected:
                    r.set("drift_detected", "false")
                    alert_active = False

                r.hset("metrics:drift", mapping={
                    "rolling_mae": f"{rolling_mae:.2f}",
                    "baseline_mae": f"{baseline_mae:.2f}",
                    "drift_detected": "true" if drift_detected else "false",
                    "total_trips_monitored": str(total_trips_processed)
                })

                r.xack(COMPLETIONS_STREAM, GROUP_NAME, message_id)
            time.sleep(0.01)    
        except Exception as e:
            print(f"Error in main monitor loop: {e}")
            time.sleep(2)

if __name__ == "__main__":
    time.sleep(3) # waiting for redis to fully boot up
    main()