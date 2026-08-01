import os
from flask import Flask, request, jsonify
import datetime
import redis
import jwt
from functools import wraps

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flasgger import Swagger 
import random
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-in-prod'

swagger = Swagger(app)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host = REDIS_HOST, port=6379, decode_responses = True)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=f"redis://{REDIS_HOST}:6379",
    default_limits=["200 per day", "25 per hour"]
)

def is_token_blacklisted(token):
    return r.exists(f"blacklist:{token}")

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        if token.startswith("Bearer "):
            token = token.split(" ")[1]
        if is_token_blacklisted(token):
            return jsonify({'message': 'Token has been revoked/logged out!'}), 401
        
        try: 
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['user']
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Access token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Access token is invalid!'}), 401

        return f(current_user, *args, **kwargs)
    return decorated


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"message": "Username and passoword required"}), 400

    if r.hexists('users', username):
        return jsonify({'message': 'User already exists!'}), 400

    r.hset('users', username, password)
    return jsonify({'message': 'User registered successfully!'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    stored_password = r.hget('users', username)
    if not stored_password or stored_password != password:
        return jsonify({'message': 'Invalid credentials!'}), 401
    
    access_token = jwt.encode(
        {
            'user': username,
            'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        },
        app.config['SECRET_KEY'], algorithm="HS256"
    )

    refresh_token = jwt.encode({
        'user': username,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    r.set(f"refresh_token:{username}", refresh_token)
    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token
    })

@app.route('/refresh', methods=['POST'])
def refresh():
    data = request.get_json()
    refresh_token = data.get('refresh_token')
    
    if not refresh_token:
        return jsonify({'message': 'Refresh token is missing!'}), 400

    try:
        decoded = jwt.decode(refresh_token, app.config['SECRET_KEY'], algorithms=["HS256"])
        username = decoded['user']
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'Refresh token has expired! Please log in again.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Refresh token is invalid!'}), 401

    stored_token = r.get(f"refresh_token:{username}")
    if not stored_token or stored_token != refresh_token:
        r.delete(f"refresh_token:{username}")  # Revoke session
        return jsonify({'message': 'Security Alert: Refresh token reuse detected! All sessions revoked. Please log in again.'}), 401

    new_access_token = jwt.encode({
        'user': username,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
    }, app.config['SECRET_KEY'], algorithm="HS256")
    
    new_refresh_token = jwt.encode({
        'user': username,
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    r.set(f"refresh_token:{username}", new_refresh_token)
    
    return jsonify({
        'access_token': new_access_token,
        'refresh_token': new_refresh_token
    }), 200



@app.route('/logout', methods=['POST'])
@token_required  
def logout(current_user):
    token = request.headers.get('Authorization')
    if token.startswith("Bearer "):
        token = token.split(" ")[1]
        
    try:
        decoded = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"], options={"verify_exp": False})
        exp_time = decoded.get('exp')
        
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        ttl = exp_time - now
        
        if ttl > 0:
            r.setex(f"blacklist:{token}", int(ttl), "true")
            
    except Exception as e:
        return jsonify({'message': f'Error processing token revocation: {e}'}), 400
        
    r.delete(f"refresh_token:{current_user}")
    
    return jsonify({'message': 'Logged out successfully!'}), 200

@app.route('/request-ride', methods=['POST'])
@token_required
@limiter.limit("5 per minute") 
def request_ride(current_user):
    data = request.get_json()
    pickup_lat = data.get('pickup_latitude')
    pickup_lon = data.get('pickup_longitude')
    dropoff_lat = data.get('dropoff_latitude')
    dropoff_lon = data.get('dropoff_longitude')
    passenger_count = data.get('passenger_count', 1)

    if not all([pickup_lat, pickup_lon, dropoff_lat, dropoff_lon]):
        return jsonify({'message': 'Missing coordinates!'}), 400

    pickup_zone = random.randint(1, 263)
    dropoff_zone = random.randint(1, 263)

    features = r.hgetall(f"zone:{pickup_zone}:features")
    if not features:
        # Fallback values if simulator hasn't started yet
        features = {"active_rides_last_10m": "10", "avg_speed_last_10m": "15.0", "demand_supply_ratio": "1.0"}
    job_id = str(uuid.uuid4())

    payload = {
        "job_id": job_id,
        "pickup_zone": str(pickup_zone),
        "dropoff_zone": str(dropoff_zone),
        "pickup_latitude": str(pickup_lat),
        "pickup_longitude": str(pickup_lon),
        "dropoff_latitude": str(dropoff_lat),
        "dropoff_longitude": str(dropoff_lon),
        "passenger_count": str(passenger_count),
        "active_rides_last_10m": features.get("active_rides_last_10m", "10"),
        "avg_speed_last_10m": features.get("avg_speed_last_10m", "15.0"),
        "demand_supply_ratio": features.get("demand_supply_ratio", "1.0"),
        "user": current_user
    }

    r.xadd("eta_requests", payload)
    return jsonify({
        'message': 'Ride request accepted and queued.',
        'job_id': job_id,
        'status_url': f'/ride-status/{job_id}'
    }), 202

@app.route('/ride-status/<job_id>', methods=['GET'])
def get_ride_status(job_id):
    result = r.hgetall(f"job:{job_id}:result")
    if not result:
        return jsonify({'status': 'pending', 'message': 'Prediction is still processing.'}), 200

    return jsonify({
        'status': 'completed',
        'job_id': job_id,
        'predicted_eta_seconds': float(result.get("eta_seconds", 0)),
        'timestamp': result.get("timestamp"),
        'model_version': result.get("model_version", "v1.0")
    }), 200

@app.route('/chaos/kill-worker', methods=['POST'])
@limiter.exempt
@token_required
def kill_worker(current_user):
    import random
    try:
        # 1. Query Redis for all consumers in the worker group
        consumers = r.xinfo_consumers("eta_requests", "eta_worker_group")
        
        # 2. Filter ONLY active workers (idle time < 5 seconds)
        active_consumers = [c for c in consumers if c['idle'] < 5000]
        
        if active_consumers:
            # 3. Pick a random active worker name
            target_worker = random.choice(active_consumers)['name']
            print(f"[GATEWAY] 🎯 Targeting ACTIVE worker for chaos crash: {target_worker}")
            
            # 4. Publish only that worker's name to the chaos channel
            r.publish("chaos_channel", target_worker)
            return jsonify({'message': f"Chaos signal sent to target worker: {target_worker}"}), 200
    except Exception as e:
        print(f"[GATEWAY] Error querying consumers: {e}")
        
    return jsonify({'message': 'No active workers registered in group yet to kill.'}), 200

@app.route('/chaos/inject-drift', methods=['POST'])
@limiter.exempt
@token_required
def inject_drift(current_user):
    data = request.get_json() or {}
    enable = data.get('enable', True)

    r.set("inject_drift", "true" if enable else "false")

    return jsonify({
        'message': f"Drift injection {'enabled' if enable else 'disabled'}.",
        'inject_drift': r.get("inject_drift")
    }), 200

@app.route('/dashboard/metrics', methods=['GET'])
@limiter.exempt
@token_required
def get_dashboard_metrics(current_user):
    drift_metrics = r.hgetall("metrics:drift") or {}

    try:
        queue_size = r.xlen("eta_requests")
    except Exception:
        queue_size = 0

    inject_drift_status = r.get("inject_drift") or "false"

    return jsonify({
        "rolling_mae": drift_metrics.get("rolling_mae", "0.00"),
        "baseline_mae": drift_metrics.get("baseline_mae", "0.00"),
        "drift_detected": drift_metrics.get("drift_detected", "false"),
        "total_trips_monitored": drift_metrics.get("total_trips_monitored", "0"),
        "queue_size": queue_size,
        "inject_drift": inject_drift_status
    }), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug = True)