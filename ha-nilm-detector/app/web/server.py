"""Simple embedded web server for NILM live status and statistics."""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _html_page() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>HA NILM Statistics</title>
  <style>
    :root {
      --bg: #f3f4f6;
      --card: #ffffff;
      --ink: #101828;
      --muted: #667085;
      --line: #d0d5dd;
      --accent: #006d77;
      --accent-soft: #e6f6f8;
    }
    body {
      margin: 0;
      font-family: \"Segoe UI\", \"Helvetica Neue\", sans-serif;
      background: radial-gradient(circle at 20% 20%, #edf8ff 0%, var(--bg) 45%, #eef2f7 100%);
      color: var(--ink);
    }
    .wrap {
      max-width: 1080px;
      margin: 24px auto;
      padding: 0 16px 24px;
    }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 16px;
    }
    .head h1 {
      margin: 0;
      font-size: 1.5rem;
      letter-spacing: 0.02em;
    }
    .muted { color: var(--muted); font-size: 0.9rem; }
    .grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      margin-bottom: 12px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      box-shadow: 0 1px 2px rgba(16,24,40,0.06);
    }
    .label { font-size: 0.82rem; color: var(--muted); margin-bottom: 4px; }
    .value { font-size: 1.2rem; font-weight: 600; }
    .chart-wrap {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px;
      margin-bottom: 12px;
    }
    canvas { width: 100%; height: 280px; display: block; }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      margin-bottom: 12px;
    }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-size: 0.92rem;
    }
    thead th { background: var(--accent-soft); }
    tbody tr:last-child td { border-bottom: 0; }
    button {
      border: 1px solid var(--accent);
      background: #fff;
      color: var(--accent);
      border-radius: 8px;
      padding: 4px 8px;
      cursor: pointer;
    }
    @media (max-width: 700px) {
      .head { flex-direction: column; align-items: flex-start; }
      canvas { height: 220px; }
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"head\">
      <h1>HA NILM Live-Statistik</h1>
      <div id=\"ts\" class=\"muted\">Lädt...</div>
    </div>
    <div style=\"margin-bottom: 12px;\">
      <button id=\"runLearningBtn\" title=\"Lernlauf sofort starten\">Lernen jetzt ausführen</button>
      <button id=\"flushDbBtn\" title=\"Nur für Debugging\">DB leeren (Debug)</button>
    </div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Gesamtleistung</div><div id=\"current_power\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL1\" style=\"display:none;\"><div class=\"label\">Phase L1</div><div id=\"power_l1\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL2\" style=\"display:none;\"><div class=\"label\">Phase L2</div><div id=\"power_l2\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL3\" style=\"display:none;\"><div class=\"label\">Phase L3</div><div id=\"power_l3\" class=\"value\">-</div></div>
    </div>

    <div class=\"grid\">
      <div class=\"card\"><div class=\"label\">Durchschnitt (24h)</div><div id=\"avg_power\" class=\"value\">-</div></div>
      <div class=\"card\"><div class=\"label\">Spitze (24h)</div><div id=\"peak_power\" class=\"value\">-</div></div>
      <div class=\"card\"><div class=\"label\">Messwerte (24h)</div><div id=\"reading_count\" class=\"value\">-</div></div>
    </div>

    <div class=\"chart-wrap\">
      <canvas id=\"powerChart\" width=\"1000\" height=\"280\"></canvas>
    </div>

    <h2 style=\"margin:14px 0 8px; font-size:1.1rem;\">Erkannte Geräte</h2>
    <table>
      <thead>
        <tr><th>Gerät</th><th>Status</th><th>Leistung (W)</th><th>Konfidenz</th><th>Zyklen</th><th>Laufzeit (s)</th></tr>
      </thead>
      <tbody id=\"deviceRows\"></tbody>
    </table>

    <h2 style=\"margin:14px 0 8px; font-size:1.1rem;\">Gelernte Muster</h2>
    <table>
      <thead>
        <tr><th>ID</th><th>Typ</th><th>Label</th><th>Phasen</th><th>Ø (W)</th><th>Spitze (W)</th><th>Dauer (s)</th><th>Anzahl</th><th>Aktion</th></tr>
      </thead>
      <tbody id=\"patternRows\"></tbody>
    </table>
  </div>

<script>
const canvas = document.getElementById('powerChart');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('ts');

function apiPath(path) {
  const clean = String(path || '').replace(/^\\/+/, '');
  return clean;
}

async function fetchJson(path) {
  const response = await fetch(apiPath(path));
  const body = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${body.slice(0, 120)}`);
  }

  try {
    return JSON.parse(body);
  } catch (error) {
    throw new Error(`Ungültige JSON-Antwort für ${path}: ${body.slice(0, 120)}`);
  }
}

function fmt(v, suffix='') {
  if (v === null || v === undefined) return '-';
  return `${Number(v).toFixed(1)}${suffix}`;
}

function setStatus(message) {
  statusEl.textContent = message;
}

async function flushDebugDb() {
  const sure = confirm('Soll die Debug-Datenbank wirklich geleert werden?');
  if (!sure) return;

  try {
    setStatus('Leere Datenbank...');
    const response = await fetch(apiPath('api/debug/flush-db'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reset_patterns: true })
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    const deleted = payload.deleted || {};
    alert(`DB geleert. Messwerte: ${deleted.power_readings || 0}, Erkennungen: ${deleted.detections || 0}, Muster: ${deleted.learned_patterns || 0}`);
    await refresh();
  } catch (err) {
    alert(`DB-Flush fehlgeschlagen: ${err}`);
    setStatus(`DB-Flush fehlgeschlagen: ${err}`);
  }
}

async function runLearningNow() {
  try {
    setStatus('Starte Lernlauf...');
    const response = await fetch(apiPath('api/debug/run-learning-now'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    alert(`Lernlauf abgeschlossen. Zusammengeführt: ${payload.merged || 0}, Muster geprüft: ${payload.patterns_considered || 0}`);
    await refresh();
  } catch (err) {
    alert(`Lernlauf fehlgeschlagen: ${err}`);
    setStatus(`Lernlauf fehlgeschlagen: ${err}`);
  }
}

function buildLiveStatusMessage(live) {
  const now = new Date().toLocaleString();
  const power = live && live.current_power_w;
  const sensorTs = live && live.timestamp;

  if (power === null || power === undefined) {
    if (sensorTs) {
      return `Warte auf verwertbare Messwerte (letzter Sensor-Zeitstempel: ${sensorTs})`;
    }
    return `Warte auf erste Messwerte vom Sensor (Stand: ${now})`;
  }

  return `Aktiv: ${fmt(power, ' W')} (aktualisiert: ${now})`;
}

function drawChart(series) {
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, w, h);

  if (!series || series.length < 2) {
    ctx.fillStyle = '#667085';
    ctx.font = '14px Segoe UI';
    ctx.fillText('Noch nicht genug Daten für den Verlauf.', 20, 36);
    return;
  }

  const values = series.map(p => Number(p.power_w));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);

  ctx.strokeStyle = '#d0d5dd';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = 20 + (i * (h - 40) / 4);
    ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
  }

  ctx.strokeStyle = '#006d77';
  ctx.lineWidth = 2;
  ctx.beginPath();
  series.forEach((point, i) => {
    const x = 10 + (i * (w - 20) / (series.length - 1));
    const y = h - 20 - ((point.power_w - min) / span) * (h - 40);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = '#667085';
  ctx.font = '12px Segoe UI';
  ctx.fillText(`min ${min.toFixed(1)}W`, 12, h - 6);
  ctx.fillText(`max ${max.toFixed(1)}W`, w - 90, h - 6);
}

function renderDevices(devices) {
  const tbody = document.getElementById('deviceRows');
  tbody.innerHTML = '';
  const names = Object.keys(devices || {});
  if (!names.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="6">Keine Geräte konfiguriert oder noch keine Erkennung.</td>';
    tbody.appendChild(tr);
    return;
  }
  names.forEach(name => {
    const d = devices[name];
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${name}</td><td>${d.state || '-'}</td><td>${fmt(d.estimated_power_w)}</td><td>${fmt(d.confidence)}</td><td>${d.daily_cycles ?? '-'}</td><td>${fmt(d.daily_runtime_seconds)}</td>`;
    tbody.appendChild(tr);
  });
}

function renderPatterns(patterns) {
  const tbody = document.getElementById('patternRows');
  tbody.innerHTML = '';
  if (!patterns || !patterns.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="9">Noch keine Muster erkannt.</td>';
    tbody.appendChild(tr);
    return;
  }

  patterns.forEach(p => {
    const tr = document.createElement('tr');
    const label = p.user_label || '-';
    const candidate = p.candidate_name || p.suggestion_type || 'unbekannt';
    const typeText = p.is_confirmed ? candidate : `evtl. ${candidate}`;
    const phaseModeRaw = String(p.phase_mode || 'unknown');
    const phaseMode = phaseModeRaw === 'single_phase' ? '1-ph' : (phaseModeRaw === 'multi_phase' ? '3-ph' : '?');
    tr.innerHTML = `<td>${p.id}</td><td>${typeText}</td><td>${label}</td><td>${phaseMode}</td><td>${fmt(p.avg_power_w)}</td><td>${fmt(p.peak_power_w)}</td><td>${fmt(p.duration_s)}</td><td>${p.seen_count ?? 0}</td><td><button data-id="${p.id}">Label</button></td>`;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('button[data-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.getAttribute('data-id'));
      const label = prompt('Welches Gerät ist das? (z.B. Kühlschrank)');
      if (!label) return;
      try {
        const res = await fetch(apiPath(`api/patterns/${id}/label`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await refresh();
      } catch (err) {
        alert(`Konnte Label nicht speichern: ${err}`);
      }
    });
  });
}

async function refresh() {
  try {
    setStatus('Lade Live-Daten...');
    const [summaryRes, seriesRes, liveRes, patternsRes] = await Promise.all([
      fetchJson('api/summary'),
      fetchJson('api/series?limit=360'),
      fetchJson('api/live'),
      fetchJson('api/patterns')
    ]);

    const summary = summaryRes;
    const series = seriesRes;
    const live = liveRes;
    const patterns = patternsRes;

    document.getElementById('current_power').textContent = fmt(live.current_power_w, ' W');
    document.getElementById('avg_power').textContent = fmt(summary.avg_power_w, ' W');
    document.getElementById('peak_power').textContent = fmt(summary.max_power_w, ' W');
    document.getElementById('reading_count').textContent = String(summary.reading_count ?? 0);
    
    // Zeige Phaseninformationen
    const phases = live.phases || [];
    ['L1', 'L2', 'L3'].forEach(phaseName => {
      const phaseData = phases.find(p => p.name === phaseName);
      const cardEl = document.getElementById(`phase${phaseName}`);
      const valueEl = document.getElementById(`power_${phaseName.toLowerCase()}`);
      if (phaseData) {
        cardEl.style.display = 'block';
        valueEl.textContent = fmt(phaseData.power_w, ' W');
      } else {
        cardEl.style.display = 'none';
      }
    });

    setStatus(buildLiveStatusMessage(live));

    setStatus('Zeichne Verlauf und aktualisiere Tabellen...');
    drawChart(series.points || []);
    renderDevices(live.devices || {});
    renderPatterns(Array.isArray(patterns) ? patterns : []);
    setStatus(buildLiveStatusMessage(live));
  } catch (err) {
    setStatus(`Warte auf API: ${err}`);
  }
}

refresh();
setInterval(refresh, 5000);
document.getElementById('runLearningBtn').addEventListener('click', runLearningNow);
document.getElementById('flushDbBtn').addEventListener('click', flushDebugDb);
</script>
</body>
</html>
"""


class StatsWebServer:
    """Embedded HTTP server exposing stats APIs and a lightweight dashboard."""

    def __init__(
        self,
        host: str,
        port: int,
        get_live_data: Callable[[], Dict],
        get_summary_data: Callable[[], Dict],
        get_series_data: Callable[[int], List[Dict]],
        get_patterns_data: Optional[Callable[[], List[Dict]]] = None,
        set_pattern_label: Optional[Callable[[int, str], bool]] = None,
        flush_debug_data: Optional[Callable[[bool], Dict]] = None,
        run_learning_now: Optional[Callable[[], Dict]] = None,
    ):
        self.host = host
        self.port = int(port)
        self.get_live_data = get_live_data
        self.get_summary_data = get_summary_data
        self.get_series_data = get_series_data
        self.get_patterns_data = get_patterns_data
        self.set_pattern_label = set_pattern_label
        self.flush_debug_data = flush_debug_data
        self.run_learning_now = run_learning_now
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        handler = self._build_handler()
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info(f"Web UI started on {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to start web UI server: {e}", exc_info=True)
            return False

    def stop(self) -> None:
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
                logger.info("Web UI server stopped")
            except Exception as e:
                logger.warning(f"Error while stopping web UI server: {e}")
            finally:
                self._server = None

    def _build_handler(self):
        parent = self
        html = _html_page()

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload: Dict | List, status: int = 200) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, body: str) -> None:
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(html)
                    return

                if parsed.path == "/health":
                    self._send_json({"status": "ok", "ts": datetime.now().isoformat()})
                    return

                if parsed.path == "/api/live":
                    self._send_json(parent.get_live_data())
                    return

                if parsed.path == "/api/summary":
                    self._send_json(parent.get_summary_data())
                    return

                if parsed.path == "/api/series":
                    query = parse_qs(parsed.query or "")
                    limit_raw = (query.get("limit") or ["300"])[0]
                    try:
                        limit = max(10, min(int(limit_raw), 2000))
                    except ValueError:
                        limit = 300
                    self._send_json({"points": parent.get_series_data(limit)})
                    return

                if parsed.path == "/api/patterns":
                    if parent.get_patterns_data:
                        self._send_json(parent.get_patterns_data())
                    else:
                        self._send_json([])
                    return

                self._send_json({"error": "not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/debug/run-learning-now":
                    if not parent.run_learning_now:
                        self._send_json({"error": "manual learning trigger not enabled"}, status=400)
                        return

                    result = parent.run_learning_now()
                    if not result.get("ok"):
                        self._send_json(result, status=500)
                        return

                    self._send_json(result)
                    return

                if parsed.path == "/api/debug/flush-db":
                    if not parent.flush_debug_data:
                        self._send_json({"error": "debug flush not enabled"}, status=400)
                        return

                    length = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    try:
                        payload = json.loads(raw.decode("utf-8")) if raw else {}
                    except json.JSONDecodeError:
                        self._send_json({"error": "invalid json"}, status=400)
                        return

                    reset_patterns = bool(payload.get("reset_patterns", True))
                    result = parent.flush_debug_data(reset_patterns)
                    if not result.get("ok"):
                        self._send_json(result, status=500)
                        return

                    self._send_json(result)
                    return

                if parsed.path.startswith("/api/patterns/") and parsed.path.endswith("/label"):
                    if not parent.set_pattern_label:
                        self._send_json({"error": "labeling not enabled"}, status=400)
                        return

                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) != 4:
                        self._send_json({"error": "invalid path"}, status=400)
                        return

                    try:
                        pattern_id = int(parts[2])
                    except ValueError:
                        self._send_json({"error": "invalid pattern id"}, status=400)
                        return

                    length = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    try:
                        payload = json.loads(raw.decode("utf-8")) if raw else {}
                    except json.JSONDecodeError:
                        self._send_json({"error": "invalid json"}, status=400)
                        return

                    label = str(payload.get("label", "")).strip()
                    if not label:
                        self._send_json({"error": "label is required"}, status=400)
                        return

                    ok = parent.set_pattern_label(pattern_id, label)
                    if not ok:
                        self._send_json({"error": "failed to save label"}, status=500)
                        return

                    self._send_json({"ok": True})
                    return

                self._send_json({"error": "not found"}, status=404)

            def log_message(self, format: str, *args):
                return

        return Handler
