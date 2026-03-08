# Pattern Learning & Recognition System - Technical Summary

## Overview
The system detects repeated ON/OFF power cycles and recognizes/learns patterns from power data. It uses adaptive thresholds, advanced feature extraction, and distance-based matching to identify similar appliance cycles.

---

## 1. CYCLE DETECTION (Pattern Creation from Power Data)

### Core Component
**File:** `app/learning/pattern_learner.py` - `PatternLearner` class

### Cycle Detection Process
The system uses a **state machine with debouncing** to detect ON/OFF transitions:

#### A. State Machine Logic (Lines 110-175)
```
State 1: OFF (Idle)
  - Waiting for power to rise above ON_THRESHOLD
  - Updates adaptive baseline during idle periods
  - Requires debounce_samples consecutive high samples to confirm transition
  
State 2: ON (Active)
  - Collecting power samples
  - Waiting for power to fall below OFF_THRESHOLD
  - Updates see debounce counter reset if power rises again
  - Has safety failsafe: Cycles exceeding max_cycle_seconds (8 hours default) are reset
```

#### B. Key Cycle Detection Conditions (Lines 42-60)

| Parameter | Default Value | Purpose |
|-----------|---------------|---------| 
| `on_threshold_w` | 40.0 W | Cycle starts when power exceeds this |
| `off_threshold_w` | 20.0 W | Cycle ends when power drops below this |
| `min_cycle_seconds` | 5.0 s | Minimum cycle duration (ignores noise) |
| `max_cycle_seconds` | 28,800 s (8 hours) | Maximum cycle duration |
| `debounce_samples` | 2 | Require 2 consecutive samples for state change |
| `noise_filter_window` | 3 | Median filter window for spike rejection |

#### C. Adaptive Thresholds (Lines 47-50, 115-118)
When `use_adaptive_thresholds=True`:
- **Adaptive ON Threshold:** `baseline_power_w + adaptive_on_offset_w` (30W default)
- **Adaptive OFF Threshold:** `baseline_power_w + adaptive_off_offset_w` (10W default)
- **Baseline Tracking:** Moving median of last 60 idle samples (Lines 79-80)
- **Baseline Update:** Only updates with samples below `baseline + (adaptive_on_offset_w * 0.5)` (Line 195)
- **Median-based baseline prevents outlier pollution** (Lines 195-197)

#### D. Noise Filtering (Lines 177-189)
**Median filter for spike rejection:**
- Window of 3 samples
- Returns median (middle value) to reject single-sample spikes
- Fallback: Uses average if < 3 samples available

#### E. Cycle Completion (Lines 204-260)
When cycle ends, the system validates:
```python
1. Minimum 2 samples collected (Line 208)
2. Duration within min/max bounds (Lines 210-211)
3. Features can be extracted (Line 220)
4. Multi-mode analysis if available (Lines 224-244)
```

---

## 2. FEATURE EXTRACTION (Pattern Properties)

### Core Component
**File:** `app/learning/features.py` - `CycleFeatures` class

### Minimum Requirements
**Minimum samples required:** 3 samples (Line 45)
- Allows feature extraction even for very short cycles
- Methods that need more samples return `None` gracefully

### Extracted Features (Lines 24-40)

#### Basic Features
| Feature | Description | Formula |
|---------|-------------|---------|
| `avg_power_w` | Average power during cycle | sum(values) / n |
| `peak_power_w` | Maximum power | max(values) |
| `duration_s` | Cycle duration in seconds | (end_ts - start_ts).total_seconds() |
| `energy_wh` | Total energy consumed | Trapezoid integration: (dt * (prev + curr) * 0.5) / 3600 |

#### Advanced Shape Features
| Feature | Purpose | Calculation |
|---------|---------|-------------|
| `power_variance` | Power stability | sum((value - avg)²) / n |
| `rise_rate_w_per_s` | Ramp-up speed | Average slope across up to 30% of cycle using 12 windows |
| `fall_rate_w_per_s` | Ramp-down speed | Slope of last 20% of samples (min 3, max 12 samples) |
| `duty_cycle` | Time above 50% peak | count(samples >= peak*0.5) / total_samples |
| `peak_to_avg_ratio` | "Spikiness" | peak_power / max(avg_power, 1) |
| `power_std_dev` | Standard deviation | sqrt(variance) |

#### Multi-State Detection (Lines 153-190)
**Detects distinct power levels** (e.g., washing machine phases):
- Creates histogram with up to 10 bins
- Finds peaks (local maxima with >10% of samples)
- Returns (power_level, duration) pairs sorted by duration
- Threshold: `len(values) * 0.1` for significance

#### Pattern Type Detection (Lines 178-233)

**Heating Pattern Detection** (Line 178-189):
- Minimum 10 samples required
- Checks first 30% of samples for rising trend
- Returns TRUE if >70% of initial samples rise
- Used for: Kettle, oven, toaster

**Motor Pattern Detection** (Lines 208-233):
- Minimum 15 samples required
- Uses **Coefficient of Variation (CV)** for scale-independent analysis: `CV = stdev / mean`
- Valid motor pattern range: **0.25 ≤ CV ≤ 0.85** (25-85% variation)
- Applies zero-crossing analysis on detrended signal
- Returns TRUE if **≥3 zero crossings** detected
- Used for: Fridge compressor, washing machine, dishwasher

---

## 3. PATTERN MATCHING LOGIC (Pattern Recognition)

### Core Component
**File:** `app/storage/sqlite_store.py` - Methods: `learn_cycle_pattern()`, `_pattern_distance()`

### Pattern Matching Workflow (Lines 868-1090)

```
1. Get all active patterns from database (limit=500)
   ↓
2. Calculate distance to each pattern using _pattern_distance()
   ↓
3. Find pattern with minimum distance
   ↓
4. If distance <= tolerance (0.38 default):
   ├→ MATCHED: Update existing pattern statistics
   └→ NOT MATCHED: Create new pattern
```

### Distance Calculation (Lines 450-583)

The `_pattern_distance()` method computes similarity between patterns:

#### Core Power Characteristics (60% weight)
```python
Weighted components:
  avg_power_distance:      0.25
  peak_power_distance:     0.20
  duration_distance:       0.10
  energy_distance:         0.03
  phase_distance:          0.02
  
Formula: relative_distance = |a - b| / max(|a|, |b|, 1.0)
```
**Lines 463-478**

#### Advanced Shape Features (40% weight)
```python
Rise/Fall rates:           0.08 + 0.07 = 0.15
Duty cycle & variance:     0.06 + 0.05 = 0.11
Peak-to-average ratio:     0.04
Multi-state detection:     0.05
Pattern type matching:     0.03 + 0.02 = 0.05
(fallbacks if features missing)

Lines 480-567
```

#### Pattern Type Matching (Lines 555-567)
- **Heating pattern mismatch:** +0.03 penalty
- **Motor pattern mismatch:** +0.02 penalty
- These prevent matching incompatible device types

#### Final Distance
```python
total_distance = core_distance + shape_distance
Capped at: min(total_distance, 1.0)
```
**Line 574**

### Matching Threshold
**Default tolerance:** 0.38 (Lines 868, 951)

This means patterns within 38% distance are considered the same device:
- **0.0** = identical cycles
- **0.38** = match threshold (38% relative difference)
- **1.0** = completely different

### Pattern Update When Matched (Lines 902-965)

When a new cycle matches an existing pattern (distance ≤ 0.38):

```python
seen_count = existing_seen_count + 1
alpha = 1.0 / seen_count  # Exponential moving average factor

# Update pattern statistics (weighted by frequency)
avg_power = existing_avg * (1 - alpha) + new_avg * alpha
peak_power = existing_peak * (1 - alpha) + new_peak * alpha
duration = existing_duration * (1 - alpha) + new_duration * alpha
energy = existing_energy * (1 - alpha) + new_energy * alpha
```
**Lines 917-920**

This **exponential moving average** means:
- First 2 cycles: Equal weight (50% each)
- 10th cycle: Only 10% new, 90% history
- Patterns stabilize over time

#### Temporal Pattern Tracking (Lines 925-950)
When pattern is matched, system also tracks:
- **Interval between occurrences:** Time since last match
- **Last 10 intervals:** Stored as JSON array
- **Typical interval:** Median of last intervals
- **Hour of day distribution:** Histogram of which hours appliance runs
- **Average hour:** Weighted average time device typically runs

**Lines 929-948**

---

## 4. PATTERN CREATION (Manual & Automatic)

### A. Automatic Pattern Creation (Lines 965-1090)

When a cycle **doesn't match** any existing pattern (distance > 0.38):

1. **Feature extraction** - Extract all advanced features if not present (Lines 998-1004)
2. **Database insert** - Create new row in `learned_patterns` table (Lines 1008-1050):
   - All basic metrics: avg_power, peak_power, duration, energy
   - All advanced features: variance, rise_rate, fall_rate, duty_cycle, etc.
   - Pattern types: has_heating_pattern, has_motor_pattern
   - Multi-mode data: operating_modes JSON, has_multiple_modes flag
   - Initial temporal data: hour distribution, typical_interval_s
   - Status: "active"
   - Seen count: 1

3. **Return created pattern** (Lines 1061-1079)

### B. Manual Pattern Creation from UI (Lines 1105-1220)

**File:** `app/storage/sqlite_store.py` - `create_pattern_from_range()`

**Triggered from:** Web UI "Bereich markieren" (mark range) feature

**Process:**
```
1. Retrieve power readings between start_time and end_time
2. Minimum 3 data points required (Line 1124)
3. Extract CycleFeatures from selected range
4. Calculate: avg_power, peak_power, duration, energy
5. Analyze for multi-state substates
6. Detect heating and motor patterns
7. Insert with user_label and status="user_defined"
8. Return pattern_id to UI
```

**Lines 1113-1220**

#### Validation Requirements (Lines 1124-1130):
```python
rows = fetch(start_time to end_time)
if not rows or len(rows) < 3:
    return {"ok": False, "error": "not enough data points"}
```

---

## 5. NIGHTLY LEARNING PASS

### Core Component
**File:** `app/storage/sqlite_store.py` - `run_nightly_learning_pass()`
**Lines:** 590-750

### Purpose
Consolidate similar patterns to prevent database bloat and improve matching accuracy.

### Merge Process

```
1. Get all active patterns (limit configurable, default 800)
   ↓
2. Find all pairs with distance <= merge_tolerance (default 0.20)
   ↓
3. Sort pairs by distance (closest first)
   ↓
4. Select non-overlapping pairs (each pattern used max once)
   ↓
5. For each pair:
   ├→ Merge into pattern A (weighted average by seen_count)
   └→ Delete pattern B
```

**Lines 674-737**

### Weighted Merge (Lines 703-717)

```python
def _weighted_value(a_val, a_seen, b_val, b_seen):
    total = max(a_seen + b_seen, 1)
    return ((a_val * a_seen) + (b_val * b_seen)) / float(total)

# Example: Pattern A seen 5x (100W avg), Pattern B seen 3x (120W avg)
# Result: (100*5 + 120*3) / 8 = 108.75W avg
```

This ensures **older, more frequently seen patterns have more influence**.

### Merge Conditions
- **Default merge tolerance:** 0.20 (20% difference)
- **Phase mode must match:** Only merges patterns with same phase configuration
- **Status must be "active":** Inactive patterns are ignored

**Lines 670-673**

---

## 6. DATABASE SCHEMA FOR PATTERNS

### Core Tables (Lines 216-263)

**Table:** `learned_patterns`

```
Basic identity:
  id (PRIMARY KEY), created_at, updated_at, first_seen, last_seen

Pattern statistics:
  seen_count (occurrence frequency), 
  avg_power_w, peak_power_w, duration_s, energy_wh

Classification:
  suggestion_type (auto-suggested device label)
  user_label (user-confirmed label)
  status ("active", "archived", "user_defined")

Power characteristics:
  avg_active_phases, phase_mode (single_phase/multi_phase/unknown)

Advanced shape features:
  power_variance, rise_rate_w_per_s, fall_rate_w_per_s,
  duty_cycle, peak_to_avg_ratio, num_substates

Pattern types:
  has_heating_pattern, has_motor_pattern,
  operating_modes (JSON), has_multiple_modes

Temporal tracking:
  typical_interval_s (median interval between occurrences)
  avg_hour_of_day (typical time appliance runs)
  last_intervals_json (array of last 10 intervals)
  hour_distribution_json (histogram of usage by hour)
```

**Lines 216-258**

### Index
```sql
CREATE INDEX idx_learned_patterns_seen ON learned_patterns(last_seen)
```
**Line 259** - Enables efficient cleanup of old patterns

---

## 7. ERROR HANDLING & EDGE CASES

### Pattern Creation Prevents Errors (Lines 1024-1090)

1. **Missing advanced features:** Falls back to zeros (Lines 998-1004)
   ```python
   power_variance = float(cycle.get("power_variance", 0.0))
   rise_rate = float(cycle.get("rise_rate_w_per_s", 0.0))
   # ... defaults to 0 if missing
   ```

2. **Invalid timestamps:** Caught with try/except (Lines 1014-1020)
   ```python
   try:
       cycle_end_dt = datetime.fromisoformat(cycle["end_ts"])
   except (ValueError, TypeError):
       # Use defaults
   ```

3. **JSON parsing errors:** Handled gracefully (Lines 1040)
   ```python
   operating_modes_json = json.dumps(cycle.get("operating_modes", []))
   # Always produces valid JSON
   ```

### Pattern Matching Protection (Lines 875-880)

```python
if not self._patterns_conn:
    return {"matched": False, "pattern": None}

patterns = self.list_patterns(limit=500)
# Prevents processing if DB not connected
# Limits to 500 patterns to avoid O(n²) slowdown
```

### Feature Extraction Validation (Lines 43-45)

```python
@classmethod
def extract(cls, samples: List[PowerReading]) -> Optional[CycleFeatures]:
    if len(samples) < 3:
        return None  # Returns None, not exception
```

**All feature methods return None or default values** rather than raising exceptions.

---

## 8. INTEGRATION POINTS

### Where Patterns are Saved (Main Loop)
**File:** `app/main.py` - `_main_loop()` method (Lines 562-580)

```python
# After cycle detection by PatternLearner:
cycle_payload = {
    "start_ts": cycle.start_ts,
    "end_ts": cycle.end_ts,
    "avg_power_w": cycle.avg_power_w,
    # ... + all cycle features
}
heuristic_suggestion = self.pattern_learner.suggest_device_type(cycle)
learn_result = self.storage.learn_cycle_pattern(
    cycle=cycle_payload,
    suggestion_type=heuristic_suggestion,  # Tolerance: 0.38
)
```

### Nightly Learning Trigger
**File:** `app/main.py` - `_run_learning_now()` method (Lines 280-297)

```python
# Triggered manually from Web UI or on schedule
result = self.storage.run_nightly_learning_pass(
    merge_tolerance=0.20,  # Stricter than real-time (0.38)
    max_patterns=800,
)
```

### Pattern Suggestion to UI
**File:** `app/web/server.py` - `_build_patterns_payload()` (Line 252)

```python
def _build_patterns_payload(self) -> List[Dict]:
    if not self.storage:
        return []
    return self.storage.list_patterns(limit=100)
```

---

## 9. KEY THRESHOLDS AND TOLERANCES

| Parameter | Value | Location | Purpose |
|-----------|-------|----------|---------|
| Min cycle duration | 5.0 s | pattern_learner.py:46 | Ignore noise/spikes |
| Max cycle duration | 28,800 s (8 hrs) | pattern_learner.py:45 | Safety failsafe |
| Debounce samples | 2 | pattern_learner.py:52 | Confirm state transitions |
| Median filter window | 3 | pattern_learner.py:55 | Spike rejection |
| Baseline history size | 60 | pattern_learner.py:55 | Adaptive threshold window |
| Heating pattern threshold | >70% rising in first 30% | features.py:188 | Ramp-up detection |
| Motor pattern CV range | 0.25 - 0.85 | features.py:220 | Fridge/washer detection |
| Motor zero-crossings | ≥3 | features.py:232 | Cyclic pattern detection |
| Real-time match tolerance | 0.38 (38%) | sqlite_store.py:868 | Pattern matching threshold |
| Nightly merge tolerance | 0.20 (20%) | sqlite_store.py:633 | Pattern consolidation |
| Min data points (range) | 3 | sqlite_store.py:1124 | Manual pattern creation |
| Histogram significance | >10% of samples | features.py:172 | Detect multi-state |
| Rise rate window | up to 30% of cycle | features.py:73 | Robust ramp detection |
| Fall rate window | last 20% of samples | features.py:82 | Consistent ramp detection |

---

## 10. SUMMARY: FLOW FROM DETECTION TO DATABASE

```
Power Reading Ingestion
    ↓
[PatternLearner.ingest()]
    - Median filter for noise
    - Adaptive threshold calculation
    - State machine (OFF→ON, ON→OFF)
    - Debounce (2 samples required)
    ↓
Cycle Complete
    ↓
[PatternLearner._build_cycle()]
    - Validate: min 2 samples, duration bounds
    - Extract CycleFeatures
    - Detect heating/motor patterns
    - Analyze multi-mode (operating phases)
    - Return LearnedCycle object
    ↓
[PatternLearner.suggest_device_type()]
    - Use SmartDeviceClassifier (25+ device types)
    - Fallback to legacy heuristics (fridge, washing_machine, etc.)
    ↓
[SQLiteStore.learn_cycle_pattern()] ← **Pattern Matching Entry**
    - Load all active patterns (limit=500)
    - Calculate distance to each
    - Find best match (min distance)
    ↓
[Matching Decision]
    If distance <= 0.38:
        - UPDATE existing pattern
        - Exponential moving average of features
        - Track temporal data (intervals, hours)
    Else:
        - INSERT new pattern
        - Set status="active"
        - Initialize temporal tracking
    ↓
Database Persistence
    ↓
[Nightly cron: run_nightly_learning_pass()]
    - Load all patterns (limit=800)
    - Find similar pairs (distance <= 0.20)
    - Merge with weighted average
    - Delete duplicates
```

---

## Summary

The pattern learning system is a **lightweight, unsupervised learning framework** that:

✅ **Creates patterns** from raw power readings using cycle detection with adaptive thresholds  
✅ **Recognizes cycles** using multi-feature distance calculation (basic + advanced shape features)  
✅ **Learns iteratively** using exponential moving averages that weight recent observations  
✅ **Consolidates** similar patterns nightly to prevent database bloat  
✅ **Captures device behavior** including heating/motor patterns, multi-phase operations, and temporal usage  
✅ **Allows manual refinement** through UI pattern labeling  
✅ **Gracefully handles** missing data and edge cases with defaults instead of exceptions  

