# HA NILM Detector

HA NILM Detector is an experimental Home Assistant add-on for **Non-Intrusive Load Monitoring (NILM)**. It observes one or more power sensors and learns recurring load patterns without requiring a dedicated sensor on every appliance.

> [!WARNING]
> This project is currently **BETA**. Do not use detected device states as the only input for safety-critical or otherwise critical automations.

## Installation

Add this repository to the Home Assistant Add-on Store:

```text
https://github.com/BlueIceWolf/ha-nilm-addon
```

Then install **HA NILM Detector**.

## Required configuration

At least one phase sensor is required:

```yaml
home_assistant:
  phase_entities:
    l1: sensor.power_l1
    l2: ""
    l3: ""
```

The configured Home Assistant entity must expose a numeric power value in watts.

For three separately measured phases:

```yaml
home_assistant:
  phase_entities:
    l1: sensor.power_l1
    l2: sensor.power_l2
    l3: sensor.power_l3
```

The add-on uses the Home Assistant Supervisor API. In a normal add-on installation, a manual access token is not required.

## Web UI

The add-on exposes its web interface through Home Assistant Ingress.

Open the add-on and select **Open Web UI**.

The interface contains dedicated areas for:

- live power values
- detected events
- learned devices and patterns
- learning decisions
- debugging and pipeline information

## Learning behavior

The learning pipeline roughly follows this path:

1. Read power values from Home Assistant.
2. Detect changes and candidate events.
3. Add pre-roll and post-roll context.
4. Evaluate segmentation quality.
5. Extract features such as power, duration, rise/fall rate, plateau behavior and shape.
6. Match the event against existing patterns.
7. Store it as stable or provisional learning data.
8. Merge sufficiently similar patterns and refine classification.

The default configuration is designed to work without manual tuning. Adjust thresholds only when you have a specific reason and can verify the effect in the event and debug views.

## Important learning options

```yaml
learning:
  auto_pipeline_enabled: true
  auto_pipeline_interval_minutes: 30
  start_threshold_w: 30.0
  end_threshold_w: 12.0
  baseline_window_s: 5.0
  derivative_threshold_w_per_s: 120.0
  slope_threshold: 90.0
  hold_time_s: 6.0
  stabilization_grace_s: 12.0
  pre_roll_s: 20.0
  post_roll_s: 30.0
  ring_buffer_seconds: 10.0
  max_gap_s: 6.0
  pattern_match_threshold: 0.45
  ml_confidence_threshold: 0.60
  segmentation_threshold: 0.40
  stable_segmentation_threshold: 0.70
  min_samples_for_learning: 4
  min_waveform_score_for_provisional: 0.20
  min_waveform_score_for_final: 0.45
  merge_similarity_threshold: 0.86
  provisional_promotion_count: 3
  learning_starvation_window: 8
```

## Logging

Supported log levels:

```text
debug
info
warning
error
```

For troubleshooting, use:

```yaml
log_level: debug
```

## Storage

Default base path:

```text
/data/ha_nilm_detector
```

Default files:

```text
/data/ha_nilm_detector/nilm_live.sqlite3
/data/ha_nilm_detector/nilm_patterns.sqlite3
/data/ha_nilm_detector/nilm.log
```

The application also checks known legacy storage locations and migrates files when necessary.

## Home Assistant connection

The add-on is configured with:

```yaml
homeassistant_api: true
```

The default Home Assistant API endpoint inside the add-on is:

```text
http://supervisor/core/api
```

The runtime Supervisor token is used automatically when available. A manual token is only useful for non-standard setups.

## MQTT

MQTT support exists in the application but is **optional**. The main data source for the current add-on is the Home Assistant REST/Supervisor API.

Do not configure MQTT unless you specifically need the publisher functionality.

## Suitable loads

NILM generally works best when a load has a clear and repeatable signature.

Typical easier examples:

- refrigerators and freezers
- kettles
- coffee machines
- resistive heaters
- pumps and motors with repeatable cycles

More difficult examples:

- inverter heat pumps
- inverter air conditioners
- induction cooktops
- computers
- variable-speed appliances
- very small loads close to the household noise floor

Simultaneous switching events can also reduce classification quality.

## Troubleshooting

### Add-on does not start

Check that at least one phase entity is configured. The application intentionally rejects a configuration without a selected phase sensor.

### No live values

1. Check the entity in Home Assistant Developer Tools.
2. Confirm its state is numeric.
3. Confirm the entity ID in the add-on options.
4. Enable `debug` logging if necessary.

### Events are detected but no stable patterns appear

Check the learning/debug views. Events can remain provisional when segmentation or waveform quality is too weak for stable learning.

### Too many duplicate patterns

This can happen with variable loads or incomplete event windows. Version 0.6.44 includes fuzzy cluster merging and stricter segmentation handling, but duplicate reduction remains an active development area.

## Diagnostics API

The add-on exposes diagnostic endpoints used by the web UI, including:

```text
GET /api/training-log
GET /api/debug/pipeline-buffer
```

These are intended for troubleshooting and development.

## Privacy

Processing and persistence are local by default.

The optional export functions can create:

- full exports
- privacy-reduced shared pattern packs
- LLM review bundles

Exports happen only when explicitly requested by the user. Depending on the selected export type, an export can include detailed measurements and timestamps, so review the generated file before sharing it.


## Built-in AI classification

Version 0.7.0 keeps the complete recognition stack inside the add-on. No Ollama instance, external AI server or cloud API is required.

The classifier combines deterministic event segmentation, waveform/shape matching, local RandomForest ML and an attention-style prototype classifier. The attention stage compares an event feature vector with learned patterns and aggregates similarities using softmax weighting.

The system therefore remains fully offline and self-contained.

## Version

Current add-on version: **0.7.0**

See [CHANGELOG.md](CHANGELOG.md) and [RELEASE.md](RELEASE.md) for detailed release history.
