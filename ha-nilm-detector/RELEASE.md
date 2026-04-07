# Release Notes

> ⚠️ **EXPERIMENTELLES PROJEKT**: Dieses Add-on ist in aktiver Entwicklung (BETA-Status). Features können unvollständig sein, Breaking Changes auftreten. Nutze es zum Experimentieren und Testen, nicht für kritische Produktionsumgebungen.

---

# Release 0.6.40 (BETA)

## Store Kurztext
- **🧾 LLM-Review jetzt mit Messpunkten exportierbar**: externe Analyse von Lernlogik und Segmentierung kann direkt mit echten Power-Readings erfolgen.

## Highlights
- **Externer LLM-Review mit echten Messdaten**
  - der LLM-Review-Bundle kann jetzt rohe `power_readings` mitsamt Zeitstempeln enthalten
  - dadurch laesst sich Segmentierung, Start-/End-Erkennung und Lernlogik deutlich besser extern bewerten
- **Web-UI direkt nutzbar**
  - der bestehende LLM-Exportbutton liefert jetzt nicht nur Pattern-/Event-Zusammenfassungen, sondern auch Messpunkte
  - die Exportgroesse bleibt ueber ein Limit kontrollierbar
- **Mehr Transparenz im Bundle**
  - `counts.power_readings` zeigt sofort, wie viele Messpunkte enthalten sind
  - Privacy-Metadaten weisen darauf hin, dass genaue Zeitstempel und Rohmesswerte enthalten sein koennen
- **Verifikation**
  - gezielte Tests fuer Storage-Export und Web-Endpoint mit Messpunkten sind gruen

---

# Release 0.6.39 (BETA)

## Store Kurztext
- **🧭 Segmentierungs-Qualitaet weiter gehaertet**: ehrlichere Shape-Scores, sichere Kandidatenlabels bei Teilzyklen und strengeres Learning-Gating ohne Test-/Import-Roundtrips zu brechen.

## Highlights
- **Shape-Scoring ehrlicher gemacht**
  - explizite `shape_signature` wird wieder sauber ausgewertet, auch wenn Status-Metadaten fehlen
  - fehlende oder ungueltige Signaturen erzeugen keine falsche Shape-Confidence mehr
- **Segmentierungsqualitaet sichtbar in der Entscheidung**
  - `segmentation_confidence` und `waveform_completeness_score` werden im Klassifikationspfad und in der Persistenz mitgefuehrt
  - Baseline-Sichtbarkeit vor und nach dem Event wird explizit bewertet
- **Sicherere Labels fuer Teilzyklen**
  - unvollstaendige Motor-/Kompressor-Ereignisse bleiben bei Kandidatenlabels wie `compressor_candidate`, `motor_candidate`, `pump_candidate` oder `fridge_candidate`
  - optimistische Endlabels werden bei schwacher Segmentierung aktiv heruntergestuft
- **Learning-Gate gehaertet ohne Kollateralschaeden**
  - schlechte Segmentierung blockiert Pattern-Lernen gezielt
  - synthetische Vollzyklen aus Persistenz-/Roundtrip-Tests bleiben mit sichtbarer Start-/End-Baseline lernbar
- **Segmentierungsabschluss robuster**
  - Mid-Cycle-Starts finalisieren nach gesammeltm Post-Roll sauber
  - reine Kurzspikes werden weiterhin verworfen und nicht als gueltige Zyklen gelernt
- **Verifikation**
  - fokussierte NILM-Suite komplett gruen: 28 Tests bestanden

---

# Release 0.6.38 (BETA)

## Store Kurztext
- **🩺 Segmentierungs-Hotfix fuer Vollzyklen**: fruehere Start-Erkennung, spaeteres Event-Ende und weniger faelschliche Truncation bei Motoren und Kompressoren.

## Highlights
- **Vollzyklen statt Fragmenten**
  - Event-Start nutzt jetzt Rolling-Baseline, Delta-Trigger und Derivative-Trigger
  - Inrush-Spitzen werden frueher in das Eventfenster aufgenommen
  - Pre-Roll/Post-Roll werden explizit in den Segmentierungsfluss eingebunden
- **Robustere End-Erkennung**
  - Rueckkehr zur Baseline muss ueber Hold-Time stabil sein
  - kurze Einbrueche bei Motoren/Kompressoren beenden das Event nicht sofort
- **Weniger falsche `truncated_start`-Faelle**
  - harte Starts direkt aus Idle werden nicht mehr als abgeschnitten behandelt
  - Truncation wird erst auf dem vollstaendigen Eventfenster bewertet
- **Lern-/Shape-Gating verbessert**
  - truncierte Events senken Confidence
  - `shape_signature` wird fuer truncierte Events nicht als vollwertige Lernbasis genutzt
- **Verifikation**
  - neue Segmentierungsregressionen und fokussierte NILM-Suite sind gruen

---

# Release 0.6.37 (BETA)

## Store Kurztext
- **🔬 NILM-Lernpfad fuer Realtests geschaerft**: bessere Event-Segmentierung, feinere Unknown-Klassen und reichhaltigere Review-/Debug-Daten fuer Home Assistant.

## Highlights
- **Segmentierung stabilisiert**
  - Rolling-Baseline reduziert False Starts bei Replay und Live-Learning
  - Event-Ende nutzt jetzt Hold-Time und Stabilization-Grace statt zu fruehem Abschneiden
  - Pre-Roll/Post-Roll werden mitgespeichert, inklusive `truncated_start` und `truncated_end`
- **Klassifikation deutlich verfeinert**
  - neue abgeleitete Merkmale fuer Inrush, Plateau, Varianz und Formverlauf
  - `shape_signature` wird aktiv im Matching genutzt
  - breit gefasste Unknown-Sammellabel werden durch spezifischere Unterklassen ersetzt
- **Pattern- und Event-Review erweitert**
  - Confidence-Split (`rule`, `shape`, `temporal`, `final`)
  - Kandidatenlabels, Begruendungstexte und Segmentierungsflags in Persistenz und Exporten
  - besseres Debugging fuer echte HA-Testzyklen
- **Dedup/Pattern-Lernen robuster**
  - fast identische Muster werden ueber explizite Toleranzen eher zusammengefuehrt statt doppelt gespeichert
- **Verifikation**
  - zielgerichtete Regressionstests fuer Segmentierung, Klassifikations-Refactor und Persistenz sind gruen

---

# Release 0.6.36 (BETA)

## Store Kurztext
- **🤝 Testweise kollaborative Musterfreigabe**: Privacy-sicherer Shared-Pattern-Export, neues LLM-Review-Bundle und sichtbare Exportflaechen in der UI.

## Highlights
- **Shared Pattern Pack fuer freiwilliges Community-Sharing**
  - Neues Exportformat fuer bestaetigte Muster ohne Rohmesswerte, ohne Event-Historie und ohne Freitext-Kommentare
  - Oeffentliche Labels werden sanitisiert, damit keine privaten Raum-/Geraetenamen unkontrolliert exportiert werden
- **LLM-Review-Bundle fuer Entwickleranalyse**
  - Kompaktes JSON mit Pattern-Features, Event-Summaries, Klassifikationslog und Trainingslog
  - Direkt fuer ChatGPT-/LLM-gestuetzte Review-Loops nutzbar, ohne Voll-Export der lokalen Datenbank
- **UI-Exportflaechen erweitert**
  - Neue Buttons `Shared Pack` und `LLM Review` im Dashboard
  - Downloads laufen ueber dieselbe JSON-Download-Logik wie der bisherige Voll-Export
- **Erstklassifikation geschaerft**
  - Markante Signaturen werden frueh als konkrete Geraetetypen erkannt (`kettle`, `fridge`, `washing_machine`, `dishwasher`, `microwave`)
  - Unscharfe Faelle bleiben bewusst `unknown` statt in grobe Sammelkategorien zu rutschen
- **Verifikation**
  - Neue Regressionstests fuer Shared-Export und Erstklassifikation gruen

---

# Release 0.6.35 (BETA)

## Store Kurztext
- **🧱 Lernpipeline modularisiert**: klare Stage-Trennung, bessere Event-Inspektion im Kontextchart und robuster Import/Export-Roundtrip.

## Highlights
- **Deterministische Pipeline-Stages als Modul**
  - Neues Modul `app/learning/pipeline_stages.py`
  - Lernfluss ist jetzt klar getrennt in `prepare -> match -> dedup-decision`
  - `sqlite_store.learn_cycle_pattern` bleibt API-stabil, ist intern aber besser testbar
- **Dedup-Konfiguration zentralisiert**
  - `dedup_update_similarity` und `dedup_merge_similarity` als zentrale Parameter
  - Zusatzausgabe im Log: dedup-Entscheidung inkl. Grund und Similarity
- **UI-Inspektion erweitert**
  - Pattern-Kontextansicht zeigt jetzt segmentierte Event-Phasen (Inrush/Steady/Shutdown) direkt im Chart
  - Stats im Modal enthalten zusaetzlich die Phasen-Dauern
- **Persistenz & Roundtrip gehaertet**
  - Export liefert Schema-Metadaten
  - Import uebernimmt erweiterte Pattern-/Device-/Event-Felder
  - Timestamp-Repair fuer Patterns wird nach Import automatisch forciert
- **Tests ausgebaut**
  - Neue Unit-Tests fuer Pipeline-Stages
  - Restart-Persistenz- und Import/Export-Roundtrip-Test
  - Dedup-Regression fuer leicht variierenden Inrush beim selben Geraet

---

# Release 0.6.34 (BETA)

## Store Kurztext
- **🧠 Hybrid-ML Phase 1 gestartet**: Boosting-first Fusion, mehr Debug-Transparenz und sichtbare Build-Version im Dashboard.

## Highlights
- **Phase-1 Fusion aktiv**
  - Gewichte: Boosting `45%`, Shape `35%`, Prototype `20%`
  - Kontrollierter ML-Override nur bei klarer Evidenz
  - `decision_reason` pro Entscheidung fuer bessere Nachvollziehbarkeit
- **ML-Modell verbessert**
  - Boosting-first (`HistGradientBoostingClassifier`) statt reinem RandomForest
  - Fallback auf RandomForest bei inkompatiblen Umgebungen
  - Training bevorzugt bestaetigte bzw. User-gelabelte Muster
- **Persistenz + Debug-API erweitert**
  - Event-/Training-Logs enthalten jetzt Hybrid-Teilscores und Agreement-Flag
  - UI zeigt `Boosting/Shape Agreement` und `ML Override Rate` der letzten 100 Entscheidungen
- **Build-Version sichtbar**
  - Start-Log und Web-UI zeigen Release-Version + kurzen Git-Commit

---

# Release 0.6.33 (BETA)

## Store Kurztext
- **🔎 Muster-Detailansicht deutlich besser**: Kontextkurve mit Vor-/Nachlauf, Event-Markierungen, Dedup-Entscheidungen und Touch-feste Musterauswahl.

## Highlights
- **Robuste Dedup-Lernlogik vor Insert**
  - Similarity-Scoring mit gewichteten Komponenten (Shape, Duration, Delta, Peak/Inrush)
  - Entscheidungsregeln: `update_existing`, `merge_mode`, `create_new`
  - Session-Guard verhindert doppelte Lern-Eintraege im selben Lauf
- **Neue Kontext-API fuer Musterdetails**
  - `GET /api/patterns/<id>/context?pre=2&post=2`
  - Liefert Event-Zeitpunkte, Kontextgrenzen, Rohsamples, Offsets, Baseline und Marker
- **Pattern-Modal fuer Debugging ausgebaut**
  - Umschaltung `Mit Kontext` / `Nur Muster`
  - Presets `2s`, `5s`, `10s` Vor-/Nachlauf
  - Event-Fenster farblich hervorgehoben, Start/Ende als Linien
  - Hover-Werte + Zoom (Mausrad) + optionale Sample-Punkte
- **Mobile/Touch-Fix in der Musterliste**
  - Auswahl funktioniert jetzt zuverlaessig auf Touchscreens
  - Neuer `Details`-Button als klarer Tap-Target
- **Schema und Debug-Transparenz verbessert**
  - Dedup-Felder in `learned_patterns`, `events`, `training_log`
  - Event-Metafelder fuer Kontext-Reproduktion (`start_time`, `end_time`, `sample_*`, `raw_trace_id`)

---

# Release 0.6.30 (BETA)

## Store Kurztext
- **🧱 Pipeline-/Debug-Refactor**: Per-Phase NILMPipeline, Overlap-Scoring und neues 5-Tab-Dashboard machen Lernen und Fehleranalyse deutlich nachvollziehbarer.

## Highlights
- Main-Loop nutzt pro Phase eine dedizierte `NILMPipeline` mit konsistentem Stage-Debug
- Neue Overlap-Analyse (`strong`/`weak`) mit `overlap_score` im Klassifikations-Payload
- Neue Audit-Tabelle `training_log` fuer Accept/Reject-Entscheidungen des Trainingspfads
- Neue Endpunkte:
  - `GET /api/training-log`
  - `GET /api/debug/pipeline-buffer`
- Dashboard als 5 Tabs neu strukturiert: `LIVE`, `EVENTS`, `GERÄTE`, `LERNEN`, `DEBUG`
- Debug-Tab zeigt Pipeline-Puffer, Klassifikationslog und Confidence-Breakdown
- Typing-/Runtime-Hotfixes fuer Storage und Web-API (Optional-Strings, sichere JSON-Payloads)

---

# Release 0.6.29 (BETA)

## Store Kurztext
- **⚡ Schnellere Updates**: Add-on verwendet jetzt vorkompilierte Alpine-Binary-Pakete fuer `numpy`, `scipy` und `scikit-learn` statt langsamer Source-Builds.

## Highlights
- Add-on-Dockerfile auf Binary-Dependencies umgestellt: `py3-numpy`, `py3-scipy`, `py3-scikit-learn`
- Build-Toolchain aus dem Runtime-Image entfernt (`gcc`, `g++`, `musl-dev`, `python3-dev`)
- `requirements.txt` im Add-on reduziert auf leichte pip-Pakete (`paho-mqtt`, `requests`)
- Erwartete Wirkung: spuerbar kuerzere Install-/Update-Zeit auf ARM und x86

---

# Release 0.6.28 (BETA)

## Store Kurztext
- **🤖 Machine Learning aktiviert**: RandomForest trainiert sich selbst auf deinen Labels! Hybrid-Klassifikation kombiniert Prototype + Shape + ML für bessere Genauigkeit.

## Highlights
- ML-System `LocalMLClassifier` mit scikit-learn RandomForest (80 Estimators) aktiviert
- Standard-aktiviert: `ml_enabled=true` in allen Konfigurationen
- **Automatisches Training**: RandomForest trainiert sich selbst wenn ≥8 bestätigte Samples mit ≥2 Klassen vorhanden
- **3er-Hybrid-Klassifikation**: Prototype-Matching + Shape-Similarity + ML-Vorhersage kombiniert
- **Intelligente Fallbacks**: Wenn ML unsicher (<0.55 confidence) → nutzt regelbasierte Klassifikation
- ML-Features umfassen: avg/peak power, duration, energy, power_variance, rise/fall rates, duty_cycle, substates, pattern-flags
- **Web-UI Integration**: ML-Score sichtbar unter "Hybrid AI Debug" mit Top-3 Vorhersagen
- Confidence-Score wird aus allen 3 Quellen kombiniert → höhere Erkennungsgenauigkeit
- scikit-learn>=1.0 zu Abhängigkeiten hinzugefügt
- **Inrush/Runtime-Schema aktiv**: Persistenz um Baseline/Delta-Kennwerte in `learned_patterns` und `events` erweitert
- **Feingranulare Event-Phasen**: Neue Tabelle `event_phases` speichert `baseline`, `inrush`, `steady/modulated_run`, `shutdown`, `cooldown`
- **Cycle-Aggregation pro Gerät**: Neue Tabelle `device_cycles` mit Dauer-/Leistungs-Mittelwerten und Signatur
- **Neue Diagnose-APIs**: `GET /api/event-phases`, `GET /api/device-cycles`
- **Erweiterte bestehende APIs**: `GET /api/devices` (Subklasse + Baseline-Range), `GET /api/events` (Baseline/Delta)

---

# Release 0.6.26 (BETA)

## Store Kurztext
- **Wissensbasis-Upgrade**: Pattern, Events, Devices und Entscheidungslog werden jetzt getrennt und persistent gespeichert fuer nachvollziehbares Langzeitlernen.

## Highlights
- Neue persistente Tabellen: `devices`, `events`, `pattern_features`, `classification_log`, `user_labels`, `pattern_history`
- Explizite `patterns`-Mirror-Tabelle als getrennte Pattern-Ebene (parallel zu `learned_patterns`)
- Laufende Lernzyklen speichern jetzt Event-Daten, Feature-Snapshots, Entscheidungsgruende und Historie
- User-Label-Aenderungen werden als Trainingssignal in `user_labels` historisiert
- Neue API-Endpunkte fuer Debug/Analyse: `/api/devices`, `/api/events`, `/api/classification-log`, `/api/user-labels`
- Neue Trainings-Exporte: `/api/debug/export-training-jsonl` und `/api/debug/export-features-csv`

---

# Release 0.6.24 (BETA)

## Store Kurztext
- **Klassifikation verbessert**: Echte Zyklus-Features, deterministic First-Level-Regeln und Frequency-Refinement reduzieren `unknown` und verbessern die Musterqualitaet.

## Highlights
- Feature-Extraction mit robusten Edge-Raten (Rise/Fall), Plateau/Substate-Segmentierung und `step_count`
- Deterministische Erstklassifikation (`heater`, `motor`, `electronics`, `long_running`) vor ML-Fallback
- Replay-Edge-Fallback nutzt echte Features statt Dummy-Werte
- Frequency-basierte Label-Verfeinerung fuer plausiblere Vorschlaege
- `step_count` durchgaengig in Pattern-Schema, Update/Insert und manueller Bereichserstellung
- Erweiterte Klassifikations-Logs mit Regelgrund und Kernmerkmalen fuer bessere Diagnose

---

# Release 0.6.23 (BETA)

## Store Kurztext
- **Hybrid-Debug-Fix**: `unknown` wird nicht mehr mit hoher Konfidenz dargestellt.

## Highlights
- Konsistenzfix fuer Hybrid-Entscheidungen: unbekannte Labels erhalten nun eine gedeckelte, niedrige Konfidenz
- Neuer Source-Hinweis `fallback_unknown_label` fuer klare Nachvollziehbarkeit
- Explain-Details bleiben sichtbar

---

# Release 0.6.22 (BETA)

## Store Kurztext
- **Lernlauf-Fix**: Bei schwieriger Historie wird jetzt ein robuster Fallback genutzt, damit trotz vieler Messpunkte auch wirklich Zyklen gelernt werden koennen.

## Highlights
- Edge-basierter Replay-Fallback, wenn Standard-Replay 0 Zyklen liefert
- Delta-On/Off + Baseline + Sparse-Gap-Handling fuer Recorder-Historie
- Verbesserte Lernquote bei importierten Verlaufspunkten

---

# Release 0.6.21 (BETA)

## Store Kurztext
- **Persistenz stabilisiert**: Daten bleiben nach Neustarts/Updates deutlich robuster erhalten, Warmstart und Migrationen sind jetzt transparent diagnostizierbar.

## Highlights
- Zentraler Storage-Standardpfad: `/data/ha_nilm_detector` (konfigurierbar via `storage.base_path`)
- Robuste Legacy-Migration auch bei leeren Ziel-Dateien
- Erweiterte Startup-Diagnose: DB-Dateien, Groessen, Tabellen, Row-Counts, Schema-Versionen
- Migration ohne irrefuehrende Warnungen bei fehlender Legacy-Tabelle
- Warmstart mit Fallback auf letzte Messwerte + detaillierter Ursache im Log
- Saubere Shutdown-Reihenfolge mit explizitem Flush/Commit/Close vor Service-Stop

---

# Release 0.6.20 (BETA)

## Store Kurztext
- **Persistenz-Hotfix**: Nach Updates koennen Live-Daten jetzt automatisch aus Legacy-DB-Pfaden wiederhergestellt werden.

## Highlights
- Neue Startup-Recovery fuer `power_readings` und `detections`, wenn aktuelle Live-DB leer ist
- Recovery prueft bekannte Legacy-Pfade (`/addon_configs/...`, `/data/...`) und importiert vorhandene Daten
- Reduziert Datenverlust-Eindruck nach Versionswechsel deutlich

---

# Release 0.6.19 (BETA)

## Store Kurztext
- **Lernlauf-Hotfix**: Manueller Lernlauf erkennt wieder mehr Zyklen aus importierten HA-Verlaufsdaten (48h Replay + Fallback-Pass).

## Highlights
- Manueller Trigger (`Lernen jetzt ausfuehren`) replayt 48h statt 24h
- Zweiter Replay-Fallback ohne Baseline-Priming, wenn erster Pass 0 Zyklen findet
- Stabilerer Lernlauf bei importierter Historie und schwankender Grundlast

---

# Release 0.6.18 (BETA)

## Store Kurztext
- **Hybrid-AI sichtbar gemacht**: Neues Debug-Panel zeigt die letzte Modellentscheidung mit Explain-Scores und ML-Kandidaten direkt im Dashboard.

## Highlights
- Dashboard-Panel fuer Hybrid-AI Diagnose (`source`, `label`, `confidence`, `distance`)
- Explain-Scores live sichtbar: Prototype, Shape, Repeatability
- ML-Block zeigt Top-Kandidaten bei aktivem lokalem ML
- Neuer Endpoint `/api/debug/hybrid-status`

---

# Release 0.6.17 (BETA)

## Store Kurztext
- **Hybrid-AI Ausbau**: Modulare Event Detection, Shape Matching und optionales lokales ML fuer deutlich robustere Mustererkennung.

## Highlights
- Neue Module fuer Event-, Substate- und Shape-Analyse sowie Pattern-Matching
- Hysterese + Gap-Merging als dedizierte Event-State-Machine integriert
- Hybrid-Scoring mit explainable Teil-Scores (`prototype`, `shape`, `repeatability`, optional `ml`)
- Optionales lokales RandomForest-ML mit sicherem `unknown`-Fallback
- Neue Learning-Optionen: `ai_enabled`, `ml_enabled`, `shape_matching_enabled`, `online_learning_enabled`, `pattern_match_threshold`, `ml_confidence_threshold`
- Export um `pattern_dataset` erweitert fuer Trainings-/ML-Workflows

---

# Release 0.6.16 (BETA)

## Store Kurztext
- **Jetzt automatisch + manuell**: Die Lernpipeline laeuft zyklisch im Hintergrund und kann weiterhin jederzeit manuell gestartet werden.

## Highlights
- Auto-Lernen: periodischer Pipeline-Lauf mit konfigurierbarem Intervall
- Manuell: Dashboard-Trigger startet denselben Lernpfad sofort
- Konsistenter Lernfluss: Nachtlauf verwendet dieselbe aktive Pipeline
- Neue Optionen in `learning`: `auto_pipeline_enabled`, `auto_pipeline_interval_minutes`

---

# Release 0.6.15 (BETA)

## Store Kurztext
- **Neue Lernpipeline**: Exportdaten werden jetzt aktiv neu verarbeitet (Event Detection + Clustering + Pattern-Update) statt nur erneut ausgegeben.

## Highlights
- Neues CLI-Tool `nilm_pipeline.py` fuer echte Lernzyklen aus vorhandenen Daten
- Event-Erkennung mit Baseline + Schwellwert, Mindestdauer und Gap-Merge
- Event-Features und Pattern-Updates mit Plausibilitaetsbewertung und Erklaerungstexten
- Outputs fuer Debug und ML-Vorbereitung: `patterns_updated.json`, `events_detected.json`, `features.csv`, `dataset.jsonl`

---

# Release 0.6.14 (BETA)

## Store Kurztext
- **Test-Release 0.6.14**: Schneller Rollout fuer den Praxistest mit Daten-Export/Import und externem NILM-Analyse-Tool.

## Highlights
- Versionsupdate auf `0.6.14` fuer sofortigen Test im Add-on Store
- Export/Import bleibt aktiv: Daten koennen fuer KI-gestuetzte Analyse geteilt werden
- CLI-Tool `nilm_pattern_analyzer.py` zur robusteren Pattern-Auswertung von Export-JSON

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
