# Release Notes

> ⚠️ **EXPERIMENTELLES PROJEKT**: Dieses Add-on ist in aktiver Entwicklung (BETA-Status). Features können unvollständig sein, Breaking Changes auftreten. Nutze es zum Experimentieren und Testen, nicht für kritische Produktionsumgebungen.

---

# Release 0.6.13 (BETA)

## Store Kurztext
- **Daten-Export/Import**: Teile deine Mustersignaturen und Messwerte mit externen KI-Tools zur Diagnostik und Optimierung – für besseres Tuning und Fehlersuche!

## Highlights
- Neue Buttons: `📥 Daten exportieren` / `📤 Daten importieren` im Dashboard
- Export als JSON mit allen Mustern und historischen Messwerten
- Ermöglicht Datenanalyse durch externe KI und manuelle Optimierung
- SQLite Batch-Write Optimierung: 90-95% schnellere Datenbankschreibvorgänge
- Unterstützt Debugging und Datenfreigabe für Community-Support
- Bilingual: DE/EN Unterstützung in UI

## Use Cases
- Teile Muster-Exporte mit Discord/Community für Hilfe
- Analyse durch GPT/Claude für Pattern-Optimierung
- Backup und Migration von gelernten Signaturen
- Performance-Tuning durch Datenanalyse

---

# Release 0.6.12 (BETA)

## Store Kurztext
- **Gelernte Geräte sind jetzt live sichtbar**: Muster erscheinen automatisch als Geräte-Einträge im Dashboard – echtes Self-Learning ohne Konfiguration!

## Highlights
- Automatische Gerätesynthese aus repräsentativen Mustergruppen
- Live-Status pro Gerät wird aus aktueller Phasenleistung geschätzt
- Intelligente Filterung: zu unsichere/seltene Muster ausgeblendet
- Robuste Benennung bei Kollisionen mit manuellen Detektoren (`(learned)`-Suffix)
- Dashboard wird sauberer und aussagekräftiger ohne manuelle Konfiguration

---

# Release 0.6.11 (BETA)

## Store Kurztext
- **UI Sprach-Hotfix**: Auch die oberen Dashboard-Karten schalten jetzt korrekt zwischen Deutsch und Englisch um.

## Highlights
- Summary-Karten an i18n angebunden: Gesamtleistung, Phasen, Durchschnitt, Spitze, Messwerte, Gelernte Muster

---

# Release 0.6.10 (BETA)

## Store Kurztext
- **Speichert wieder sichtbar im klassischen Add-on-Pfad**: `/addon_configs/ha_nilm_detector`.
- **Automatische Uebernahme aus `/data`**: Vorhandene DBs/Logs werden beim Start migriert, wenn im Ziel noch nichts liegt.

## Highlights
- Neue Default-Pfade: `/addon_configs/ha_nilm_detector/nilm_live.sqlite3`, `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3`, `/addon_configs/ha_nilm_detector/nilm.log`
- Recovery/Migration prueft jetzt sowohl alte `/data`- als auch `/addon_configs`-Dateien

---

# Release 0.6.9 (BETA)

## Store Kurztext
- **DE/EN UI sauberer**: Weitere Dialoge, Tooltips und Pattern-Details sind jetzt korrekt sprachumschaltbar.
- **Legacy-Pfad kompatibel**: `/addon_configs/ha_nilm_detector` wird beim Start best-effort bereitgestellt.

## Highlights
- i18n erweitert fuer Pattern-Aktionen, Statusmeldungen, Import/Lernlauf-Dialogs und Modal-Statistiken
- Tooltip-Titel der Aktionsbuttons werden zur Laufzeit nach Sprache gesetzt
- Verbesserte Legacy-Ordner-Kompatibilitaet fuer DB-Recovery-Workflows

---

# Release 0.6.8 (BETA)

## Store Kurztext
- **Hotfix Muster weg nach Update**: Wenn die aktuelle Pattern-DB leer ist, werden Legacy-Muster automatisch aus `/addon_configs/ha_nilm_detector/` wiederhergestellt.
- **Sicherer Fallback**: Recovery prueft `nilm_patterns.sqlite3` und danach `nilm_live.sqlite3`.
- **Keine manuelle SQL-Aktion noetig**: Muster werden beim Start automatisch nachgeladen.

## Highlights
- Neuer Startup-Recovery-Pfad in `SQLiteStore.connect()`
- Nur aktiv, wenn Ziel-DB leer ist (keine Ueberschreibung bestehender Muster)

---

# Release 0.6.7 (BETA)

## Store Kurztext
- **Device-Gruppen aktiv**: Mehrere Pattern eines Geraets werden gruppiert und konsistenter benannt.
- **Variable Lasten robuster**: Betriebsmodi werden beim Lernen als Cluster gepflegt statt zu stark zu fragmentieren.
- **UI-Transparenz**: Neue Gruppen-Spalte + Sortierung `Gruppe ↓` in der Muster-Tabelle.

## Highlights
- Backend liefert `device_group_key`, `device_group_label`, `device_group_size`
- Gruppenbasiertes Voting in der Label-Suggestion
- Operating-Mode-Merge im Lernpfad (`operating_modes`, `has_multiple_modes`)

---

# Release 0.6.6 (BETA)

## Store Kurztext
- **Confidence sichtbar**: Die Muster-Tabelle zeigt jetzt pro Pattern einen klaren Confidence-Wert (0-100%).
- **Direkt sortierbar**: Neue Sortierung `Confidence ↓` fuer schnelle Qualitaetspruefung.
- **Plausible Berechnung**: Score kombiniert Pattern-Qualitaet und Pattern-Reife (`seen_count`).

## Highlights
- Backend liefert neuen Wert `confidence_score` in `/api/patterns`
- Web-UI zeigt Confidence als farbigen Prozent-Indicator
- Roadmap-Task "sichtbarer Confidence-Score" als umgesetzt markiert

---

# Release 0.6.5 (BETA)

## Store Kurztext
- **Bessere Muster-Namen**: Vorschlaege bewerten jetzt zusaetzlich Lastanstieg (Delta zur Basis), typische Spitzenform und Laufzeiten.
- **Weniger Fehlzuordnung**: Runtime-/Spike-Konsistenz im Voting macht Labels plausibler bei aehnlichen Leistungsniveaus.
- **Sprache einstellbar**: Dashboard unterstuetzt jetzt Deutsch und Englisch (`language: de|en`).

## Highlights
- Neue Distanz-Merkmale: `incremental_rise_w` und Peak-Zeitpunkt im Zyklus
- Erweiterte Label-Votes mit Laufzeit- und `peak_to_avg_ratio`-Konsistenz
- Add-on Option `language` + UI-Sprachumschalter (persistiert im Browser)
- Dokumentation und Roadmap auf Version 0.6.5 aktualisiert

---

# Release 0.6.4 (BETA)

## Store Kurztext
- **Muster bleiben erhalten**: Standard-Speicherpfade liegen jetzt unter `/data`, damit gelernte Patterns Neustarts ueberstehen.
- **Sichere Umstellung**: Legacy-Dateien aus `/addon_configs/ha_nilm_detector/` werden bei Bedarf automatisch nach `/data` migriert.
- **DB-Konsistenz**: SQLite-`-wal`/`-shm` Dateien werden in der Migration mitkopiert.

## Highlights
- Neue Default-Pfade: `/data/nilm_live.sqlite3`, `/data/nilm_patterns.sqlite3`, `/data/nilm.log`
- Automatische Migration nur dann, wenn am Ziel noch keine Datei existiert (keine Ueberschreibung bestehender Daten)
- Verbessert Upgrade-Verhalten fuer bestehende Installationen mit alten Pfaden

---

# Release 0.6.3 (BETA)

## Store Kurztext
- **Selbstlernen verbessert**: Replay lernt jetzt phasenbasiert (L1/L2/L3) statt ueber aggregierte Total-Leistung.
- **Robusteres Matching**: Kurvenform-Distanz aus echten Profilpunkten verbessert die Pattern-Zuordnung.
- **Weniger Musterrauschen**: Qualitaetsfilter blockiert unzuverlaessige Zyklen vor dem Lernen.

## Highlights
- Per-Phase Replay-Learner analog zum Live-Learning-Pfad
- Adaptive Match-Toleranz nach Pattern-Reife (`seen_count`)
- Neue persistente Pattern-Qualitaet `quality_score_avg` als Feedback-Signal
- Vorschlagslogik mit Qualitaetsgewicht + Zeitprior (`avg_hour_of_day`) fuer plausiblere Selbstklassifikation

---

# Release 0.6.2 (BETA)

## Store Kurztext
- **Echte Musterkurven**: Gelernte Patterns speichern jetzt echte Profilpunkte und zeigen diese im Modal.
- **Transparenz im UI**: Modal kennzeichnet klar `Echte Messkurve` vs `Rekonstruierte Kurve (Legacy)`.
- **Stabileres Rendering**: Chart-Marker-Logik fuer gespeicherte Profile robuster gemacht.

## Highlights
- Neue persistente Pattern-Spalte `profile_points_json` (kompaktes Zeit/Leistungs-Profil)
- Profilpunkte werden in allen Lernpfaden geschrieben: live, replay und manuelle Bereichsauswahl
- Legacy-Muster ohne Profil bleiben kompatibel (automatischer Fallback auf Rekonstruktion)

---

# Release 0.6.1 (BETA)

## Store Kurztext
- **Erkennung stabiler**: Vollstaendige Feature-Nutzung im Learning (weniger unplausible Pattern-Vorschlaege)
- **Import robuster**: Zeitstempel-Normalisierung fuer HA-History/Replay verhindert stille Lern-Aussetzer
- **DB konsistenter**: Pattern-Updates pflegen jetzt auch erweiterte Feature-Spalten und Phase

## Highlights
- Replay- und Live-Learning uebergeben nun alle relevanten Zyklusmerkmale (u.a. Varianz, Rise/Fall-Rate, Duty-Cycle, Substates)
- Vorschlagsmodell beruecksichtigt bei Single-Phase-Cycles nur phasenkompatible Pattern
- Manuelle Pattern-Erstellung aus dem Graphen speichert explizit die dominante Phase

---

# Release 0.6.0 (BETA)

> ℹ️ **Version-Hinweis**: Fundamentales Architektur-Redesign - noch nicht ausführlich getestet.
> Bei unerwarteten Problemen bitte auf v0.5.2.1 zurückrollen und Issue auf GitHub melden.

## Store Kurztext
- **Per-Phase Pattern Learning**: Jede Phase (L1/L2/L3) trackt Muster unabhängig - keine Interferenz mehr!
- **Intelligente Phase-Attribution**: Kühlschrank (L1, 150W) + Waschmaschine (L2, 800W) = 2 Patterns, nicht 950W-Gerät
- **Ressourcen-Optimierung**: Learner nur für konfigurierte Phasen aktiv

## Highlights
- **Architektur-Redesign**: Separate `PatternLearner` Instanzen pro Phase (L1/L2/L3)
- **Interferenz-Schutz**: Geräte auf verschiedenen Phasen beeinflussen sich nicht mehr
- **Phase-basiertes Pattern Matching**: Patterns werden nur mit Cycles der gleichen Phase verglichen
- **UI-Verbesserung**: Phase-Spalte zeigt explizit L1/L2/L3 (statt nur "1-ph")
- **Conditional Initialization**: Nur Phasen mit Entity-ID bekommen Learner (spart RAM bei 1-Phasen-Systemen)
- **Bugfix**: DateTime timezone-aware/naive Konflikt in manueller Pattern-Erstellung behoben

## Technical Details
**Main Loop (app/main.py):**
- Changed from single `self.pattern_learner` to `self.phase_learners: Dict[str, PatternLearner]`
- Conditional creation: `if entity_id and entity_id.strip()` before learner initialization
- Iterator over phase_learners processes each phase with isolated `PowerReading(power_w=phase_power, phase=phase_name)`
- Explicit phase attribution in cycle payload: `"phase": phase_name`

**Database Schema (app/storage/sqlite_store.py):**
- New column: `phase TEXT DEFAULT 'L1'` in learned_patterns table
- INSERT statement includes phase field from cycle
- SELECT in `list_patterns()` includes `COALESCE(phase, 'L1')`
- Pattern matching filters candidates by phase before distance calculation

**Web UI (app/web/server.py):**
- Phase column displays: `L1<br><span>1-ph</span>` (explicit phase + mode)
- Pattern table shows clear phase attribution for each learned device

## Migration Notes
- Existing patterns in DB get default `phase='L1'` via COALESCE
- No data loss - patterns remain functional
- Consider reviewing patterns after upgrade to verify correct phase attribution
- Multi-phase devices (e.g., 3-phase motors) will be detected on all active phases

---

# Release 0.5.2.1

## Bugfix Release
- Fixed NameError in phase detection when reading power data
- Variables `active_phases` and `num_active_phases` now properly scoped
- Addon no longer crashes on power reading

---

# Release 0.5.2

## Store Kurztext
- **Muster-Kurven anzeigen**: Klick auf ein Muster zeigt Leistungsprofil (Anstieg/Plateau/Abfall)
- **Phasen-Erkennung genauer**: Echte 3-Phasen-Geräte vs. mehrere Single-Phase-Geräte besser unterschieden

## Highlights
- **Interactive Pattern Visualization**: Click any learned pattern row for power curve (rise/plateau/fall) in modal
- Curve reconstruction from pattern metrics: rise_rate, peak_power, fall_rate, duration
- **Improved 3-Phase Detection**: Power distribution ratio (15-60% balance) instead of absolute watts
- Better accuracy: Single-phase devices on different phases no longer misclassified as 3-phase

## Technical Details
**UI Changes (server.py):**
- Added pattern modal with canvas curve visualization
- `renderPatternChart()` reconstructs power profile from pattern properties
- Stats panel displays avg/peak power, duration, rates, phase mode, frequency

**Phase Detection Logic (source.py):**
- Calculates phase contribution percentages (power % per phase)
- Multi-phase only if: all 3 phases active AND max% < 60% AND min% > 15%
- Single-phase default prevents false positives

---

# Release 0.5.1

## Store Kurztext
- **Modernes HA-nahes Web-UI**: Karten, Tabellen und Controls im aktuellen Home-Assistant-Stil
- **Einfachere Add-on-Konfiguration**: Fokus auf Leistungs-/Phasen-Sensoren, Rest bleibt optional mit Defaults

## Highlights
- Visuelles Refresh der Web-UI mit konsistenten hell/dunkel Farben, modernisierten Karten und klareren Interaktionen
- Task-Progress-Bereich stabil integriert (kein `classList`-Frontend-Fehler bei fehlenden Elementen)
- Add-on Optionen reduziert auf `home_assistant.phase_entities.l1/l2/l3` fuer den Standardbetrieb
- Lernen bleibt automatisch aktiv, erweiterte Parameter sind weiterhin optional verfuegbar

## Technical Details
- Reworked embedded CSS theme in `app/web/server.py` with stable selectors and improved spacing/contrast
- Added robust guard in `updateTaskProgress(taskInfo)` for optional task progress markup
- Updated addon manifest schema/options in `config.yaml` to keep advanced settings optional (`?`)
- Documentation and examples aligned: `README.md`, `DOCS.md`, `example_options.json`

---

# Release 0.5.0

## Store Kurztext
- **UI-Verbesserungen**: Aufgaben-Fortschritt oben angezeigt, Chart flackert nicht mehr
- Viele kleine Performance-Optimierungen

## Highlights
- **Task Progress Indicator**: Shows active tasks (learning runs, HA import) with percentage progress bar
- **Chart Flickering Fixed**: Diagram only redraws when data actually changes - no more flickering on every refresh
- Smooth rendering with requestAnimationFrame
- Visual progress bar (0-100%) for long-running operations

## Technical Details
**UI Components Added:**
- `.active-task` container with progress bar
- `updateTaskProgress(taskInfo)` function
- Task info displayed from `/api/live` response (live.task)

**Chart Optimization:**
```javascript
// Before: Always redraw (flickering)
ctx.clearRect(0, 0, w, h);

// After: Smart detection
if (prevLength === newLength && lastPoint.identical) {
  return; // Skip redraw
}
requestAnimationFrame(() => { /* render */ });
```

**Detection Logic:**
1. Compare series length (prevLength vs newLength)
2. If same length, compare last data point (timestamp + power_w)
3. Only redraw if data changed
4. Wrap rendering in requestAnimationFrame for smoothness

**Why This Matters:**
- Previously: Chart redrawn every 5 seconds even if data identical → flickering
- Now: Only redraws when new data arrives → smooth experience
- Task progress visible during long operations (learning 24h of data)

**Backend Integration (future):**
API should return `task` object in `/api/live`:
```json
{
  "task": {
    "active": true,
    "name": "Lernlauf (24h Daten)",
    "progress": 67.5
  }
}
```

---

# Release 0.4.4

## Store Kurztext
- **Kritischer Bugfix**: IndentationError behoben - Container startet wieder korrekt

## Highlights
- Fixed IndentationError in pattern_learner.py that prevented addon from starting
- Removed orphaned debug line from merge conflict

## Technical Details
Orphaned line at line 258:
```python
                logger.debug(f"Baseline updated: {self._baseline_power_w:.1f}W (from {len(self._baseline_history)} samples)")
```

This line was outside any function scope, causing Python interpreter to fail on import.

**Impact:** Without this fix, addon completely fails to start with IndentationError

---

# Release 0.4.3

## Store Kurztext
- **Log-Rotation**: Bei jedem Start wird die Log-Datei rotiert, maximal 3 alte Logs werden behalten
- Jeder Container-Start beginnt mit frischer, leerer Log-Datei

## Highlights
- **Startup log rotation**: Old logs are rotated automatically on each container start
- **Configurable retention**: Keep max N old log files (default: 3)
- Fresh start every time: Begin with empty log file for better readability
- No more massive accumulated log files

## Technical Details
**Rotation Logic:**
1. On startup, if `nilm.log` exists:
   - `nilm.log.2` → `nilm.log.3`
   - `nilm.log.1` → `nilm.log.2`
   - `nilm.log` → `nilm.log.1`
2. Old logs beyond `max_log_backups` are deleted
3. New `nilm.log` created fresh

**Configuration (config.yaml):**
- `log_file: /addon_configs/ha_nilm_detector/nilm.log` - Path to log file
- `max_log_backups: 3` - Number of old logs to keep (1-10)

**Implementation:**
- New function: `_rotate_log_file()` in `app/utils/logging.py`
- FileHandler added alongside StreamHandler (both console and file logging)
- Rotation happens before first log write

**Benefits:**
- Easy debugging: Latest run always in `nilm.log`
- History: Last 3 runs preserved as `.log.1`, `.log.2`, `.log.3`
- Clean starts: No searching through huge accumulated logs
- Persistent: Logs survive container restarts

---

# Release 0.4.2

## Store Kurztext
- **Intelligente 3-Phasen-Erkennung**: Unterscheidet echte 3-Phasen-Geräte von mehreren 1-Phasen-Geräten
- Prüft synchrone Anstiege auf allen Phasen

## Highlights
- **Synchronized phase rise detection**: Checks if all phases rise within 10 seconds → true 3-phase device
- **Prevents false classification**: Distinguishes multiple 1-phase devices (e.g., microwave on L1 + kettle on L2) from real 3-phase appliances
- Better accuracy for mixed-phase environments
- Uses actual timeline analysis instead of just counting active phases

## Technical Details
New method: `PatternLearner._check_synchronized_phase_rise(samples)`:
1. Extracts `phase_powers_w` from PowerReading metadata
2. Finds rise point for each phase (>30W increase from baseline)
3. Checks if all rises occur within 10-second window
4. Sets `phase_mode = "multi_phase"` only if synchronized

**Logic:**
- Synchronized rises (≤10s apart) → true 3-phase device (e.g., heat pump, EV charger)
- Non-synchronized rises → multiple 1-phase devices on different phases
- Single phase data → 1-phase device

## Why This Matters
Previously: Just counted active phases → misclassified overlapping 1-phase devices as 3-phase

Now: Analyzes temporal synchronization → accurate 3-phase detection even with complex multi-device scenarios

Common false positives now fixed:
- Microwave (L1) + toaster (L2) running simultaneously
- Fridge (L1) + washing machine (L3) overlapping cycles
- Multiple kitchen appliances on different phases

---

# Release 0.4.1

## Store Kurztext
- **KRITISCHER BUGFIX**: Automatische Geräteerkennung erkennt jetzt 1-Phasen-Geräte korrekt!
- Phase-Erkennung nutzt echte Messdaten statt primitive Heuristik

## Highlights
- **Fixed 1-phase device detection**: SmartDeviceClassifier now uses actual phase information from power readings instead of power-based heuristic (>5kW = 3-phase)
- **LearnedCycle phase tracking**: Cycles now include `phase_mode` field extracted from readings
- Massively improved automatic device classification for single-phase appliances
- Better match scores for devices like microwave, toaster, kettle that were previously misclassified

## Technical Details
- `LearnedCycle` dataclass now includes `phase_mode: str` field ("single_phase" or "multi_phase")
- Phase mode extracted in `_build_cycle()` from PowerReading phases: `phases_set = set(r.phase for r in samples)`
- `SmartDeviceClassifier._detect_phase_mode()` prioritizes actual phase data over power heuristic
- Fallback to >5kW heuristic only when phase data unavailable

## Why This Matters
Previously, the classifier ignored actual phase information and used `peak_power > 5000W` to determine 3-phase. This caused:
- High-confidence single-phase devices to get -0.20 penalty if they had >5kW peak
- Low-power 3-phase devices to be misclassified as 1-phase
- Poor classification scores for common 1-phase appliances

Now: Phase information flows from collector → PowerReading → LearnedCycle → SmartClassifier properly.

---

# Release 0.4.0

## Store Kurztext
- Neue UI-Features: Einzelne Muster löschen, separate Clear-Buttons für Live-Daten vs. Muster
- Bessere Kontrolle: Muster bleiben beim Löschen von Live-Daten erhalten

## Highlights
- **Pattern management**: Delete individual patterns with button in table
- **Selective clearing**: Separate buttons to clear only live readings or only patterns
- No more accidental pattern deletion when clearing readings
- Each pattern row has Label + Delete buttons
- Cleaner UI with targeted data management

## Technical Details
- New endpoints: `/api/patterns/{id}/delete`, `/api/debug/clear-readings`, `/api/debug/clear-patterns`
- Storage functions: `delete_pattern()`, `clear_readings_only()`, `clear_patterns_only()`
- Old "DB leeren" button replaced with targeted "Live-Daten löschen" and "Muster löschen"

---

# Release 0.3.6

## Store Kurztext
- Behoben: Timezone-Fehler verhinderte Anzeige von gelernten Mustern in der UI.
- Muster-Tabelle wird jetzt korrekt nach Lernläufen angezeigt.

## Highlights
- **Critical fix for pattern display**: Fixed "can't subtract offset-naive and offset-aware datetimes" error in list_patterns()
- Datetime objects from database are now normalized to naive before calculations
- This was causing list_patterns() to fail silently and return empty list, hiding learned patterns from UI
- After learning runs, pattern table now displays detected cycles correctly

## Technical Details
- datetime.fromisoformat() may return timezone-aware datetime if ISO string contains timezone info
- datetime.now() returns naive datetime by default
- Added normalization step: strip tzinfo if present before subtraction in frequency calculations
- All storage operations remain local with no cloud dependency

---

# Release 0.3.5

## Store Kurztext
- Behoben: Manuelle Muster-Erstellung speichert jetzt zuverlässig (cursor-Fix).
- Behoben: Muster-Erkennung schlägt nicht mehr fehl wegen fehlender Feature-Spalten in der Datenbank.
- Muster werden jetzt sofort erkannt, wenn genug Datenpunkte vorhanden sind.

## Highlights
- **Critical fix for pattern recognition**: Added missing feature columns (rise/fall rates, substates, pattern types) to pattern matching logic. These were being omitted from database queries, causing fallback penalties that blocked valid pattern detection.
- **Fixed manual pattern persistence**: Moved cursor.lastrowid retrieval inside transaction context to ensure pattern IDs are properly retrieved when created from UI range selection.
- Patterns now reliably save and match even with minimal power variations, significantly improving learning accuracy.

## Technical Details
- Pattern distance calculation was applying 0.35 fallback penalty when advanced features were missing
- Manual pattern creation could fail silently without returning a valid pattern ID
- Both issues combined prevented new patterns from being recognized even with adequate data
- All storage operations remain local with no cloud dependency

---

# Release 0.2.11

## Store Kurztext
- Korrigierter Pfad für Pattern-DB: jetzt unter `/addon_configs/ha_nilm_detector/` (empfohlener HA Add-on Speicherort).
- Folgt den Best Practices für addon-spezifische persistente Konfiguration.

## Highlights
- Updated patterns database path to `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3` - the recommended Home Assistant addon configuration directory.
- Follows HA best practices for addon-specific persistent configuration storage.
- Existing patterns will be automatically migrated to the new location on first startup.

---

# Release 0.2.10

## Store Kurztext
- Datenbank-Trennung: Live-Rotationsdaten und Geraete-/Musterdaten sind jetzt getrennt.
- Geraete-/Muster-DB kann dauerhaft unter `/addon_configs/ha_nilm_detector/` liegen und bleibt damit besser erhalten.
- Bestehende Muster werden beim Umstieg einmalig automatisch in die neue Pattern-DB migriert.

## Highlights
- Added dedicated patterns database support via `storage.patterns_db_path`.
- Default patterns path is `/addon_configs/ha_nilm_detector/nilm_patterns.sqlite3` for persistent local storage.
- Pattern operations (labeling, matching, nightly merge, manual pattern creation) now use the dedicated DB.
- Added automatic one-time migration from existing `learned_patterns` in the live DB.

## Notes
- Live readings/detections continue in the rotating runtime DB.
- Learned devices/patterns are now decoupled from live data retention cleanup.
- All processing remains fully local (privacy-first, no cloud dependency).
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
