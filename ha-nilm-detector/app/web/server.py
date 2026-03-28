"""Simple embedded web server for NILM live status and statistics."""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _html_page(default_language: str = "de") -> str:
  lang = "en" if str(default_language).strip().lower() == "en" else "de"
  return """<!doctype html>
<html lang=\"__DEFAULT_LANG__\"> 
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>HA NILM Statistics</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --bg-elev: #ffffff;
      --card: #ffffff;
      --ink: #1f2a37;
      --muted: #6b7280;
      --line: #d8dee6;
      --accent: #03a9f4;
      --accent-strong: #0288d1;
      --accent-soft: #e3f4fd;
      --shadow-sm: 0 2px 8px rgba(17, 24, 39, 0.06);
      --shadow-md: 0 8px 24px rgba(17, 24, 39, 0.1);
      --radius: 14px;
    }
    :root.dark-mode {
      --bg: #11161c;
      --bg-elev: #18212c;
      --card: #1e2935;
      --ink: #e8eef5;
      --muted: #9aa7b5;
      --line: #2d3a47;
      --accent: #4fc3f7;
      --accent-strong: #29b6f6;
      --accent-soft: #19394a;
      --shadow-sm: 0 2px 10px rgba(0, 0, 0, 0.35);
      --shadow-md: 0 8px 28px rgba(0, 0, 0, 0.45);
    }
    body {
      margin: 0;
      font-family: "Roboto", "Noto Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(1200px 600px at -10% -10%, rgba(3, 169, 244, 0.16), transparent 60%),
        radial-gradient(1000px 500px at 110% -10%, rgba(79, 195, 247, 0.14), transparent 55%),
        linear-gradient(180deg, var(--bg-elev) 0%, var(--bg) 60%);
      color: var(--ink);
      -webkit-font-smoothing: antialiased;
    }
    .wrap {
      max-width: 1160px;
      margin: 18px auto;
      padding: 0 16px 20px;
    }
    .head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow-sm);
      padding: 12px 14px;
    }
    .head h1 {
      margin: 0;
      font-size: 1.28rem;
      letter-spacing: 0.01em;
      font-weight: 600;
    }
    .muted { color: var(--muted); font-size: 0.88rem; }
    .grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      margin-bottom: 10px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px 14px;
      box-shadow: var(--shadow-sm);
    }
    .label {
      font-size: 0.78rem;
      color: var(--muted);
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .value { font-size: 1.15rem; font-weight: 700; }
    .chart-wrap {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      margin-bottom: 10px;
      box-shadow: var(--shadow-md);
    }
    canvas { width: 100%; height: 280px; display: block; }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
      margin-bottom: 10px;
      box-shadow: var(--shadow-sm);
    }
    th, td {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-size: 0.89rem;
    }
    thead th {
      background: var(--accent-soft);
      color: var(--ink);
      font-weight: 600;
    }
    tbody tr:hover td {
      background: rgba(3, 169, 244, 0.08);
    }
    tbody tr:last-child td { border-bottom: 0; }
    button {
      border: 1px solid rgba(3, 169, 244, 0.45);
      background: rgba(3, 169, 244, 0.12);
      color: var(--accent-strong);
      border-radius: 10px;
      padding: 5px 10px;
      cursor: pointer;
      font-size: 0.86rem;
      font-weight: 500;
      transition: background 0.18s ease, border-color 0.18s ease, transform 0.08s ease;
    }
    button:hover {
      background: var(--accent-soft);
      border-color: var(--accent);
    }
    button:active {
      transform: translateY(1px);
    }
    button.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.btn-delete {
      background: rgba(239, 83, 80, 0.14);
      border-color: rgba(239, 83, 80, 0.45);
      color: #c62828;
      padding: 3px 6px;
      font-size: 0.8rem;
    }
    button.btn-delete:hover {
      background: rgba(239, 83, 80, 0.24);
      border-color: #c62828;
    }
    .chart-controls {
      display: flex;
      gap: 8px;
      margin-bottom: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .chart-controls .btn-group {
      display: flex;
      gap: 4px;
    }
    .chart-selection-overlay {
      position: absolute;
      background: rgba(3, 169, 244, 0.2);
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
      background-color: #0f1720;
      color: #f9fafb;
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
      border-color: #0f1720 transparent transparent transparent;
    }
    .tooltip:hover .tooltiptext {
      visibility: visible;
      opacity: 1;
    }
    .task-progress {
      display: none;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px 12px;
      margin-bottom: 10px;
      box-shadow: var(--shadow-sm);
    }
    .task-progress.visible {
      display: block;
    }
    .task-progress-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      font-size: 0.88rem;
    }
    .task-progress-bar {
      width: 100%;
      height: 8px;
      border-radius: 999px;
      background: rgba(3, 169, 244, 0.18);
      overflow: hidden;
    }
    .task-progress-fill {
      width: 0%;
      height: 100%;
      border-radius: 999px;
      background: var(--accent);
      transition: width 0.25s ease;
    }
    select,
    input[type="text"] {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--bg-elev);
      color: var(--ink);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
    }
    select:focus,
    input[type="text"]:focus,
    button:focus-visible {
      outline: 2px solid rgba(3, 169, 244, 0.55);
      outline-offset: 2px;
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
      <h1 id=\"pageTitle\">HA NILM Live-Statistik</h1>
      <div id=\"ts\" class=\"muted\">Lädt...</div>
    </div>
    <div style=\"margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;\">
      <button id=\"runLearningBtn\" title=\"Lernlauf sofort starten\">Lernen jetzt ausführen</button>
      <button id=\"clearReadingsBtn\" title=\"Nur Live-Daten (Readings) löschen\">🗑️ Live-Daten löschen</button>
      <button id=\"clearPatternsBtn\" title=\"Nur gelernte Muster löschen\">🗑️ Muster löschen</button>
      <button id=\"importHistoryBtn\" title=\"Verlauf aus Home Assistant importieren\">HA Verlauf importieren</button>
      <button id=\"exportDataBtn\" title=\"Muster + Messwerte als JSON exportieren\">📥 Daten exportieren</button>
      <button id=\"importDataBtn\" title=\"JSON-Datei mit Mustern/Messwerten importieren\">📤 Daten importieren</button>
      <input type=\"file\" id=\"importDataFile\" accept=\".json\" style=\"display: none;\" />
      <button id=\"darkModeToggle\" title=\"Hell/Dunkel umschalten\">🌙 Nachtmodus</button>
      <label for=\"languageSelect\" id=\"languageLabel\" class=\"muted\" style=\"margin-left: 8px;\">Sprache:</label>
      <select id=\"languageSelect\" style=\"padding: 5px 8px;\">
        <option value=\"de\">Deutsch</option>
        <option value=\"en\">English</option>
      </select>
    </div>

    <div id=\"activeTask\" class=\"task-progress\" aria-live=\"polite\">
      <div class=\"task-progress-head\">
        <span id=\"taskName\" class=\"muted\">Aufgabe läuft...</span>
        <strong id=\"taskPercent\">0%</strong>
      </div>
      <div class=\"task-progress-bar\">
        <div id=\"progressFill\" class=\"task-progress-fill\"></div>
      </div>
    </div>

    <div class=\"grid\">
      <div class=\"card\"><div id=\"lblCurrentPower\" class=\"label\">Gesamtleistung</div><div id=\"current_power\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL1\" style=\"display:none;\"><div id=\"lblPhaseL1\" class=\"label\">Phase L1</div><div id=\"power_l1\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL2\" style=\"display:none;\"><div id=\"lblPhaseL2\" class=\"label\">Phase L2</div><div id=\"power_l2\" class=\"value\">-</div></div>
      <div class=\"card\" id=\"phaseL3\" style=\"display:none;\"><div id=\"lblPhaseL3\" class=\"label\">Phase L3</div><div id=\"power_l3\" class=\"value\">-</div></div>
    </div>

    <div class=\"grid\">
      <div class=\"card\"><div id=\"lblAvgPower\" class=\"label\">Durchschnitt (24h)</div><div id=\"avg_power\" class=\"value\">-</div></div>
      <div class=\"card\"><div id=\"lblPeakPower\" class=\"label\">Spitze (24h)</div><div id=\"peak_power\" class=\"value\">-</div></div>
      <div class=\"card\"><div id=\"lblReadingCount\" class=\"label\">Messwerte (24h)</div><div id=\"reading_count\" class=\"value\">-</div></div>
      <div class=\"card\"><div id=\"lblPatternCount\" class=\"label\">Gelernte Muster</div><div id=\"pattern_count\" class=\"value\">-</div></div>
    </div>

    <div class=\"chart-wrap\">
      <div class=\"chart-controls\">
        <span id=\"showLabel\" class=\"muted\" style=\"font-size: 0.85rem;\">Anzeigen:</span>
        <div class=\"btn-group\">
          <button id=\"phaseTotalBtn\" class=\"phase-toggle active\" data-phase=\"total\">Gesamt</button>
          <button class=\"phase-toggle\" data-phase=\"L1\" style=\"display:none;\">L1</button>
          <button class=\"phase-toggle\" data-phase=\"L2\" style=\"display:none;\">L2</button>
          <button class=\"phase-toggle\" data-phase=\"L3\" style=\"display:none;\">L3</button>
        </div>
        <span class=\"muted\" style=\"font-size: 0.85rem; margin-left: 12px;\">|</span>
        <label id=\"windowLabel\" for=\"windowSelect\" class=\"muted\" style=\"font-size: 0.85rem;\">Fenster:</label>
        <select id=\"windowSelect\" style=\"padding: 4px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--ink);\">
          <option value=\"120\">1h</option>
          <option value=\"360\" selected>3h</option>
          <option value=\"720\">6h</option>
          <option value=\"1440\">12h</option>
          <option value=\"2880\">24h</option>
        </select>
        <button id=\"olderBtn\" title=\"Ältere Messpunkte anzeigen\">← Älter</button>
        <button id=\"newerBtn\" title=\"Neuere Messpunkte anzeigen\">Neuer →</button>
        <span id=\"windowInfo\" class=\"muted\" style=\"font-size: 0.8rem;\">3h, aktuell</span>
        <span class=\"muted\" style=\"font-size: 0.85rem; margin-left: 12px;\">|</span>
        <button id=\"selectRangeBtn\" title=\"Bereich im Graphen markieren und als Muster speichern\">📍 Bereich markieren</button>
      </div>
      <div style=\"position: relative;\">
        <canvas id=\"powerChart\" width=\"1000\" height=\"280\"></canvas>
        <div id=\"selectionOverlay\" class=\"chart-selection-overlay\"></div>
      </div>
    </div>

    <h2 id=\"devicesHeading\" style=\"margin:14px 0 8px; font-size:1.1rem;\">Erkannte Geräte</h2>
    <table>
      <thead>
        <tr><th id=\"thDevice\">Gerät</th><th id=\"thStatus\">Status</th><th id=\"thPower\">Leistung (W)</th><th id=\"thConfidence\">Konfidenz</th><th id=\"thCycles\">Zyklen</th><th id=\"thRuntime\">Laufzeit (s)</th></tr>
      </thead>
      <tbody id=\"deviceRows\"></tbody>
    </table>

    <h2 id=\"patternsHeading\" style=\"margin:14px 0 8px; font-size:1.1rem;\">Gelernte Muster</h2>
    <div style=\"margin-bottom: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;\">
      <input type=\"text\" id=\"patternSearch\" placeholder=\"Muster suchen...\" style=\"padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink); flex: 1; min-width: 200px;\" />
      <select id=\"patternSort\" style=\"padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink);\">
        <option id=\"sortSeenCount\" value=\"seen_count\">Sortieren: Häufigkeit ↓</option>
        <option id=\"sortConfidence\" value=\"confidence_score\">Sortieren: Confidence ↓</option>
        <option id=\"sortGroupSize\" value=\"device_group_size\">Sortieren: Gruppe ↓</option>
        <option id=\"sortPower\" value=\"avg_power_w\">Sortieren: Leistung ↓</option>
        <option id=\"sortDuration\" value=\"duration_s\">Sortieren: Dauer ↓</option>
        <option id=\"sortStability\" value=\"stability_score\">Sortieren: Stabilität ↓</option>
        <option id=\"sortInterval\" value=\"typical_interval_s\">Sortieren: Intervall ↓</option>
        <option id=\"sortId\" value=\"id\">Sortieren: ID ↑</option>
      </select>
    </div>
    <table>
      <thead>
        <tr><th id=\"pthId\">ID</th><th id=\"pthType\">Typ</th><th id=\"pthLabel\">Label</th><th id=\"pthGroup\" style="font-size:0.85rem;">Gruppe</th><th id=\"pthFrequency\" style="font-size:0.85rem;">Häufig.</th><th id=\"pthInterval\" style="font-size:0.85rem;">Intervall</th><th id=\"pthTime\" style="font-size:0.85rem;">Uhrzeit</th><th id=\"pthStability\" style="font-size:0.85rem;">Stabilit.</th><th id=\"pthConfidence\" style="font-size:0.85rem;">Conf.</th><th id=\"pthPhases\">Phasen</th><th id=\"pthAvg\">Ø (W)</th><th id=\"pthPeak\">Spitze (W)</th><th id=\"pthDuration\">Dauer (s)</th><th id=\"pthCount\">Anzahl</th><th id=\"pthAction\">Aktion</th></tr>
      </thead>
      <tbody id=\"patternRows\"></tbody>
    </table>

    <!-- Pattern Visualization Modal -->
    <div id=\"patternModal\" style=\"display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:1000;justify-content:center;align-items:center;flex-direction:column;padding:20px;box-sizing:border-box;\">
      <div style=\"background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px;max-width:900px;width:100%;box-shadow:var(--shadow-md);max-height:90vh;overflow-y:auto;\">
        <div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;\">
          <h2 style=\"margin:0;font-size:1.2rem;\" id=\"patternModalTitle\">Muster-Profil</h2>
          <button onclick=\"document.getElementById('patternModal').style.display='none'\" style=\"background:none;border:none;font-size:1.5rem;cursor:pointer;color:var(--muted);\">✕</button>
        </div>
        <div style=\"margin-bottom:12px;\">
          <div id=\"patternProfileSource\" class=\"muted\" style=\"margin-bottom:6px;font-size:0.82rem;\">Quelle: Rekonstruierte Kurve</div>
          <canvas id=\"patternChart\" width=\"800\" height=\"300\" style=\"border:1px solid var(--line);border-radius:6px;background:var(--bg-elev);width:100%;\"></canvas>
        </div>
        <div id=\"patternStats\" style=\"display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;font-size:0.85rem;\">
          <!-- Stats werden eingefüllt -->
        </div>
      </div>
    </div>
  </div>

<script>
const canvas = document.getElementById('powerChart');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('ts');
const selectionOverlay = document.getElementById('selectionOverlay');

// Task progress elements
const activeTaskEl = document.getElementById('activeTask');
const taskNameEl = document.getElementById('taskName');
const taskPercentEl = document.getElementById('taskPercent');
const progressFillEl = document.getElementById('progressFill');

// State für sichtbare Phasen und Daten
let visiblePhases = { total: true, L1: false, L2: false, L3: false };
let currentSeriesData = null;
let availablePhases = [];
let isSelectingRange = false;
let selectionStart = null;
let allPatterns = [];
let currentSortBy = 'seen_count';
let seriesWindow = 360;
let seriesOffset = 0;
const defaultLanguage = document.documentElement.lang === 'en' ? 'en' : 'de';

const I18N = {
  de: {
    pageTitle: 'HA NILM Live-Statistik',
    languageLabel: 'Sprache:',
    runLearningBtn: 'Lernen jetzt ausführen',
    clearReadingsBtn: 'Live-Daten löschen',
    clearPatternsBtn: 'Muster löschen',
    importHistoryBtn: 'HA Verlauf importieren',
    exportDataBtn: '📥 Daten exportieren',
    importDataBtn: '📤 Daten importieren',
    darkModeOn: '☀️ Tagmodus',
    darkModeOff: '🌙 Nachtmodus',
    devicesHeading: 'Erkannte Geräte',
    patternsHeading: 'Gelernte Muster',
    lblCurrentPower: 'Gesamtleistung',
    lblPhaseL1: 'Phase L1',
    lblPhaseL2: 'Phase L2',
    lblPhaseL3: 'Phase L3',
    lblAvgPower: 'Durchschnitt (24h)',
    lblPeakPower: 'Spitze (24h)',
    lblReadingCount: 'Messwerte (24h)',
    lblPatternCount: 'Gelernte Muster',
    thDevice: 'Gerät',
    thStatus: 'Status',
    thPower: 'Leistung (W)',
    thConfidence: 'Konfidenz',
    thCycles: 'Zyklen',
    thRuntime: 'Laufzeit (s)',
    pthType: 'Typ',
    pthGroup: 'Gruppe',
    pthFrequency: 'Häufig.',
    pthInterval: 'Intervall',
    pthTime: 'Uhrzeit',
    pthStability: 'Stabilit.',
    pthConfidence: 'Conf.',
    pthPhases: 'Phasen',
    pthPeak: 'Spitze (W)',
    pthDuration: 'Dauer (s)',
    pthCount: 'Anzahl',
    pthAction: 'Aktion',
    showLabel: 'Anzeigen:',
    phaseTotalBtn: 'Gesamt',
    windowLabel: 'Fenster:',
    olderBtn: '← Älter',
    newerBtn: 'Neuer →',
    rangeBtnIdle: '📍 Bereich markieren',
    rangeBtnActive: '✓ Wähle Bereich aus',
    patternSearchPlaceholder: 'Muster suchen...',
    sortSeenCount: 'Sortieren: Häufigkeit ↓',
    sortConfidence: 'Sortieren: Confidence ↓',
    sortGroupSize: 'Sortieren: Gruppe ↓',
    sortPower: 'Sortieren: Leistung ↓',
    sortDuration: 'Sortieren: Dauer ↓',
    sortStability: 'Sortieren: Stabilität ↓',
    sortInterval: 'Sortieren: Intervall ↓',
    sortId: 'Sortieren: ID ↑',
    loading: 'Lade Live-Daten...',
    waitingApi: 'Warte auf API',
    drawing: 'Zeichne Verlauf und aktualisiere Tabellen...',
    noDataSeries: 'Noch nicht genug Daten für den Verlauf.',
    noPhaseSelected: 'Keine Phase ausgewählt.',
    noDevices: 'Keine Geräte konfiguriert oder noch keine Erkennung.',
    noPatterns: 'Noch keine Muster erkannt.',
    unknown: 'unbekannt',
    maybePrefix: 'evtl.',
    confirmedSuffix: 'bestätigt',
    currentWindow: 'aktuell',
    offset: 'offset',
    sourceReal: 'Quelle: Echte Messkurve',
    sourceLegacy: 'Quelle: Rekonstruierte Kurve (Legacy-Muster ohne Profilpunkte)',
    taskRunning: 'Aufgabe läuft...',
    deleteConfirm: 'Muster {id} wirklich löschen?',
    promptLabel: 'Welches Gerät ist das? (z.B. Kühlschrank)',
    promptHours: 'Wie viele Stunden Verlauf importieren? (1-168)',
    invalidHours: 'Bitte eine Zahl zwischen 1 und 168 eingeben.',
    createPatternSuccess: 'Muster erfolgreich erstellt! ID: {id}',
    createPatternFailed: 'Muster-Erstellung fehlgeschlagen: {err}',
    clearReadingsConfirm: 'Nur Live-Daten (Readings) löschen? Muster bleiben erhalten!',
    clearReadingsStatus: 'Lösche Live-Daten...',
    clearReadingsSuccess: 'Live-Daten gelöscht. Muster bleiben erhalten.',
    clearPatternsConfirm: 'Nur gelernte Muster löschen? Live-Daten bleiben erhalten!',
    clearPatternsStatus: 'Lösche Muster...',
    clearPatternsSuccess: 'Muster gelöscht. Live-Daten bleiben erhalten.',
    deleteFailed: 'Konnte Muster nicht löschen: {err}',
    labelSaveFailed: 'Konnte Label nicht speichern: {err}',
    runLearningStatus: 'Starte Lernlauf...',
    runLearningSuccess: 'Lernlauf abgeschlossen. Zyklen gelernt: {cycles}, Messpunkte: {points}, Zusammengeführt: {merged}, Muster geprüft: {considered}',
    runLearningFailed: 'Lernlauf fehlgeschlagen: {err}',
    importStatus: 'Importiere Verlauf aus HA...',
    importSuccess: 'Import abgeschlossen. Messwerte importiert: {imported}, übersprungen (<=0W): {skipped}',
    importFailed: 'Import fehlgeschlagen: {err}',
    invalidRange: 'Ungültiger Zeitbereich ausgewählt.',
    patternModalTitle: 'Muster-Profil: {name} (ID: {id})',
    unknownPattern: 'Unbekannt',
    statsAvgPower: 'Durchschn. Leistung',
    statsPeakPower: 'Peak-Leistung',
    statsDuration: 'Dauer',
    statsRiseRate: 'Anstiegsrate',
    statsFallRate: 'Fallrate',
    statsDetected: 'Erkannt',
    statsPhase: 'Phase',
    modeSingle: '1-ph',
    modeMulti: '3-ph',
    modeUnknown: '?',
    intervalsTooltip: 'Letzte Intervalle:',
    hoursTooltip: 'Häufigste Stunden:',
    frequencyUnknown: 'unbekannt',
    patternCountLabel: '{total} ({confirmed} bestätigt)'
    ,btnLabel: 'Label'
    ,btnDelete: 'Löschen'
    ,titleRunLearning: 'Lernlauf sofort starten'
    ,titleClearReadings: 'Nur Live-Daten (Readings) löschen'
    ,titleClearPatterns: 'Nur gelernte Muster löschen'
    ,titleImportHistory: 'Verlauf aus Home Assistant importieren'
    ,titleDarkMode: 'Hell/Dunkel umschalten'
    ,titleOlder: 'Ältere Messpunkte anzeigen'
    ,titleNewer: 'Neuere Messpunkte anzeigen'
    ,titleSelectRange: 'Bereich im Graphen markieren und als Muster speichern'
  },
  en: {
    pageTitle: 'HA NILM Live Statistics',
    languageLabel: 'Language:',
    runLearningBtn: 'Run learning now',
    clearReadingsBtn: 'Clear live data',
    clearPatternsBtn: 'Clear patterns',
    importHistoryBtn: 'Import HA history',
    exportDataBtn: '📥 Export data',
    importDataBtn: '📤 Import data',
    darkModeOn: '☀️ Light mode',
    darkModeOff: '🌙 Dark mode',
    devicesHeading: 'Detected devices',
    patternsHeading: 'Learned patterns',
    lblCurrentPower: 'Total power',
    lblPhaseL1: 'Phase L1',
    lblPhaseL2: 'Phase L2',
    lblPhaseL3: 'Phase L3',
    lblAvgPower: 'Average (24h)',
    lblPeakPower: 'Peak (24h)',
    lblReadingCount: 'Readings (24h)',
    lblPatternCount: 'Learned patterns',
    thDevice: 'Device',
    thStatus: 'Status',
    thPower: 'Power (W)',
    thConfidence: 'Confidence',
    thCycles: 'Cycles',
    thRuntime: 'Runtime (s)',
    pthType: 'Type',
    pthGroup: 'Group',
    pthFrequency: 'Freq.',
    pthInterval: 'Interval',
    pthTime: 'Time',
    pthStability: 'Stability',
    pthConfidence: 'Conf.',
    pthPhases: 'Phases',
    pthPeak: 'Peak (W)',
    pthDuration: 'Duration (s)',
    pthCount: 'Count',
    pthAction: 'Action',
    showLabel: 'Show:',
    phaseTotalBtn: 'Total',
    windowLabel: 'Window:',
    olderBtn: '← Older',
    newerBtn: 'Newer →',
    rangeBtnIdle: '📍 Select range',
    rangeBtnActive: '✓ Select range now',
    patternSearchPlaceholder: 'Search patterns...',
    sortSeenCount: 'Sort: frequency ↓',
    sortConfidence: 'Sort: confidence ↓',
    sortGroupSize: 'Sort: group ↓',
    sortPower: 'Sort: power ↓',
    sortDuration: 'Sort: duration ↓',
    sortStability: 'Sort: stability ↓',
    sortInterval: 'Sort: interval ↓',
    sortId: 'Sort: ID ↑',
    loading: 'Loading live data...',
    waitingApi: 'Waiting for API',
    drawing: 'Drawing chart and updating tables...',
    noDataSeries: 'Not enough data for the chart yet.',
    noPhaseSelected: 'No phase selected.',
    noDevices: 'No devices configured or no detections yet.',
    noPatterns: 'No patterns detected yet.',
    unknown: 'unknown',
    maybePrefix: 'maybe',
    confirmedSuffix: 'confirmed',
    currentWindow: 'current',
    offset: 'offset',
    sourceReal: 'Source: Real measured curve',
    sourceLegacy: 'Source: Reconstructed curve (legacy pattern without profile points)',
    taskRunning: 'Task running...',
    deleteConfirm: 'Delete pattern {id}?',
    promptLabel: 'Which device is this? (e.g. fridge)',
    promptHours: 'How many hours of history to import? (1-168)',
    invalidHours: 'Please enter a number between 1 and 168.',
    createPatternSuccess: 'Pattern created successfully! ID: {id}',
    createPatternFailed: 'Pattern creation failed: {err}',
    clearReadingsConfirm: 'Clear only live readings? Learned patterns will be kept.',
    clearReadingsStatus: 'Clearing live data...',
    clearReadingsSuccess: 'Live data cleared. Patterns were kept.',
    clearPatternsConfirm: 'Clear only learned patterns? Live data will be kept.',
    clearPatternsStatus: 'Clearing patterns...',
    clearPatternsSuccess: 'Patterns cleared. Live data was kept.',
    deleteFailed: 'Could not delete pattern: {err}',
    labelSaveFailed: 'Could not save label: {err}',
    runLearningStatus: 'Starting learning run...',
    runLearningSuccess: 'Learning completed. Cycles learned: {cycles}, points: {points}, merged: {merged}, patterns reviewed: {considered}',
    runLearningFailed: 'Learning failed: {err}',
    importStatus: 'Importing history from HA...',
    importSuccess: 'Import completed. Imported points: {imported}, skipped (<=0W): {skipped}',
    importFailed: 'Import failed: {err}',
    invalidRange: 'Invalid time range selected.',
    patternModalTitle: 'Pattern profile: {name} (ID: {id})',
    unknownPattern: 'Unknown',
    statsAvgPower: 'Avg power',
    statsPeakPower: 'Peak power',
    statsDuration: 'Duration',
    statsRiseRate: 'Rise rate',
    statsFallRate: 'Fall rate',
    statsDetected: 'Detected',
    statsPhase: 'Phase',
    modeSingle: '1-ph',
    modeMulti: '3-ph',
    modeUnknown: '?',
    intervalsTooltip: 'Recent intervals:',
    hoursTooltip: 'Most common hours:',
    frequencyUnknown: 'unknown',
    patternCountLabel: '{total} ({confirmed} confirmed)'
    ,btnLabel: 'Label'
    ,btnDelete: 'Delete'
    ,titleRunLearning: 'Start learning run now'
    ,titleClearReadings: 'Delete live readings only'
    ,titleClearPatterns: 'Delete learned patterns only'
    ,titleImportHistory: 'Import history from Home Assistant'
    ,titleDarkMode: 'Toggle light/dark mode'
    ,titleOlder: 'Show older measurement points'
    ,titleNewer: 'Show newer measurement points'
    ,titleSelectRange: 'Mark a chart range and save as pattern'
  }
};

let currentLanguage = localStorage.getItem('dashboardLanguage') || defaultLanguage;
if (currentLanguage !== 'de' && currentLanguage !== 'en') {
  currentLanguage = defaultLanguage;
}

function t(key, params = null) {
  const langDict = I18N[currentLanguage] || I18N.de;
  const fallback = I18N.de[key] || key;
  let text = langDict[key] || fallback;
  if (params && typeof text === 'string') {
    Object.entries(params).forEach(([pKey, pValue]) => {
      text = text.replace(`{${pKey}}`, String(pValue));
    });
  }
  return text;
}

function applyLanguage() {
  document.documentElement.lang = currentLanguage;
  const assignText = (id, key) => {
    const el = document.getElementById(id);
    if (el) el.textContent = t(key);
  };
  const assignTitle = (id, key) => {
    const el = document.getElementById(id);
    if (el) el.title = t(key);
  };

  assignText('pageTitle', 'pageTitle');
  assignText('languageLabel', 'languageLabel');
  assignText('runLearningBtn', 'runLearningBtn');
  assignText('clearReadingsBtn', 'clearReadingsBtn');
  assignText('clearPatternsBtn', 'clearPatternsBtn');
  assignText('importHistoryBtn', 'importHistoryBtn');
  assignText('devicesHeading', 'devicesHeading');
  assignText('patternsHeading', 'patternsHeading');
  assignText('lblCurrentPower', 'lblCurrentPower');
  assignText('lblPhaseL1', 'lblPhaseL1');
  assignText('lblPhaseL2', 'lblPhaseL2');
  assignText('lblPhaseL3', 'lblPhaseL3');
  assignText('lblAvgPower', 'lblAvgPower');
  assignText('lblPeakPower', 'lblPeakPower');
  assignText('lblReadingCount', 'lblReadingCount');
  assignText('lblPatternCount', 'lblPatternCount');
  assignText('thDevice', 'thDevice');
  assignText('thStatus', 'thStatus');
  assignText('thPower', 'thPower');
  assignText('thConfidence', 'thConfidence');
  assignText('thCycles', 'thCycles');
  assignText('thRuntime', 'thRuntime');
  assignText('pthType', 'pthType');
  assignText('pthGroup', 'pthGroup');
  assignText('pthFrequency', 'pthFrequency');
  assignText('pthInterval', 'pthInterval');
  assignText('pthTime', 'pthTime');
  assignText('pthStability', 'pthStability');
  assignText('pthConfidence', 'pthConfidence');
  assignText('pthPhases', 'pthPhases');
  assignText('pthPeak', 'pthPeak');
  assignText('pthDuration', 'pthDuration');
  assignText('pthCount', 'pthCount');
  assignText('pthAction', 'pthAction');
  assignText('showLabel', 'showLabel');
  assignText('phaseTotalBtn', 'phaseTotalBtn');
  assignText('windowLabel', 'windowLabel');
  assignText('olderBtn', 'olderBtn');
  assignText('newerBtn', 'newerBtn');
  assignText('sortSeenCount', 'sortSeenCount');
  assignText('sortConfidence', 'sortConfidence');
  assignText('sortGroupSize', 'sortGroupSize');
  assignText('sortPower', 'sortPower');
  assignText('sortDuration', 'sortDuration');
  assignText('sortStability', 'sortStability');
  assignText('sortInterval', 'sortInterval');
  assignText('sortId', 'sortId');
  assignTitle('runLearningBtn', 'titleRunLearning');
  assignTitle('clearReadingsBtn', 'titleClearReadings');
  assignTitle('clearPatternsBtn', 'titleClearPatterns');
  assignTitle('importHistoryBtn', 'titleImportHistory');
  assignTitle('darkModeToggle', 'titleDarkMode');
  assignTitle('olderBtn', 'titleOlder');
  assignTitle('newerBtn', 'titleNewer');
  assignTitle('selectRangeBtn', 'titleSelectRange');

  const search = document.getElementById('patternSearch');
  if (search) {
    search.placeholder = t('patternSearchPlaceholder');
  }

  const rangeBtn = document.getElementById('selectRangeBtn');
  if (rangeBtn) {
    rangeBtn.textContent = rangeSelection.active ? t('rangeBtnActive') : t('rangeBtnIdle');
  }

  updateDarkModeButtonText();
}

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
    throw new Error(`Invalid JSON response for ${path}: ${body.slice(0, 120)}`);
  }
}

function fmt(v, suffix='') {
  if (v === null || v === undefined) return '-';
  return `${Number(v).toFixed(1)}${suffix}`;
}

function setStatus(message) {
  statusEl.textContent = message;
}

function updateTaskProgress(taskInfo) {
  // Task progress UI is optional; if markup is missing, skip silently.
  if (!activeTaskEl || !taskNameEl || !taskPercentEl || !progressFillEl) {
    return;
  }

  if (!taskInfo || !taskInfo.active) {
    // Hide task progress if no active task
    activeTaskEl.classList.remove('visible');
    return;
  }
  
  // Show and update task progress
  activeTaskEl.classList.add('visible');
  taskNameEl.textContent = taskInfo.name || 'Aufgabe läuft...';
  if (!taskInfo.name) {
    taskNameEl.textContent = t('taskRunning');
  }
  
  const percent = Math.min(100, Math.max(0, taskInfo.progress || 0));
  taskPercentEl.textContent = `${percent.toFixed(0)}%`;
  progressFillEl.style.width = `${percent}%`;
}

async function clearReadingsOnly() {
  const sure = confirm(t('clearReadingsConfirm'));
  if (!sure) return;

  try {
    setStatus(t('clearReadingsStatus'));
    const response = await fetch(apiPath('api/debug/clear-readings'), {
      method: 'POST'
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    alert(t('clearReadingsSuccess'));
    await refresh();
  } catch (err) {
    alert(t('createPatternFailed', { err }));
    setStatus(t('createPatternFailed', { err }));
  }
}

async function clearPatternsOnly() {
  const sure = confirm(t('clearPatternsConfirm'));
  if (!sure) return;

  try {
    setStatus(t('clearPatternsStatus'));
    const response = await fetch(apiPath('api/debug/clear-patterns'), {
      method: 'POST'
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    alert(t('clearPatternsSuccess'));
    await refresh();
  } catch (err) {
    alert(t('createPatternFailed', { err }));
    setStatus(t('createPatternFailed', { err }));
  }
}

async function runLearningNow() {
  try {
    setStatus(t('runLearningStatus'));
    const response = await fetch(apiPath('api/debug/run-learning-now'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}'
    });
    const body = await response.text();
    let payload = null;
    try {
      payload = JSON.parse(body);
    } catch (parseErr) {
      throw new Error(`Ungültige Serverantwort: ${body.slice(0, 180)}`);
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    alert(
      t('runLearningSuccess', {
        cycles: payload.cycles_detected || 0,
        points: payload.points_processed || 0,
        merged: payload.merged || 0,
        considered: payload.patterns_considered || 0,
      })
    );
    await refresh();
  } catch (err) {
    alert(t('runLearningFailed', { err }));
    setStatus(t('runLearningFailed', { err }));
  }
}

async function importHistoryFromHA() {
  const raw = prompt(t('promptHours'), '24');
  if (raw === null) return;

  const hours = Number(raw);
  if (!Number.isFinite(hours) || hours < 1 || hours > 168) {
    alert(t('invalidHours'));
    return;
  }

  try {
    setStatus(t('importStatus'));
    const response = await fetch(apiPath('api/debug/import-history'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: Math.round(hours) })
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }

    alert(t('importSuccess', { imported: payload.imported || 0, skipped: payload.skipped_non_positive || 0 }));
    await refresh();
  } catch (err) {
    alert(t('importFailed', { err }));
    setStatus(t('importFailed', { err }));
  }
}

async function exportData() {
  try {
    setStatus(t('exportDataBtn'));
    const response = await fetch(apiPath('api/debug/export'));
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    
    const filename = `nilm-export-${new Date().toISOString().slice(0,10)}.json`;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    alert(currentLanguage === 'en' 
      ? `Exported: ${data.patterns?.length || 0} patterns, ${data.readings?.length || 0} readings`
      : `Exportiert: ${data.patterns?.length || 0} Muster, ${data.readings?.length || 0} Messwerte`);
  } catch (err) {
    alert(currentLanguage === 'en' ? `Export failed: ${err}` : `Export fehlgeschlagen: ${err}`);
  }
}

function importData() {
  document.getElementById('importDataFile').click();
}

async function handleImportDataFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  
  try {
    setStatus(currentLanguage === 'en' ? 'Importing...' : 'Importiere...');
    const text = await file.text();
    const data = JSON.parse(text);
    
    const response = await fetch(apiPath('api/debug/import'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || `HTTP ${response.status}`);
    }
    
    alert(currentLanguage === 'en'
      ? `Imported: ${result.patterns_imported || 0} patterns, ${result.readings_imported || 0} readings`
      : `Importiert: ${result.patterns_imported || 0} Muster, ${result.readings_imported || 0} Messwerte`);
    await refresh();
  } catch (err) {
    alert(currentLanguage === 'en' ? `Import failed: ${err}` : `Import fehlgeschlagen: ${err}`);
  }
  event.target.value = '';
}

function buildLiveStatusMessage(live) {
  const now = new Date().toLocaleString();
  const power = live && live.current_power_w;
  const sensorTs = live && live.timestamp;

  if (power === null || power === undefined) {
    if (sensorTs) {
      return currentLanguage === 'en'
        ? `Waiting for usable readings (last sensor timestamp: ${sensorTs})`
        : `Warte auf verwertbare Messwerte (letzter Sensor-Zeitstempel: ${sensorTs})`;
    }
    return currentLanguage === 'en'
      ? `Waiting for first readings from sensor (as of: ${now})`
      : `Warte auf erste Messwerte vom Sensor (Stand: ${now})`;
  }

  return currentLanguage === 'en'
    ? `Active: ${fmt(power, ' W')} (updated: ${now})`
    : `Aktiv: ${fmt(power, ' W')} (aktualisiert: ${now})`;
}

function drawChart(series, forceRedraw = false) {
  // Store previous series length to detect changes
  const prevLength = currentSeriesData ? currentSeriesData.length : 0;
  const newLength = series ? series.length : 0;
  
  // Skip redraw if data hasn't changed (same length and last point identical)
  if (!forceRedraw && prevLength === newLength && newLength > 0 && currentSeriesData) {
    const lastOld = currentSeriesData[prevLength - 1];
    const lastNew = series[newLength - 1];
    if (lastOld && lastNew && 
        lastOld.timestamp === lastNew.timestamp && 
        lastOld.power_w === lastNew.power_w) {
      return; // No change detected - skip redraw to prevent flickering
    }
  }
  
  currentSeriesData = series;
  const w = canvas.width, h = canvas.height;
  const leftPad = 10;
  const rightPad = 10;
  const topPad = 20;
  const bottomPad = 36; // Reserve space for time scale labels
  const plotHeight = h - topPad - bottomPad;

  // Use requestAnimationFrame for smooth rendering
  requestAnimationFrame(() => {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);

  if (!series || series.length < 2) {
    ctx.fillStyle = '#667085';
    ctx.font = '14px Segoe UI';
    ctx.fillText(t('noDataSeries'), 20, 36);
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
    ctx.fillText(t('noPhaseSelected'), 20, 36);
    return;
  }

  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const span = Math.max(max - min, 1);

  // Gitterlinien
  ctx.strokeStyle = '#d0d5dd';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = topPad + (i * plotHeight / 4);
    ctx.beginPath(); ctx.moveTo(leftPad, y); ctx.lineTo(w - rightPad, y); ctx.stroke();
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
      const x = leftPad + (i * (w - leftPad - rightPad) / (series.length - 1));
      const y = topPad + plotHeight - ((point.power_w - min) / span) * plotHeight;
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
        const x = leftPad + (i * (w - leftPad - rightPad) / (series.length - 1));
        const y = topPad + plotHeight - ((value - min) / span) * plotHeight;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
  });

  // Zeitachse unten (Start/Ende + Zwischen-Ticks)
  const parseTs = (raw) => {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const fmtTime = (d, includeDate) => {
    if (!d) return '--:--';
    if (includeDate) {
      return d.toLocaleString([], {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    }
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const firstTs = parseTs(series[0] && series[0].timestamp);
  const lastTs = parseTs(series[series.length - 1] && series[series.length - 1].timestamp);

  ctx.strokeStyle = '#98a2b3';
  ctx.lineWidth = 1;
  const axisY = h - bottomPad + 10;
  ctx.beginPath();
  ctx.moveTo(leftPad, axisY);
  ctx.lineTo(w - rightPad, axisY);
  ctx.stroke();

  const rangeMs = (firstTs && lastTs) ? Math.max(lastTs.getTime() - firstTs.getTime(), 1) : 0;
  const includeDate = rangeMs >= 24 * 60 * 60 * 1000;
  const minLabelSpacing = includeDate ? 110 : 72;
  const usableWidth = Math.max(w - leftPad - rightPad, 1);
  const dynamicTicks = Math.floor(usableWidth / minLabelSpacing);
  const tickCount = Math.min(8, Math.max(2, dynamicTicks));
  ctx.fillStyle = '#667085';
  ctx.font = '11px Segoe UI';
  ctx.textAlign = 'center';

  for (let i = 0; i <= tickCount; i++) {
    const t = i / tickCount;
    const x = leftPad + t * (w - leftPad - rightPad);
    ctx.beginPath();
    ctx.moveTo(x, axisY);
    ctx.lineTo(x, axisY + 5);
    ctx.stroke();

    let label = '--:--';
    if (firstTs && lastTs) {
      const ts = new Date(firstTs.getTime() + (lastTs.getTime() - firstTs.getTime()) * t);
      label = fmtTime(ts, includeDate);
    }
    ctx.fillText(label, x, axisY + 17);
  }

  // Legende
  ctx.fillStyle = '#667085';
  ctx.font = '12px Segoe UI';
  ctx.textAlign = 'left';
  ctx.fillText(`min ${min.toFixed(1)}W`, 12, 14);
  ctx.textAlign = 'right';
  ctx.fillText(`max ${max.toFixed(1)}W`, w - 12, 14);
  }); // End of requestAnimationFrame
}

function renderDevices(devices) {
  const tbody = document.getElementById('deviceRows');
  tbody.innerHTML = '';
  const names = Object.keys(devices || {});
  if (!names.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="6">${t('noDevices')}</td>`;
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
    tr.innerHTML = `<td colspan="16">${t('noPatterns')}</td>`;
    tbody.appendChild(tr);
    return;
  }

  patterns.forEach(p => {
    const tr = document.createElement('tr');
    const label = p.user_label || '-';
    const candidate = p.candidate_name || p.suggestion_type || t('unknown');
    const typeText = p.is_confirmed ? candidate : `${t('maybePrefix')} ${candidate}`;
    const phaseModeRaw = String(p.phase_mode || 'unknown');
    const phaseModeShort = phaseModeRaw === 'single_phase' ? '1-ph' : (phaseModeRaw === 'multi_phase' ? '3-ph' : '?');
    const phaseLabel = String(p.phase || 'L1');
    const phaseDisplay = `${phaseLabel}<br><span style="font-size:0.75rem;color:#999;">${phaseModeShort}</span>`;
    
    // Häufigkeits- und Stabilitäts-Indikatoren
    const frequency = p.frequency_label || t('frequencyUnknown');
    const stability = p.stability_score ?? 50;
    const stabilityColor = stability >= 80 ? '#28a745' : (stability >= 60 ? '#ffc107' : '#dc3545');
    const stabilityBar = `<div style="background:#e9ecef;border-radius:3px;height:16px;overflow:hidden;position:relative;"><div style="background:${stabilityColor};width:${stability}%;height:100%;">&nbsp;</div><span style="position:absolute;top:0;left:2px;font-size:0.75rem;color:#000;line-height:16px;font-weight:bold;">${stability}%</span></div>`;
    const confidence = Number.isFinite(Number(p.confidence_score)) ? Number(p.confidence_score) : 50;
    const confColor = confidence >= 80 ? '#2e7d32' : (confidence >= 60 ? '#f9a825' : '#c62828');
    const confidenceChip = `<span style="display:inline-block;padding:2px 6px;border-radius:999px;font-size:0.78rem;font-weight:600;background:rgba(0,0,0,0.04);color:${confColor};">${confidence.toFixed(0)}%</span>`;
    const groupLabel = String(p.device_group_label || candidate || t('unknown'));
    const groupSize = Number.isFinite(Number(p.device_group_size)) ? Number(p.device_group_size) : 1;
    const groupChip = `<span style="display:inline-block;padding:2px 6px;border-radius:999px;font-size:0.76rem;font-weight:600;background:rgba(3,169,244,0.12);color:#0277bd;">${groupLabel} (${groupSize})</span>`;
    
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
          intervalTooltip = `${t('intervalsTooltip')}<br>${intervalList}`;
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
          timeTooltip = `${t('hoursTooltip')}<br>${top3}`;
        }
      } catch (e) {}
    }
    
    // Multi-Mode Info (intelligent!)
    const modes = p.operating_modes || [];
    // Intervall-Zelle mit Tooltip
    const intervalCell = intervalTooltip 
      ? `<td><div class="tooltip" style="font-size:0.85rem;color:#03a9f4;font-weight:600;">${intervalText}<span class="tooltiptext">${intervalTooltip}</span></div></td>`
      : `<td style="font-size:0.85rem;color:#03a9f4;font-weight:600;">${intervalText}</td>`;
    
    // Uhrzeit-Zelle mit Tooltip
    const timeCell = timeTooltip
      ? `<td><div class="tooltip" style="font-size:0.85rem;color:#666;">${timeText}<span class="tooltiptext">${timeTooltip}</span></div></td>`
      : `<td style="font-size:0.85rem;color:#666;">${timeText}</td>`;
    
    tr.innerHTML = `<td>${p.id}</td><td>${typeText}</td><td>${label}</td><td>${groupChip}</td><td style="font-size:0.85rem;color:#666;">${frequency}</td>${intervalCell}${timeCell}<td style="padding:4px 2px;">${stabilityBar}</td><td>${confidenceChip}</td><td>${phaseDisplay}</td><td>${fmt(p.avg_power_w)}</td><td>${fmt(p.peak_power_w)}</td><td>${fmt(p.duration_s)}</td><td>${p.seen_count ?? 0}</td><td><button data-id="${p.id}" class="btn-label">${t('btnLabel')}</button> <button data-id="${p.id}" class="btn-delete">${t('btnDelete')}</button></td>`;
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      showPatternChart(p);
    });
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('button.btn-label[data-id]').forEach(btn => {
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
        alert(t('labelSaveFailed', { err }));
      }
    });
  });

  tbody.querySelectorAll('button.btn-delete[data-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.getAttribute('data-id'));
      if (!confirm(t('deleteConfirm', { id }))) return;
      try {
        const res = await fetch(apiPath(`api/patterns/${id}/delete`), {
          method: 'POST'
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await refresh();
      } catch (err) {
        alert(t('deleteFailed', { err }));
      }
    });
  });
}

async function refresh() {
  try {
    setStatus(t('loading'));
    const [summaryRes, seriesRes, liveRes, patternsRes] = await Promise.all([
      fetchJson('api/summary'),
      fetchJson(`api/series?limit=${seriesWindow}&offset=${seriesOffset}`),
      fetchJson('api/live'),
      fetchJson('api/patterns')
    ]);

    const summary = summaryRes;
    const series = seriesRes;
    const live = liveRes;
    const patterns = patternsRes;

    // Update task progress if available
    if (live && live.task) {
      updateTaskProgress(live.task);
    } else {
      updateTaskProgress(null); // Hide if no task
    }

    document.getElementById('current_power').textContent = fmt(live.current_power_w, ' W');
    document.getElementById('avg_power').textContent = fmt(summary.avg_power_w, ' W');
    document.getElementById('peak_power').textContent = fmt(summary.max_power_w, ' W');
    document.getElementById('reading_count').textContent = String(summary.reading_count ?? 0);
    
    // Muster-Statistik
    const patternArray = Array.isArray(patterns) ? patterns : [];
    const confirmedCount = patternArray.filter(p => p.is_confirmed).length;
    const totalCount = patternArray.length;
    document.getElementById('pattern_count').textContent = totalCount > 0 
      ? t('patternCountLabel', { total: totalCount, confirmed: confirmedCount })
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

    setStatus(t('drawing'));
    drawChart(series.points || []);
    renderDevices(live.devices || {});
    renderPatterns(Array.isArray(patterns) ? patterns : []);
    const windowInfo = document.getElementById('windowInfo');
    if (windowInfo) {
      const hours = Math.round((seriesWindow / 120.0) * 10) / 10;
      windowInfo.textContent = `${hours}h, ${seriesOffset === 0 ? t('currentWindow') : `${t('offset')} ${seriesOffset}`}`;
    }
    setStatus(buildLiveStatusMessage(live));
  } catch (err) {
    setStatus(`${t('waitingApi')}: ${err}`);
  }
}

// Phase-Toggle Event-Handler
document.querySelectorAll('.phase-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const phase = btn.getAttribute('data-phase');
    visiblePhases[phase] = !visiblePhases[phase];
    btn.classList.toggle('active', visiblePhases[phase]);
    if (currentSeriesData) {
      // Force redraw on visibility changes so the chart updates immediately.
      drawChart(currentSeriesData, true);
    }
  });
});

// Bereichsauswahl-Funktionalität
let rangeSelection = { active: false, startX: null, startIdx: null };

document.getElementById('selectRangeBtn').addEventListener('click', () => {
  rangeSelection.active = !rangeSelection.active;
  const btn = document.getElementById('selectRangeBtn');
  btn.classList.toggle('active', rangeSelection.active);
  btn.textContent = rangeSelection.active ? t('rangeBtnActive') : t('rangeBtnIdle');
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
  const label = prompt(t('promptLabel'));
  if (!label) return;
  
  const startPoint = currentSeriesData[startIdx];
  const endPoint = currentSeriesData[endIdx];
  
  if (!startPoint || !endPoint || !startPoint.timestamp || !endPoint.timestamp) {
    alert(t('invalidRange'));
    return;
  }
  
  try {
    setStatus(t('drawing'));
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
    
    alert(t('createPatternSuccess', { id: result.pattern_id || '?' }));
    rangeSelection.active = false;
    document.getElementById('selectRangeBtn').classList.remove('active');
    document.getElementById('selectRangeBtn').textContent = t('rangeBtnIdle');
    canvas.style.cursor = 'default';
    await refresh();
  } catch (err) {
    alert(t('createPatternFailed', { err }));
    setStatus(t('createPatternFailed', { err }));
  }
}

function showPatternChart(pattern) {
  const modal = document.getElementById('patternModal');
  modal.style.display = 'flex';
  document.getElementById('patternModalTitle').textContent = 
    t('patternModalTitle', { name: pattern.user_label || pattern.suggestion_type || t('unknownPattern'), id: pattern.id });
  
  renderPatternChart(pattern);
  renderPatternStats(pattern);
}

function renderPatternChart(pattern) {
  const canvas = document.getElementById('patternChart');
  const ctx = canvas.getContext('2d');
  const sourceEl = document.getElementById('patternProfileSource');
  const width = canvas.width;
  const height = canvas.height;
  const padding = 40;

  const styles = getComputedStyle(document.documentElement);
  const bgColor = styles.getPropertyValue('--bg-elev').trim() || '#ffffff';
  const lineColor = styles.getPropertyValue('--line').trim() || '#cccccc';
  const inkColor = styles.getPropertyValue('--ink').trim() || '#000000';
  const accentColor = '#03a9f4';

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, width, height);

  const peak = pattern.peak_power_w || 1000;
  const duration = pattern.duration_s || 60;
  const riseRate = pattern.rise_rate_w_per_s || peak / 5;
  const fallRate = pattern.fall_rate_w_per_s || peak / 5;
  const storedProfile = Array.isArray(pattern.profile_points) ? pattern.profile_points : [];

  let chartDuration = duration;
  let chartPeak = peak;
  let chartPoints = [];
  let usedStoredProfile = false;

  if (storedProfile.length >= 2) {
    const normalized = storedProfile
      .map(p => ({ t_s: Number(p.t_s), power_w: Number(p.power_w) }))
      .filter(p => Number.isFinite(p.t_s) && Number.isFinite(p.power_w))
      .sort((a, b) => a.t_s - b.t_s);

    if (normalized.length >= 2) {
      chartDuration = Math.max(1, normalized[normalized.length - 1].t_s);
      chartPeak = Math.max(Math.max(...normalized.map(p => p.power_w)), 1);
      chartPoints = normalized;
      usedStoredProfile = true;
    }
  }

  if (sourceEl) {
    sourceEl.textContent = usedStoredProfile
      ? `${t('sourceReal')} (${chartPoints.length} points)`
      : t('sourceLegacy');
  }

  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding, height - padding);
  ctx.lineTo(width - 20, height - padding);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(padding, height - padding);
  ctx.lineTo(padding, 20);
  ctx.stroke();

  ctx.strokeStyle = 'rgba(128, 128, 128, 0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 5; i++) {
    const y = height - padding - (i * (height - padding - 20) / 5);
    ctx.beginPath();
    ctx.moveTo(padding, y);
    ctx.lineTo(width - 20, y);
    ctx.stroke();
  }

  ctx.fillStyle = inkColor;
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'right';
  for (let i = 0; i <= 5; i++) {
    const watts = Math.round(i * chartPeak / 5);
    const y = height - padding - (i * (height - padding - 20) / 5);
    ctx.fillText(watts + 'W', padding - 5, y + 4);
  }

  ctx.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const timeS = Math.round(i * chartDuration / 4);
    const x = padding + (i * (width - padding - 20) / 4);
    ctx.fillText(timeS + 's', x, height - padding + 15);
  }

  const points = [];
  let riseEndX = null;
  let fallStartX = null;
  let peakY = null;

  if (chartPoints.length >= 2) {
    chartPoints.forEach(point => {
      const x = padding + (point.t_s / chartDuration) * (width - padding - 20);
      const y = height - padding - (point.power_w / chartPeak) * (height - padding - 20);
      points.push({ x, y });
    });
    const maxPoint = chartPoints.reduce((best, item) => (item.power_w > best.power_w ? item : best), chartPoints[0]);
    peakY = height - padding - (maxPoint.power_w / chartPeak) * (height - padding - 20);
    riseEndX = padding + (maxPoint.t_s / chartDuration) * (width - padding - 20);
    fallStartX = riseEndX;
  } else {
    const riseTime = riseRate > 0 ? peak / riseRate : duration / 3;
    const fallTime = fallRate > 0 ? peak / fallRate : duration / 3;
    const plateauTime = Math.max(0, duration - riseTime - fallTime);
    const samples = 200;

    for (let i = 0; i <= samples; i++) {
      const t = (i / samples) * duration;
      let power;
      if (t < riseTime) {
        power = (t / riseTime) * peak;
      } else if (t < riseTime + plateauTime) {
        power = peak;
      } else {
        const fallProgress = (t - riseTime - plateauTime) / fallTime;
        power = peak * Math.max(0, 1 - fallProgress);
      }
      const x = padding + (t / duration) * (width - padding - 20);
      const y = height - padding - (power / peak) * (height - padding - 20);
      points.push({ x, y });
    }

    riseEndX = padding + (riseTime / duration) * (width - padding - 20);
    peakY = height - padding - (peak / peak) * (height - padding - 20);
    fallStartX = padding + ((riseTime + plateauTime) / duration) * (width - padding - 20);
  }

  ctx.strokeStyle = accentColor;
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((p, idx) => {
    if (idx === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  });
  ctx.stroke();

  ctx.fillStyle = 'rgba(3, 169, 244, 0.15)';
  ctx.beginPath();
  points.forEach((p, idx) => {
    if (idx === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  });
  ctx.lineTo(points[points.length - 1].x, height - padding);
  ctx.lineTo(points[0].x, height - padding);
  ctx.fill();

  if (riseEndX !== null && fallStartX !== null && peakY !== null) {
    ctx.fillStyle = '#0288d1';
    ctx.fillRect(riseEndX - 3, peakY - 3, 6, 6);
    ctx.fillRect(fallStartX - 3, peakY - 3, 6, 6);
  }
}

function renderPatternStats(pattern) {
  const statsDiv = document.getElementById('patternStats');
  const phaseText = String(pattern.phase_mode || 'unknown') === 'single_phase'
    ? t('modeSingle')
    : (String(pattern.phase_mode || 'unknown') === 'multi_phase' ? t('modeMulti') : t('modeUnknown'));
  statsDiv.innerHTML = `
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsAvgPower')}</div>
      <div style="font-weight:600;font-size:1rem;">${fmt(pattern.avg_power_w)}</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsPeakPower')}</div>
      <div style="font-weight:600;font-size:1rem;">${fmt(pattern.peak_power_w)}</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsDuration')}</div>
      <div style="font-weight:600;font-size:1rem;">${fmt(pattern.duration_s)}s</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsRiseRate')}</div>
      <div style="font-weight:600;font-size:1rem;">${fmt(pattern.rise_rate_w_per_s || 0)}W/s</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsFallRate')}</div>
      <div style="font-weight:600;font-size:1rem;">${fmt(pattern.fall_rate_w_per_s || 0)}W/s</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsDetected')}</div>
      <div style="font-weight:600;font-size:1rem;">${pattern.seen_count || 0}x</div>
    </div>
    <div style="padding:8px;background:var(--bg-elev);border-radius:6px;">
      <div style="color:var(--muted);font-size:0.75rem;">${t('statsPhase')}</div>
      <div style="font-weight:600;font-size:1rem;">${phaseText}</div>
    </div>
  `;
}

refresh();
setInterval(refresh, 5000);
document.getElementById('runLearningBtn').addEventListener('click', runLearningNow);
document.getElementById('clearReadingsBtn').addEventListener('click', clearReadingsOnly);
document.getElementById('clearPatternsBtn').addEventListener('click', clearPatternsOnly);
document.getElementById('importHistoryBtn').addEventListener('click', importHistoryFromHA);
document.getElementById('exportDataBtn').addEventListener('click', exportData);
document.getElementById('importDataBtn').addEventListener('click', importData);
document.getElementById('importDataFile').addEventListener('change', handleImportDataFile);
document.getElementById('darkModeToggle').addEventListener('click', toggleDarkMode);
document.getElementById('windowSelect').addEventListener('change', async (e) => {
  const val = Number(e.target.value);
  if (Number.isFinite(val) && val >= 60) {
    seriesWindow = Math.round(val);
    seriesOffset = 0;
    await refresh();
  }
});
document.getElementById('olderBtn').addEventListener('click', async () => {
  seriesOffset += seriesWindow;
  await refresh();
});
document.getElementById('newerBtn').addEventListener('click', async () => {
  seriesOffset = Math.max(0, seriesOffset - seriesWindow);
  await refresh();
});
document.getElementById('patternSearch').addEventListener('input', filterAndSortPatterns);
document.getElementById('patternSort').addEventListener('change', (e) => {
  currentSortBy = e.target.value;
  filterAndSortPatterns();
});

function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark-mode');
  localStorage.setItem('darkMode', isDark);
  updateDarkModeButtonText();
}

function updateDarkModeButtonText() {
  const btn = document.getElementById('darkModeToggle');
  if (!btn) return;
  const isDark = document.documentElement.classList.contains('dark-mode');
  btn.textContent = isDark ? t('darkModeOn') : t('darkModeOff');
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

const languageSelect = document.getElementById('languageSelect');
if (languageSelect) {
  languageSelect.value = currentLanguage;
  languageSelect.addEventListener('change', (e) => {
    const selected = String(e.target.value || '').toLowerCase();
    currentLanguage = selected === 'en' ? 'en' : 'de';
    localStorage.setItem('dashboardLanguage', currentLanguage);
    applyLanguage();
    refresh();
  });
}

applyLanguage();


</script>
</body>
</html>
""".replace("__DEFAULT_LANG__", lang)


class StatsWebServer:
    """Embedded HTTP server exposing stats APIs and a lightweight dashboard."""

    def __init__(
        self,
        host: str,
        port: int,
        get_live_data: Callable[[], Dict],
        get_summary_data: Callable[[], Dict],
        get_series_data: Callable[[int, int], List[Dict]],
        get_patterns_data: Optional[Callable[[], List[Dict]]] = None,
        set_pattern_label: Optional[Callable[[int, str], bool]] = None,
        delete_pattern: Optional[Callable[[int], bool]] = None,
        flush_debug_data: Optional[Callable[[bool], Dict]] = None,
        clear_readings_only: Optional[Callable[[], Dict]] = None,
        clear_patterns_only: Optional[Callable[[], Dict]] = None,
        run_learning_now: Optional[Callable[[], Dict]] = None,
        import_history_from_ha: Optional[Callable[[int], Dict]] = None,
        create_pattern_from_range: Optional[Callable[[str, str, str], Dict]] = None,
        language: str = "de",
        storage = None,
    ):
        self.host = host
        self.port = int(port)
        self.get_live_data = get_live_data
        self.get_summary_data = get_summary_data
        self.get_series_data = get_series_data
        self.get_patterns_data = get_patterns_data
        self.set_pattern_label = set_pattern_label
        self.delete_pattern = delete_pattern
        self.flush_debug_data = flush_debug_data
        self.clear_readings_only = clear_readings_only
        self.clear_patterns_only = clear_patterns_only
        self.run_learning_now = run_learning_now
        self.import_history_from_ha = import_history_from_ha
        self.create_pattern_from_range = create_pattern_from_range
        self.language = "en" if str(language).strip().lower() == "en" else "de"
        self.storage = storage
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
        html = _html_page(parent.language)

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
                    offset_raw = (query.get("offset") or ["0"])[0]
                    try:
                        limit = max(10, min(int(limit_raw), 2000))
                    except ValueError:
                        limit = 300
                    try:
                        offset = max(0, int(offset_raw))
                    except ValueError:
                        offset = 0
                    self._send_json({"points": parent.get_series_data(limit, offset)})
                    return

                if parsed.path == "/api/patterns":
                    if parent.get_patterns_data:
                        self._send_json(parent.get_patterns_data())
                    else:
                        self._send_json([])
                    return

                if parsed.path == "/api/debug/export":
                    if not parent.storage:
                        self._send_json({"error": "storage not enabled"}, status=400)
                        return
                    
                    try:
                        data = parent.storage.export_data()
                        self._send_json(data)
                    except Exception as e:
                        logger.error(f"Export failed: {e}", exc_info=True)
                        self._send_json({"error": str(e)}, status=500)
                    return

                self._send_json({"error": "not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path == "/api/debug/run-learning-now":
                    if not parent.run_learning_now:
                        self._send_json({"error": "manual learning trigger not enabled"}, status=400)
                        return

                    try:
                        result = parent.run_learning_now()
                    except Exception as e:
                        self._send_json({"ok": False, "error": f"learning execution failed: {e}"}, status=500)
                        return

                    if not isinstance(result, dict):
                        self._send_json({"ok": False, "error": "invalid learning response"}, status=500)
                        return
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

                if parsed.path.startswith("/api/patterns/") and parsed.path.endswith("/delete"):
                    if not parent.delete_pattern:
                        self._send_json({"error": "pattern deletion not enabled"}, status=400)
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

                    ok = parent.delete_pattern(pattern_id)
                    if not ok:
                        self._send_json({"error": "failed to delete pattern"}, status=500)
                        return

                    self._send_json({"ok": True})
                    return

                if parsed.path == "/api/debug/clear-readings":
                    if not parent.clear_readings_only:
                        self._send_json({"error": "clear readings not enabled"}, status=400)
                        return

                    result = parent.clear_readings_only()
                    if not result.get("ok"):
                        self._send_json(result, status=500)
                        return

                    self._send_json(result)
                    return

                if parsed.path == "/api/debug/clear-patterns":
                    if not parent.clear_patterns_only:
                        self._send_json({"error": "clear patterns not enabled"}, status=400)
                        return

                    result = parent.clear_patterns_only()
                    if not result.get("ok"):
                        self._send_json(result, status=500)
                        return

                    self._send_json(result)
                    return

                if parsed.path == "/api/debug/export":
                    if not parent.storage:
                        self._send_json({"error": "storage not enabled"}, status=400)
                        return
                    
                    try:
                        data = parent.storage.export_data()
                        self._send_json(data)
                    except Exception as e:
                        logger.error(f"Export failed: {e}", exc_info=True)
                        self._send_json({"error": str(e)}, status=500)
                    return

                if parsed.path == "/api/debug/import":
                    if not parent.storage:
                        self._send_json({"error": "storage not enabled"}, status=400)
                        return
                    
                    try:
                        length = int(self.headers.get("Content-Length", "0") or 0)
                        raw = self.rfile.read(length) if length > 0 else b"{}"
                        data = json.loads(raw.decode("utf-8")) if raw else {}
                        result = parent.storage.import_data(data)
                        self._send_json(result)
                    except Exception as e:
                        logger.error(f"Import failed: {e}", exc_info=True)
                        self._send_json({"ok": False, "error": str(e)}, status=500)
                    return

                self._send_json({"error": "not found"}, status=404)

            def log_message(self, format: str, *args):
                return

        return Handler
