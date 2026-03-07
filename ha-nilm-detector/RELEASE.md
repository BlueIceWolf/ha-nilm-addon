# Release 0.2.8

## Store Kurztext
- Multi-Phasen-Verlauf mit ein-/ausblendbaren L1/L2/L3 Linien in der Web-UI.
- Interaktive Bereichsmarkierung im Graphen zum manuellen Lernen von Mustern.
- Erweiterte lokale NILM-Features für bessere Erkennung ohne Cloud und ohne PyTorch.

## Highlights
- Added multi-phase chart visualization with per-phase toggle buttons (Total/L1/L2/L3).
- Added "Bereich markieren" flow to select chart intervals and create patterns manually.
- Added API endpoint `POST /api/patterns/create-from-range` for manual pattern creation.
- Added advanced lightweight feature extraction (rise/fall rate, variance, duty cycle, substates).
- Improved local similarity scoring and appliance heuristics with shape-aware features.

## Notes
- All learning remains local in Home Assistant (privacy-first, no cloud dependency).
- Existing nightly automatic learning window (02:00-05:00) remains active.
- Use manual range selection in the chart to speed up labeling during test phase.
- Update via Supervisor by refreshing the repository and reinstalling the add-on.
