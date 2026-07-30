import pytest
import requests
import time

BASE_URL = "http://localhost:5000"
username = f"yash_user_{int(time.time())}"
password = "secure+password_123"

session_tokens = {}

def test_register():
    payload = {"username": username, "password":password}
    response = requests.post(f"{BASE_URL}/register", json = payload)
    assert response.status_code == 201
    assert response.json()["message"] == "User registered successfully!"

def test_login():
    payload = {"username": username, "password":password}
    response = requests.post(f"{BASE_URL}/login", json = payload)
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

    session_tokens["access_token"] = data["access_token"]
    session_tokens["refresh_token"] = data["refresh_token"]

def test_request_ride_authenticated():
    assert "access_token" in session_tokens
    headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
    payload = {
        "pickup_latitude": 40.7128,
        "pickup_longitude": -74.0060,
        "dropoff_latitude": 40.7589,
        "dropoff_longitude": -73.9851,
        "passenger_count": 2
    }

def test_request_ride_authenticated():
    assert "access_token" in session_tokens
    headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
    payload = {
        "pickup_latitude": 40.7128,
        "pickup_longitude": -74.0060,
        "dropoff_latitude": 40.7589,
        "dropoff_longitude": -73.9851,
        "passenger_count": 2
    }
    response = requests.post(f"{BASE_URL}/request-ride", json=payload, headers=headers)
    assert response.status_code == 202
    
    data = response.json()
    assert "job_id" in data
    assert "status_url" in data
    session_tokens["job_id"] = data["job_id"]

def test_ride_status():
    assert "job_id" in session_tokens
    response = requests.get(f"{BASE_URL}/ride-status/{session_tokens['job_id']}")
    assert response.status_code == 200
    assert response.json()["status"] in ["pending", "completed"]

def test_rate_limiting():
    assert "access_token" in session_tokens
    headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
    payload = {
        "pickup_latitude": 40.7128,
        "pickup_longitude": -74.0060,
        "dropoff_latitude": 40.7589,
        "dropoff_longitude": -73.9851
    }
    
    limit_hit = False
    for _ in range(10):
        response = requests.post(f"{BASE_URL}/request-ride", json=payload, headers=headers)
        if response.status_code == 429:
            limit_hit = True
            break
            
    assert limit_hit is True

def test_token_refresh():
    assert "refresh_token" in session_tokens
    payload = {"refresh_token": session_tokens["refresh_token"]}
    response = requests.post(f"{BASE_URL}/refresh", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    
    session_tokens["new_access_token"] = data["access_token"]
    session_tokens["new_refresh_token"] = data["refresh_token"]

def test_logout():
    assert "new_access_token" in session_tokens
    headers = {"Authorization": f"Bearer {session_tokens['new_access_token']}"}
    response = requests.post(f"{BASE_URL}/logout", headers=headers)
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully!"

def test_revoked_token_fails():
    assert "new_access_token" in session_tokens
    headers = {"Authorization": f"Bearer {session_tokens['new_access_token']}"}
    payload = {
        "pickup_latitude": 40.7128,
        "pickup_longitude": -74.0060,
        "dropoff_latitude": 40.7589,
        "dropoff_longitude": -73.9851
    }
    response = requests.post(f"{BASE_URL}/request-ride", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json()["message"] == "Token has been revoked/logged out!"

