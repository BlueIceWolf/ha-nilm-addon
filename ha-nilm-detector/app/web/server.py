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
    :root.dark-mode {
      --bg: #1a1a1a;
      --card: #2d2d2d;
      --ink: #e5e5e5;
      --muted: #a0a0a0;
      --line: #404040;
      --accent: #4db8c4;
      --accent-soft: #2a4a4e;
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
      font-size: 0.9rem;
    }
    button:hover { background: var(--accent-soft); }
    button.active { background: var(--accent); color: #fff; }
    .chart-controls {
      display: flex;
      gap: 8px;
      margin-bottom: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .chart-controls .btn-group {
      display: flex;
      gap: 4px;
    }
    .chart-selection-overlay {
      position: absolute;
      background: rgba(0, 109, 119, 0.2);
      border: 2px solid var(--accent);
      pointer-events: none;
      display: none;
    }
    .tooltip {
      position: relative;
      cursor: help;
      border-bottom: 1px dotted var(--muted);
    }
    .tooltip .tooltiptext {
      visibility: hidden;
      width: 200px;
      background-color: #333;
      color: #fff;
      text-align: left;
      border-radius: 6px;
      padding: 8px;
      position: absolute;
      z-index: 1000;
      bottom: 125%;
      left: 50%;
      margin-left: -100px;
      opacity: 0;
      transition: opacity 0.3s;
      font-size: 0.8rem;
      line-height: 1.4;
    }
    .tooltip .tooltiptext::after {
      content: "";
      position: absolute;
      top: 100%;
      left: 50%;
      margin-left: -5px;
      border-width: 5px;
      border-style: solid;
      border-color: #333 transparent transparent transparent;
    }
    .tooltip:hover .tooltiptext {
      visibility: visible;
      opacity: 1;
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
    <div style=\"margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;\">
      <button id=\"runLearningBtn\" title=\"Lernlauf sofort starten\">Lernen jetzt ausführen</button>
      <button id=\"flushDbBtn\" title=\"Nur für Debugging\">DB leeren (Debug)</button>
      <button id=\"importHistoryBtn\" title=\"Verlauf aus Home Assistant importieren\">HA Verlauf importieren</button>
      <button id=\"darkModeToggle\" title=\"Hell/Dunkel umschalten\">🌙 Nachtmodus</button>
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
      <div class=\"card\"><div class=\"label\">Gelernte Muster</div><div id=\"pattern_count\" class=\"value\">-</div></div>
    </div>

    <div class=\"chart-wrap\">
      <div class=\"chart-controls\">
        <span class=\"muted\" style=\"font-size: 0.85rem;\">Anzeigen:</span>
        <div class=\"btn-group\">
          <button class=\"phase-toggle active\" data-phase=\"total\">Gesamt</button>
          <button class=\"phase-toggle\" data-phase=\"L1\" style=\"display:none;\">L1</button>
          <button class=\"phase-toggle\" data-phase=\"L2\" style=\"display:none;\">L2</button>
          <button class=\"phase-toggle\" data-phase=\"L3\" style=\"display:none;\">L3</button>
        </div>
        <span class=\"muted\" style=\"font-size: 0.85rem; margin-left: 12px;\">|</span>
        <button id=\"selectRangeBtn\" title=\"Bereich im Graphen markieren und als Muster speichern\">📍 Bereich markieren</button>
      </div>
      <div style=\"position: relative;\">
        <canvas id=\"powerChart\" width=\"1000\" height=\"280\"></canvas>
        <div id=\"selectionOverlay\" class=\"chart-selection-overlay\"></div>
      </div>
    </div>

    <h2 style=\"margin:14px 0 8px; font-size:1.1rem;\">Erkannte Geräte</h2>
    <table>
      <thead>
        <tr><th>Gerät</th><th>Status</th><th>Leistung (W)</th><th>Konfidenz</th><th>Zyklen</th><th>Laufzeit (s)</th></tr>
      </thead>
      <tbody id=\"deviceRows\"></tbody>
    </table>

    <h2 style=\"margin:14px 0 8px; font-size:1.1rem;\">Gelernte Muster</h2>
    <div style=\"margin-bottom: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;\">
      <input type=\"text\" id=\"patternSearch\" placeholder=\"Muster suchen...\" style=\"padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink); flex: 1; min-width: 200px;\" />
      <select id=\"patternSort\" style=\"padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink);\">
        <option value=\"seen_count\">Sortieren: Häufigkeit ↓</option>
        <option value=\"avg_power_w\">Sortieren: Leistung ↓</option>
        <option value=\"duration_s\">Sortieren: Dauer ↓</option>
        <option value=\"stability_score\">Sortieren: Stabilität ↓</option>
        <option value=\"typical_interval_s\">Sortieren: Intervall ↓</option>
        <option value=\"id\">Sortieren: ID ↑</option>
      </select>
    </div>
    <table>
      <thead>
        <tr><th>ID</th><th>Typ</th><th>Label</th><th style="font-size:0.85rem;">Häufig.</th><th style="font-size:0.85rem;">Intervall</th><th style="font-size:0.85rem;">Uhrzeit</th><th style="font-size:0.85rem;">Stabilit.</th><th>Phasen</th><th style="font-size:0.85rem;">Modi</th><th>Ø (W)</th><th>Spitze (W)</th><th>Dauer (s)</th><th>Anzahl</th><th>Aktion</th></tr>
      </thead>
      <tbody id=\"patternRows\"></tbody>
    </table>
  </div>

<script>
const canvas = document.getElementById('powerChart');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('ts');
const selectionOverlay = document.getElementById('selectionOverlay');

// State für sichtbare Phasen und Daten
let visiblePhases = { total: true, L1: false, L2: false, L3: false };
let currentSeriesData = null;
let availablePhases = [];
let isSelectingRange = false;
let selectionStart = null;
let allPatterns = [];
let currentSortBy = 'seen_count';

// Dark Mode initialisieren
if (localStorage.getItem('darkMode') === 'true') {
  document.documentElement.classList.add('dark-mode');
}



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

async function importHistoryFromHA() {
  const raw = prompt('Wie viele Stunden Verlauf importieren? (1-168)', '24');
  if (raw === null) return;

  const hours = Number(raw);
  if (!Number.isFinite(hours) || hours < 1 || hours > 168) {
    alert('Bitte eine Zahl zwischen 1 und 168 eingeben.');
    return;
  }

  try {
    setStatus('Importiere Verlauf aus HA...');
    const response = await fetch(apiPath('api/debug/import-history'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: Math.round(hours) })
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    alert(`Import abgeschlossen. Messwerte importiert: ${payload.imported || 0}`);
    await refresh();
  } catch (err) {
    alert(`Import fehlgeschlagen: ${err}`);
    setStatus(`Import fehlgeschlagen: ${err}`);
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
  currentSeriesData = series;
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

  // Sammle alle Werte für Min/Max-Berechnung
  let allValues = [];
  if (visiblePhases.total) {
    allValues = allValues.concat(series.map(p => Number(p.power_w || 0)));
  }
  ['L1', 'L2', 'L3'].forEach(phase => {
    if (visiblePhases[phase] && availablePhases.includes(phase)) {
      allValues = allValues.concat(series.map(p => Number((p.phases && p.phases[phase]) || 0)));
    }
  });

  if (allValues.length === 0) {
    ctx.fillStyle = '#667085';
    ctx.font = '14px Segoe UI';
    ctx.fillText('Keine Phase ausgewählt.', 20, 36);
    return;
  }

  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const span = Math.max(max - min, 1);

  // Gitterlinien
  ctx.strokeStyle = '#d0d5dd';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = 20 + (i * (h - 40) / 4);
    ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
  }

  const colors = {
    total: '#006d77',
    L1: '#e63946',
    L2: '#2a9d8f',
    L3: '#f77f00'
  };

  // Zeichne Gesamt
  if (visiblePhases.total) {
    ctx.strokeStyle = colors.total;
    ctx.lineWidth = 2;
    ctx.beginPath();
    series.forEach((point, i) => {
      const x = 10 + (i * (w - 20) / (series.length - 1));
      const y = h - 20 - ((point.power_w - min) / span) * (h - 40);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // Zeichne einzelne Phasen
  ['L1', 'L2', 'L3'].forEach(phase => {
    if (visiblePhases[phase] && availablePhases.includes(phase)) {
      ctx.strokeStyle = colors[phase];
      ctx.lineWidth = 2;
      ctx.beginPath();
      series.forEach((point, i) => {
        const value = (point.phases && point.phases[phase]) || 0;
        const x = 10 + (i * (w - 20) / (series.length - 1));
        const y = h - 20 - ((value - min) / span) * (h - 40);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
  });

  // Legende
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
  // Store all patterns for filtering/sorting  
  if (patterns && patterns.length > 0) {
    allPatterns = patterns;
  }
  
  const tbody = document.getElementById('patternRows');
  tbody.innerHTML = '';
  if (!patterns || !patterns.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="14">Noch keine Muster erkannt.</td>';
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
    
    // Häufigkeits- und Stabilitäts-Indikatoren
    const frequency = p.frequency_label || 'unbekannt';
    const stability = p.stability_score ?? 50;
    const stabilityColor = stability >= 80 ? '#28a745' : (stability >= 60 ? '#ffc107' : '#dc3545');
    const stabilityBar = `<div style="background:#e9ecef;border-radius:3px;height:16px;overflow:hidden;position:relative;"><div style="background:${stabilityColor};width:${stability}%;height:100%;">&nbsp;</div><span style="position:absolute;top:0;left:2px;font-size:0.75rem;color:#000;line-height:16px;font-weight:bold;">${stability}%</span></div>`;
    
    // Temporale Muster - Intervall
    const typicalInterval = p.typical_interval_s || 0;
    let intervalText = '-';
    let intervalTooltip = '';
    if (typicalInterval > 0) {
      if (typicalInterval < 120) {
        intervalText = `${Math.round(typicalInterval)}s`;
      } else if (typicalInterval < 3600) {
        intervalText = `${Math.round(typicalInterval / 60)}min`;
      } else if (typicalInterval < 86400) {
        intervalText = `${(typicalInterval / 3600).toFixed(1)}h`;
      } else {
        intervalText = `${(typicalInterval / 86400).toFixed(1)}d`;
      }
      
      // Zusätzliche Details für Tooltip
      try {
        const lastIntervals = JSON.parse(p.last_intervals_json || '[]');
        if (lastIntervals.length > 0) {
          const intervalList = lastIntervals.map(iv => {
            if (iv < 120) return `${Math.round(iv)}s`;
            if (iv < 3600) return `${Math.round(iv / 60)}min`;
            if (iv < 86400) return `${(iv / 3600).toFixed(1)}h`;
            return `${(iv / 86400).toFixed(1)}d`;
          }).join(', ');
          intervalTooltip = `Letzte Intervalle:<br>${intervalList}`;
        }
      } catch (e) {}
    }
    
    // Temporale Muster - Durchschnittliche Tageszeit
    const avgHour = p.avg_hour_of_day || 0;
    let timeText = '-';
    let timeTooltip = '';
    if (avgHour > 0) {
      const hours = Math.floor(avgHour);
      const minutes = Math.round((avgHour - hours) * 60);
      timeText = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
      
      // Stunden-Verteilung für Tooltip
      try {
        const hourDist = JSON.parse(p.hour_distribution_json || '{}');
        const hourKeys = Object.keys(hourDist).sort((a, b) => hourDist[b] - hourDist[a]);
        if (hourKeys.length > 0) {
          const top3 = hourKeys.slice(0, 3).map(h => {
            const hNum = parseInt(h);
            return `${hNum}:00 (${hourDist[h]}x)`;
          }).join('<br>');
          timeTooltip = `Häufigste Stunden:<br>${top3}`;
        }
      } catch (e) {}
    }
    
    // Multi-Mode Info (intelligent!)
    const modes = p.operating_modes || [];
    const modeLabels = modes.map(m => {
      const modeIcon = m.type === 'startup' ? '↑' : (m.type === 'shutdown' ? '↓' : (m.type === 'standby' ? '◯' : '●'));
      return `${modeIcon}${m.type.slice(0,3).toUpperCase()}(${m.avg_power_w.toFixed(0)}W)`;
    }).join(' ');
    const modeInfo = p.has_multiple_modes ? `<span style="font-size:0.8rem;color:#666;">${modeLabels}</span>` : '<span style="font-size:0.8rem;color:#999;">-</span>';
    
    // Intervall-Zelle mit Tooltip
    const intervalCell = intervalTooltip 
      ? `<td><div class="tooltip" style="font-size:0.85rem;color:#006d77;font-weight:600;">${intervalText}<span class="tooltiptext">${intervalTooltip}</span></div></td>`
      : `<td style="font-size:0.85rem;color:#006d77;font-weight:600;">${intervalText}</td>`;
    
    // Uhrzeit-Zelle mit Tooltip
    const timeCell = timeTooltip
      ? `<td><div class="tooltip" style="font-size:0.85rem;color:#666;">${timeText}<span class="tooltiptext">${timeTooltip}</span></div></td>`
      : `<td style="font-size:0.85rem;color:#666;">${timeText}</td>`;
    
    tr.innerHTML = `<td>${p.id}</td><td>${typeText}</td><td>${label}</td><td style="font-size:0.85rem;color:#666;">${frequency}</td>${intervalCell}${timeCell}<td style="padding:4px 2px;">${stabilityBar}</td><td>${phaseMode}</td><td>${modeInfo}</td><td>${fmt(p.avg_power_w)}</td><td>${fmt(p.peak_power_w)}</td><td>${fmt(p.duration_s)}</td><td>${p.seen_count ?? 0}</td><td><button data-id="${p.id}">Label</button></td>`;
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
    
    // Muster-Statistik
    const patternArray = Array.isArray(patterns) ? patterns : [];
    const confirmedCount = patternArray.filter(p => p.is_confirmed).length;
    const totalCount = patternArray.length;
    document.getElementById('pattern_count').textContent = totalCount > 0 
      ? `${totalCount} (${confirmedCount} best\u00e4tigt)` 
      : '0';
    
    // Zeige Phaseninformationen und aktualisiere verfügbare Phasen
    const phases = live.phases || [];
    availablePhases = [];
    ['L1', 'L2', 'L3'].forEach(phaseName => {
      const phaseData = phases.find(p => p.name === phaseName);
      const cardEl = document.getElementById(`phase${phaseName}`);
      const valueEl = document.getElementById(`power_${phaseName.toLowerCase()}`);
      const toggleBtn = document.querySelector(`.phase-toggle[data-phase="${phaseName}"]`);
      
      if (phaseData) {
        availablePhases.push(phaseName);
        cardEl.style.display = 'block';
        valueEl.textContent = fmt(phaseData.power_w, ' W');
        if (toggleBtn) toggleBtn.style.display = 'inline-block';
      } else {
        cardEl.style.display = 'none';
        if (toggleBtn) toggleBtn.style.display = 'none';
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

// Phase-Toggle Event-Handler
document.querySelectorAll('.phase-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const phase = btn.getAttribute('data-phase');
    visiblePhases[phase] = !visiblePhases[phase];
    btn.classList.toggle('active', visiblePhases[phase]);
    if (currentSeriesData) {
      drawChart(currentSeriesData);
    }
  });
});

// Bereichsauswahl-Funktionalität
let rangeSelection = { active: false, startX: null, startIdx: null };

document.getElementById('selectRangeBtn').addEventListener('click', () => {
  rangeSelection.active = !rangeSelection.active;
  const btn = document.getElementById('selectRangeBtn');
  btn.classList.toggle('active', rangeSelection.active);
  btn.textContent = rangeSelection.active ? '✓ Wähle Bereich aus' : '📍 Bereich markieren';
  selectionOverlay.style.display = 'none';
  canvas.style.cursor = rangeSelection.active ? 'crosshair' : 'default';
});

canvas.addEventListener('mousedown', (e) => {
  if (!rangeSelection.active || !currentSeriesData) return;
  const rect = canvas.getBoundingClientRect();
  rangeSelection.startX = e.clientX - rect.left;
  rangeSelection.startIdx = getDataIndexFromX(rangeSelection.startX);
});

canvas.addEventListener('mousemove', (e) => {
  if (!rangeSelection.active || rangeSelection.startX === null || !currentSeriesData) return;
  const rect = canvas.getBoundingClientRect();
  const currentX = e.clientX - rect.left;
  
  const left = Math.min(rangeSelection.startX, currentX);
  const width = Math.abs(currentX - rangeSelection.startX);
  
  selectionOverlay.style.left = `${left}px`;
  selectionOverlay.style.top = '0';
  selectionOverlay.style.width = `${width}px`;
  selectionOverlay.style.height = `${canvas.height}px`;
  selectionOverlay.style.display = 'block';
});

canvas.addEventListener('mouseup', async (e) => {
  if (!rangeSelection.active || rangeSelection.startX === null || !currentSeriesData) return;
  
  const rect = canvas.getBoundingClientRect();
  const endX = e.clientX - rect.left;
  const endIdx = getDataIndexFromX(endX);
  
  const startIdx = Math.min(rangeSelection.startIdx, endIdx);
  const endIdxFinal = Math.max(rangeSelection.startIdx, endIdx);
  
  if (endIdxFinal - startIdx > 2 && currentSeriesData.length > 0) {
    await createPatternFromRange(startIdx, endIdxFinal);
  }
  
  rangeSelection.startX = null;
  rangeSelection.startIdx = null;
  selectionOverlay.style.display = 'none';
});

function getDataIndexFromX(x) {
  if (!currentSeriesData || currentSeriesData.length === 0) return 0;
  const w = canvas.width;
  const normalized = Math.max(0, Math.min((x - 10) / (w - 20), 1));
  return Math.round(normalized * (currentSeriesData.length - 1));
}

async function createPatternFromRange(startIdx, endIdx) {
  const label = prompt('Welches Gerät ist das? (z.B. Waschmaschine, Kühlschrank)');
  if (!label) return;
  
  const startPoint = currentSeriesData[startIdx];
  const endPoint = currentSeriesData[endIdx];
  
  if (!startPoint || !endPoint || !startPoint.timestamp || !endPoint.timestamp) {
    alert('Ungültiger Zeitbereich ausgewählt.');
    return;
  }
  
  try {
    setStatus('Erstelle Muster aus Bereich...');
    const response = await fetch(apiPath('api/patterns/create-from-range'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start_time: startPoint.timestamp,
        end_time: endPoint.timestamp,
        label: label
      })
    });
    
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || `HTTP ${response.status}`);
    }
    
    alert(`Muster erfolgreich erstellt! ID: ${result.pattern_id || '?'}`);
    rangeSelection.active = false;
    document.getElementById('selectRangeBtn').classList.remove('active');
    document.getElementById('selectRangeBtn').textContent = '📍 Bereich markieren';
    canvas.style.cursor = 'default';
    await refresh();
  } catch (err) {
    alert(`Muster-Erstellung fehlgeschlagen: ${err}`);
    setStatus(`Muster-Erstellung fehlgeschlagen: ${err}`);
  }
}

refresh();
setInterval(refresh, 5000);
document.getElementById('runLearningBtn').addEventListener('click', runLearningNow);
document.getElementById('flushDbBtn').addEventListener('click', flushDebugDb);
document.getElementById('importHistoryBtn').addEventListener('click', importHistoryFromHA);
document.getElementById('darkModeToggle').addEventListener('click', toggleDarkMode);
document.getElementById('patternSearch').addEventListener('input', filterAndSortPatterns);
document.getElementById('patternSort').addEventListener('change', (e) => {
  currentSortBy = e.target.value;
  filterAndSortPatterns();
});

function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark-mode');
  localStorage.setItem('darkMode', isDark);
  const btn = document.getElementById('darkModeToggle');
  btn.textContent = isDark ? '☀️ Tagmodus' : '🌙 Nachtmodus';
}

function filterAndSortPatterns() {
  const searchTerm = document.getElementById('patternSearch').value.toLowerCase();
  let filtered = allPatterns;
  
  // Filtern
  if (searchTerm) {
    filtered = allPatterns.filter(p => {
      const label = (p.user_label || '').toLowerCase();
      const type = (p.suggestion_type || '').toLowerCase();
      const candidate = (p.candidate_name || '').toLowerCase();
      const id = String(p.id || '');
      return label.includes(searchTerm) || type.includes(searchTerm) || 
             candidate.includes(searchTerm) || id.includes(searchTerm);
    });
  }
  
  // Sortieren
  filtered.sort((a, b) => {
    const aVal = a[currentSortBy] ?? 0;
    const bVal = b[currentSortBy] ?? 0;
    // Für ID aufsteigend, sonst absteigend
    return currentSortBy === 'id' ? aVal - bVal : bVal - aVal;
  });
  
  renderPatterns(filtered);
}

// Dark Mode Button Text initial setzen
if (document.documentElement.classList.contains('dark-mode')) {
  document.getElementById('darkModeToggle').textContent = '☀️ Tagmodus';
}


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
        import_history_from_ha: Optional[Callable[[int], Dict]] = None,
        create_pattern_from_range: Optional[Callable[[str, str, str], Dict]] = None,
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
        self.import_history_from_ha = import_history_from_ha
        self.create_pattern_from_range = create_pattern_from_range
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

                if parsed.path == "/api/debug/import-history":
                    if not parent.import_history_from_ha:
                        self._send_json({"error": "history import not enabled"}, status=400)
                        return

                    length = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    try:
                        payload = json.loads(raw.decode("utf-8")) if raw else {}
                    except json.JSONDecodeError:
                        self._send_json({"error": "invalid json"}, status=400)
                        return

                    try:
                        hours = max(1, min(int(payload.get("hours", 24)), 168))
                    except (TypeError, ValueError):
                        self._send_json({"error": "hours must be an integer between 1 and 168"}, status=400)
                        return

                    result = parent.import_history_from_ha(hours)
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

                if parsed.path == "/api/patterns/create-from-range":
                    if not parent.create_pattern_from_range:
                        self._send_json({"error": "pattern creation from range not enabled"}, status=400)
                        return

                    length = int(self.headers.get("Content-Length", "0") or 0)
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    try:
                        payload = json.loads(raw.decode("utf-8")) if raw else {}
                    except json.JSONDecodeError:
                        self._send_json({"error": "invalid json"}, status=400)
                        return

                    start_time = str(payload.get("start_time", "")).strip()
                    end_time = str(payload.get("end_time", "")).strip()
                    label = str(payload.get("label", "")).strip()

                    if not start_time or not end_time or not label:
                        self._send_json({"error": "start_time, end_time, and label are required"}, status=400)
                        return

                    result = parent.create_pattern_from_range(start_time, end_time, label)
                    if not result.get("ok"):
                        self._send_json(result, status=500)
                        return

                    self._send_json(result)
                    return

                self._send_json({"error": "not found"}, status=404)

            def log_message(self, format: str, *args):
                return

        return Handler
