# 🚖 Zenith-ride: End-to-End MLOps Pipeline & Drift Monitoring

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Microservices-2496ED.svg)
![Redis](https://img.shields.io/badge/Redis-Streams%20%7C%20PubSub-DC382D.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-336791.svg)
![XGBoost](https://img.shields.io/badge/XGBoost-Machine%20Learning-F37626.svg)
![Flask](https://img.shields.io/badge/Flask-API%20Gateway-000000.svg)

## 📌 Overview
Zenith-ride is a production-grade, distributed MLOps system built to predict Estimated Time of Arrival (ETA) for ride-sharing or delivery services. 

It tackles one of the most critical challenges in Machine Learning: **Model Degradation in Production**. Instead of taking the server offline to deploy new models, Zenith-ride uses a decoupled microservice architecture to simulate real-time streaming data, automatically detect model drift, and trigger a closed-loop retraining cycle with **zero-downtime in-memory hot-swapping**.

## 🏗️ System Architecture

The project consists of 5 loosely coupled microservices managed via docker-compose:

1. **Gateway Service (Flask API):** The entry point. Handles JWT Authentication, rate limiting, and routes ETA requests into a Redis Stream queue.
2. **Inference Worker:** Pulls data from Redis Streams via Consumer Groups, runs ETA predictions using an in-memory XGBoost model, and writes results to PostgreSQL. 
3. **Drift Monitor:** Continuously compares predicted ETAs against actual trip durations. Calculates a rolling Mean Absolute Error (MAE) over the last 100 trips. If the error spikes by 25%, it triggers an alert.
4. **Training Service:** Listens for drift alerts, fetches the latest ground-truth data from PostgreSQL, retrains the XGBoost model, saves it to a shared volume, and broadcasts a deployment signal.
5. **Simulator:** Acts as the "real world," generating concurrent trip requests and actual completion times to simulate traffic and concept drift.

## ✨ Key Features

* **Zero-Downtime Hot-Swapping:** Workers listen to a Redis Pub/Sub channel. When a new model is trained, they dynamically load the new .bin weights into RAM without dropping a single pending request.
* **Automated Drift Detection:** Continuous evaluation of live predictions against ground truth to trigger autonomous retraining.
* **High-Throughput Stream Processing:** Uses Redis Streams and Consumer Groups to allow infinite horizontal scaling of Inference Workers based on load.
* **Chaos Engineering:** Workers include a "Chaos Listener" that accepts poison-pill signals to intentionally crash containers, validating fault tolerance and task reassignment.
* **Secure API Gateway:** Implements JWT-based authentication, token blacklisting, and rate limiting to prevent API abuse.

## 🚀 Getting Started

### Prerequisites
* Docker
* Docker Compose

### Installation & Execution

1. Clone the repository and navigate to the project directory:
   `ash
   cd Zenith-ride
   `

2. Build and spin up the microservices:
   `ash
   docker-compose up --build -d
   `

3. Verify all containers (Redis, Postgres + 4 Python services) are running:
   `ash
   docker-compose ps
   `

## 📡 API Endpoints & Swagger Docs

The API Gateway runs on port 5000. It includes an interactive Swagger UI for testing routes.

* **Swagger UI:** http://localhost:5000/apidocs

### Core Endpoints:
* POST /register: Register a new user.
* POST /login: Receive a JWT Bearer token.
* POST /predict: Submit trip parameters (distance, traffic, time of day) to queue an ETA prediction. (Requires JWT auth)
* POST /logout: Blacklist the current JWT.

## 📂 Project Structure

`	ext
Zenith-ride/
│
├── gateway-service/      # Flask API, JWT Auth, Swagger docs
├── inference-worker/     # XGBoost prediction engine & hot-swapper
├── drift-monitor/        # Rolling MAE calculator & alert trigger
├── training-service/     # Model retraining and Pub/Sub broadcaster
├── simulator/            # Data generator simulating concept drift
├── tests/                # Pytest suites for ML pipeline validation
├── docker-compose.yml    # Container orchestration
└── test_ml_pipeline.py   # Unit testing script
`

## 🛠️ Built With
* **Python 3.9+**
* **XGBoost:** For fast, CPU-efficient tabular regression.
* **Redis:** Used as a Message Broker (Pub/Sub & Streams) and for JWT Blacklisting/Rate Limiting.
* **PostgreSQL:** Persistent storage for trip logs and training data.
* **Flask & Flasgger:** RESTful API and documentation.
* **Docker:** Containerization and shared volume mounts.

## 🤝 Contribution
Feel free to fork this repository, submit pull requests, or open issues to improve the MLOps pipeline!
