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
