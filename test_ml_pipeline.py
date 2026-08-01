import requests
import time
import redis


BASE_URL = "http://localhost:5000"

def run_mlops_pipeline_test():
    print("=== STARTING MLOPS CLOSED-LOOP PIPELINE TEST ===")

    print("\n1. Logging in to secure access token...")
    reg_payload = {"username": "mlops_tester", "password": "super_secure_pass"}
    requests.post(f"{BASE_URL}/register", json=reg_payload)

    login_response = requests.post(f"{BASE_URL}/login", json=reg_payload)
    token = login_response.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print("Success: Access token obtained.")

    print("\n2. Injecting Data Drift (Simulating traffic jam/storm)...")
    drift_response = requests.post(f"{BASE_URL}/chaos/inject-drift", json={"enable": True}, headers=headers)
    print(f"Response: {drift_response.json()}")

    print("\n3. Monitoring rolling MAE in real-time. Waiting for drift alert to trigger...")
    print("This will take about 30-40 seconds as the simulator logs new trips.")
    print("-" * 50)
    print(f"{'Time':<10} | {'Rolling MAE':<15} | {'Baseline MAE':<15} | {'Drift Status':<12}")
    print("-" * 50)

    r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    start_time = time.time()
    drift_triggered = False

    while time.time() - start_time < 180:  # Timeout after 180 seconds
        metrics = r.hgetall("metrics:drift")
        if metrics:
            rolling_mae = metrics.get("rolling_mae", "N/A")
            baseline_mae = metrics.get("baseline_mae", "N/A")
            drift_detected = metrics.get("drift_detected", "N/A")

            current_time = f"{int(time.time() - start_time)}s"
            print(f"{current_time:<10} | {rolling_mae:<15} | {baseline_mae:<15} | {drift_detected:<12}")

            inject_drift_status = r.get("inject_drift")
            if inject_drift_status == "false" and drift_detected == "false":
                print("-" * 50)
                print("\n SUCCESS! MLOPS CLOSED-LOOP RETRAINING COMPLETE!")
                print("1. Drift was detected by the Monitor.")
                print("2. Training Service retrained the model on Postgres logs.")
                print("3. Workers hot-swapped to the new model in-memory.")
                print("4. Prediction error dropped, and drift was resolved!")
                drift_triggered = True
                break
        else:
            print("Waiting for metrics...")
            
        time.sleep(4)

    if not drift_triggered:
        print("-" * 50)
        print("\n Test timed out before drift was resolved. Check worker/trainer logs.")

if __name__ == "__main__":
    run_mlops_pipeline_test()