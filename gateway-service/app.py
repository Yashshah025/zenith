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
            'exp': datetime.datetime.now() + datetime.timedelta(minutes=15)
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

@app.route('/get_ride_status', methods=['GET'])
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
@token_required
def kill_worker(current_user):
    r.publish("chaos_channel", "shutdown")
    return jsonify({'message': 'Chaos event triggered: Shutdown signal sent to a worker.'}), 200

@app.route('/chaos/inject-drift', methods=['POST'])
@token_required
def inject_drift(current_user):
    data = request.get_json() or {}
    enable = data.get('enable', True)

    r.set("inject_drift", "true" if enable else "false")
    
    return jsonify({
        'message': f"Drift injection {'enabled' if enable else 'disabled'}.",
        'inject_drift': r.get("inject_drift")
    }), 200




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug = True)