import React, { useState, useEffect, useRef } from 'react';
import './App.css';

export default function App() {
  // --- AUTHENTICATION STATES ---
  const [token, setToken] = useState(localStorage.getItem('zenith_token'));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // --- LIVE METRICS STATES ---
  const [metrics, setMetrics] = useState({
    rolling_mae: '0.00',
    baseline_mae: '0.00',
    drift_detected: 'false',
    queue_size: 0,
    inject_drift: 'false',
    total_trips_monitored: 0
  });

  const [maeHistory, setMaeHistory] = useState([]);

  // --- CANVAS REFERENCES ---
  const chartCanvasRef = useRef(null);
  const mapCanvasRef = useRef(null);
  const animationRef = useRef(null);

  // --- 1. HANDLE LOGIN / REGISTER ---
  const handleLogin = async (e) => {
    e.preventDefault();
    setAuthError('');
    try {
      // First, try to auto-register in case this user is new
      await fetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      const data = await response.json();
      if (response.ok && data.access_token) {
        localStorage.setItem('zenith_token', data.access_token);
        setToken(data.access_token);
      } else {
        setAuthError(data.message || 'Login failed.');
      }
    } catch (err) {
      setAuthError('Cannot connect to API Gateway.');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('zenith_token');
    setToken(null);
    setMaeHistory([]);
  };

  // --- 2. POLL METRICS FROM GATEWAY ---
  useEffect(() => {
    if (!token) return;

    const fetchMetrics = async () => {
      try {
        const response = await fetch('/api/dashboard/metrics', {
          headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.status === 401) {
          handleLogout();
          return;
        }

        const data = await response.json();
        setMetrics(data);

        // Update MAE history list (keep last 35 points)
        setMaeHistory((prev) => {
          const updated = [...prev, parseFloat(data.rolling_mae)];
          if (updated.length > 35) updated.shift();
          return updated;
        });

      } catch (err) {
        console.error('Error polling dashboard metrics:', err);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => clearInterval(interval);
  }, [token]);

  // --- 3. TRIGGER CHAOS ACTIONS ---
  const triggerChaosAction = async (endpoint, payload) => {
    try {
      await fetch(`/api/${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });
    } catch (err) {
      console.error(`Chaos action failed on ${endpoint}:`, err);
    }
  };

  // --- 4. DRAW MAE PERFORMANCE CHART (HTML CANVAS) ---
  useEffect(() => {
    const canvas = chartCanvasRef.current;
    if (!canvas || maeHistory.length === 0) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.offsetWidth;
    const height = canvas.offsetHeight;

    // Support high-DPI displays
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    ctx.clearRect(0, 0, width, height);

    // Layout configuration
    const padding = { top: 20, right: 20, bottom: 30, left: 40 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;

    const maxVal = Math.max(...maeHistory, parseFloat(metrics.baseline_mae) * 1.5, 4.0);
    const minVal = 0;

    const getX = (index) => padding.left + (index / 34) * chartWidth;
    const getY = (val) => padding.top + chartHeight - ((val - minVal) / (maxVal - minVal)) * chartHeight;

    // Draw Grid Lines
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 1; i <= 4; i++) {
      const yVal = minVal + (maxVal - minVal) * (i / 4);
      const y = getY(yVal);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();

      // Draw Grid Labels
      ctx.fillStyle = '#64748b';
      ctx.font = '9px Outfit';
      ctx.fillText(`${yVal.toFixed(1)}s`, 10, y + 3);
    }

    // Draw Baseline MAE Line (Neon Gold)
    const baseMae = parseFloat(metrics.baseline_mae);
    const baseY = getY(baseMae);
    ctx.strokeStyle = '#ffaa00';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padding.left, baseY);
    ctx.lineTo(width - padding.right, baseY);
    ctx.stroke();
    ctx.setLineDash([]); // Reset
    ctx.fillStyle = '#ffaa00';
    ctx.fillText(`Baseline: ${baseMae.toFixed(2)}s`, padding.left + 5, baseY - 5);

    // Draw Rolling MAE Line (Neon Pink/Cyan)
    ctx.strokeStyle = metrics.drift_detected === 'true' ? '#ff0055' : '#00e5ff';
    ctx.lineWidth = 2.5;
    ctx.shadowBlur = 10;
    ctx.shadowColor = metrics.drift_detected === 'true' ? 'rgba(255, 0, 85, 0.5)' : 'rgba(0, 229, 255, 0.5)';

    ctx.beginPath();
    ctx.moveTo(getX(0), getY(maeHistory[0]));
    for (let i = 1; i < maeHistory.length; i++) {
      ctx.lineTo(getX(i), getY(maeHistory[i]));
    }
    ctx.stroke();

    // Reset shadow for subsequent drawings
    ctx.shadowBlur = 0;

  }, [maeHistory, metrics]);

  // --- 5. DRAW NYC REAL-TIME OPERATIONS MAP (ANIMATED HTML CANVAS) ---
  useEffect(() => {
    const canvas = mapCanvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.offsetWidth;
    const height = canvas.offsetHeight;

    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    // Define mock coordinates for major NYC hubs
    const hubs = [
      { id: 1, name: 'Times Sq', x: 80, y: 100 },
      { id: 2, name: 'Wall St', x: 70, y: 220 },
      { id: 3, name: 'JFK Airport', x: 260, y: 240 },
      { id: 4, name: 'LGA Airport', x: 190, y: 80 },
      { id: 5, name: 'Brooklyn Core', x: 140, y: 250 },
      { id: 6, name: 'Central Park', x: 110, y: 50 }
    ];

    // Establish route links
    const links = [
      [0, 1], [0, 3], [0, 5], [1, 4], [2, 3], [3, 4], [1, 2]
    ];

    // Array to hold active moving particles (representing simulated active rides)
    let particles = [];
    const maxParticles = metrics.queue_size > 0 ? 30 : 8;

    const animateMap = () => {
      ctx.clearRect(0, 0, width, height);

      // Draw background grid lines
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.02)';
      ctx.lineWidth = 1;
      for (let i = 0; i < width; i += 20) {
        ctx.beginPath();
        ctx.moveTo(i, 0); ctx.lineTo(i, height);
        ctx.stroke();
      }
      for (let j = 0; j < height; j += 20) {
        ctx.beginPath();
        ctx.moveTo(0, j); ctx.lineTo(width, j);
        ctx.stroke();
      }

      // Draw Route Lines
      ctx.strokeStyle = 'rgba(0, 229, 255, 0.08)';
      ctx.lineWidth = 1.5;
      links.forEach(([fromIdx, toIdx]) => {
        ctx.beginPath();
        ctx.moveTo(hubs[fromIdx].x, hubs[fromIdx].y);
        ctx.lineTo(hubs[toIdx].x, hubs[toIdx].y);
        ctx.stroke();
      });

      // Spawn new particles (ride dots) dynamically based on activity
      if (particles.length < maxParticles && Math.random() < 0.1) {
        const randomLink = links[Math.floor(Math.random() * links.length)];
        const startHub = hubs[randomLink[0]];
        const endHub = hubs[randomLink[1]];
        particles.push({
          x: startHub.x,
          y: startHub.y,
          targetX: endHub.x,
          targetY: endHub.y,
          progress: 0,
          // Speed up the traffic if drift is injected (storm speed!)
          speed: metrics.inject_drift === 'true' ? 0.012 : 0.006
        });
      }

      // Draw and Animate Particles (Active Rides)
      particles.forEach((p, idx) => {
        p.progress += p.speed;
        p.x = p.x + (p.targetX - p.x) * p.progress;
        p.y = p.y + (p.targetY - p.y) * p.progress;

        // Draw ride glow dot
        ctx.fillStyle = metrics.drift_detected === 'true' ? '#ff0055' : '#00e5ff';
        ctx.shadowBlur = 6;
        ctx.shadowColor = ctx.fillStyle;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0; // Reset

        // Remove particle once arrived
        if (p.progress >= 0.98) {
          particles.splice(idx, 1);
        }
      });

      // Draw Hubs (Taxi Zones)
      hubs.forEach((hub) => {
        // Draw glowing core node
        ctx.fillStyle = 'var(--bg-dark)';
        ctx.strokeStyle = 'var(--neon-cyan)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(hub.x, hub.y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Pulsing radar ring
        ctx.strokeStyle = 'rgba(0, 229, 255, 0.15)';
        ctx.beginPath();
        const pulseRadius = 6 + (Date.now() / 150 % 10);
        ctx.arc(hub.x, hub.y, pulseRadius, 0, Math.PI * 2);
        ctx.stroke();

        // Label
        ctx.fillStyle = '#64748b';
        ctx.font = '8px Outfit';
        ctx.fillText(hub.name, hub.x - 20, hub.y - 12);
      });

      animationRef.current = requestAnimationFrame(animateMap);
    };

    animateMap();
    return () => cancelAnimationFrame(animationRef.current);

  }, [metrics]);

  // --- RENDER COMPONENT VIEW ---
  if (!token) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <h2 style={{ textAlign: 'center', marginTop: 0, textTransform: 'uppercase', letterSpacing: '1.5px' }}>
            Zenith<span>Ride</span>
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center', marginBottom: '2rem' }}>
            SECURE Serving Dashboard & MLOps Control
          </p>
          <form onSubmit={handleLogin}>
            <div className="form-group">
              <label>Developer Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label>Access Code</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button className="login-btn" type="submit">Authenticate Session</button>
            {authError && <div className="auth-error">{authError}</div>}
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header>
        <div className="logo-container">
          <div className="logo-icon" />
          <h1>Zenith<span>Ride</span> Ops Center</h1>
        </div>
        <button className="logout-btn" onClick={handleLogout}>Revoke Access</button>
      </header>

      {/* 1. TOP METRICS STRIP */}
      <div className="metrics-grid">
        <div className={`metric-card ${metrics.drift_detected === 'true' ? 'alert' : ''}`}>
          <p className="metric-label">Rolling MAE (Error)</p>
          <p className="metric-value">{parseFloat(metrics.rolling_mae).toFixed(2)}s</p>
          <div className="alert-indicator">
            <div className={`pulse-dot ${metrics.drift_detected === 'true' ? 'pink' : 'green'}`} />
            {metrics.drift_detected === 'true' ? 'DRIFT ALERT' : 'MODEL STABLE'}
          </div>
        </div>

        <div className="metric-card">
          <p className="metric-label">ML Baseline MAE</p>
          <p className="metric-value">{parseFloat(metrics.baseline_mae).toFixed(2)}s</p>
        </div>

        <div className="metric-card">
          <p className="metric-label">In-Flight Queue Size</p>
          <p className="metric-value" style={{ color: metrics.queue_size > 5 ? 'var(--neon-gold)' : 'var(--neon-cyan)' }}>
            {metrics.queue_size} jobs
          </p>
        </div>

        <div className="metric-card">
          <p className="metric-label">Total Logs Monitored</p>
          <p className="metric-value">{metrics.total_trips_monitored}</p>
        </div>
      </div>

      {/* 2. LIVE CHARTS & MAPS */}
      <div className="viz-grid">
        {/* ML Performance Chart */}
        <div className="viz-card">
          <div className="viz-title">
            <span>Model Performance (Rolling vs Baseline)</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>LAST 35 EVENTS</span>
          </div>
          <div className="canvas-container">
            <canvas ref={chartCanvasRef} />
          </div>
        </div>

        {/* Interactive Operations Map */}
        <div className="viz-card">
          <div className="viz-title">Simulated NYC Traffic Map</div>
          <div className="canvas-container">
            <canvas ref={mapCanvasRef} />
          </div>
        </div>
      </div>

      {/* 3. CONTROL PANEL */}
      <div className="viz-card" style={{ marginBottom: '2rem' }}>
        <h3 className="viz-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.8rem' }}>
          Chaos Command Console
        </h3>
        <div className="control-grid">
          {/* Toggle Drift Button */}
          <button
            className={`action-btn ${metrics.inject_drift === 'true' ? 'danger' : 'primary'}`}
            onClick={() => triggerChaosAction('chaos/inject-drift', { enable: metrics.inject_drift !== 'true' })}
          >
            <span>{metrics.inject_drift === 'true' ? '🔴 Disable Drift' : '⚡ Inject Drift'}</span>
            <span className="description">
              {metrics.inject_drift === 'true'
                ? 'Stop storm simulation and restore traffic speeds.'
                : 'Simulate NYC storm (1.8x travel times) to trigger drift.'}
            </span>
          </button>

          {/* Kill Worker Button */}
          <button
            className="action-btn danger"
            onClick={() => triggerChaosAction('chaos/kill-worker', {})}
          >
            <span>💥 Kill Inference Worker</span>
            <span className="description">
              Broadcast poison pill to instantly crash a background worker node.
            </span>
          </button>

          {/* Retrain Model Button */}
          <button
            className="action-btn primary"
            onClick={() => triggerChaosAction('chaos/inject-drift', { enable: true })}
          >
            <span>🔄 Trigger Retrain Loop</span>
            <span className="description">
              Force drift alert to trigger retraining of XGBoost model immediately.
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}