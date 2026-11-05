# Gnomon

Find roadside assets (signs, hydrants, signals, covers) in street-level imagery and estimate where they **physically** are, not just where the camera stood. Pilot: Wellesley, MA, using Mapillary and Panoramax imagery.

- `PLAN.md`: project overview, sources, and statewide plan
- `LOCALIZATION.md`: how detections become map positions (Mapillary SfM geometry, fused range cues, multi-view triangulation, self-calibration) and the accuracy benchmark against the town hydrant layer
- `POSITION_ERROR_AND_SIGN_PLACEMENT.md`: camera-position errors and placement rules
- `WELLESLEY_METHODOLOGY.md`, `COVERAGE.md`, `TOWN_COVERAGE.md`, `REVIEW_AND_BENCHMARK.md`: inventory, coverage, and review notes

Data, imagery, databases, model weights and `.env` (holds `MAPILLARY_ACCESS_TOKEN`) are not committed; the scripts regenerate them. Machine estimates are unreviewed. Check each image source's license before reuse.
