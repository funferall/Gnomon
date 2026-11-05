# Estimating physical asset positions from street imagery

Prepared 4 November 2026. This implements stages 2–3 and 7 of the sign-placement plan in `POSITION_ERROR_AND_SIGN_PLACEMENT.md`: automatic ray/range regions and multi-view triangulation. Output is a separate layer of **unreviewed machine estimates**. It never edits provider coordinates, human placements (`assets`) or reviews.

## The idea in one paragraph

Mapillary does not just store a GPS point per photo. For most imagery it has run structure-from-motion (OpenSfM), and its API exposes the result: an SfM-refined camera rotation, an SfM camera position, and a per-image **mesh**, which is the triangulated 3D points that camera actually saw, in metric camera coordinates. That turns every detection box into a measurement. The box gives a precise world bearing, and the SfM points inside the box give its distance. Three further independent range cues back that up: a ground-contact ray against a road plane measured from the same points, the box's angular size against standard object dimensions, and a monocular depth map rescaled to the SfM points. The cues are fused with outlier rejection. Sightings of the same object across frames and separate drives are then triangulated jointly. The system calibrates itself with no ground truth. Wellesley's published hydrant layer is held out purely to score accuracy.

## Verified conventions (not assumed)

- `computed_rotation` is an OpenSfM world→camera angle-axis in local ENU. The camera centre `C = −Rᵀt` reproduces the API `computed_geometry` to 10⁻¹² degrees.
- Mesh vertices are in camera coordinates of the atomic reconstruction. `world = C + Rᵀ(v / atomic_scale)` matches the downloaded `sfm_cluster` point cloud with a **1 mm** median residual. The first eight vertices are a placeholder cube and are dropped.
- **Raw `compass_angle` is unusable for these panoramas.** On a sample GoPro Max image it read 340°, while SfM said 72°. Every bearing here uses `computed_rotation`, and images without an SfM pose are skipped rather than guessed.
- Cube-face pixels map to camera bearings by the exact inverse of `wellesley_pipeline.views()`. Unit tests cover round trips, face orientation, distortion models, and a synthetic camera 2.2 m above a road.
- ENU directions are rotated into EPSG:26986 grid north (about 0.1° convergence in Wellesley). Positions are solved in metres.

## Per-detection range cues (`observation_geometry`)

| Cue | How | Why it is trustworthy |
|---|---|---|
| `sfm` | Nearest coherent depth group among SfM points projecting inside the box | Triangulated geometry, not inference |
| `mono` | Depth Anything V2 Small (Apache-2.0) per face, affine-fitted `1/z = a·D + b` to that face's SfM points (`depth_cue.py`, GPU) | Dense, so it covers boxes with no SfM points. Used **only** when `sfm` is absent, so evidence is not double-counted |
| `ground` | Bottom-centre ray (hydrant, bollard) or centre ray (cover, drain) intersected with a RANSAC road plane fitted to SfM points 2–25 m around the camera | Camera height is **measured per image** (1.8–2.7 m observed, about 6 cm plane RMS) |
| `size` | Angular box height vs standard height (MUTCD stop 30″, speed limit 30″, hydrant about 0.78 m, …) | Weak alone; self-calibration measures and corrects its bias |

Cues are fused by inverse variance in log-range. The most inconsistent cue is dropped while any normalized residual exceeds 3σ, and the conflict is recorded as a flag.

## Multi-view association and solve (`asset_estimates`)

For each class, sighting pairs within 25 m pass a cheap gate (agreement within combined along-ray spread, different images). Each pair is then solved for real. Pairs are merged greedily in order of fit quality. A merge is accepted only if no image contributes twice and every bearing/range residual in the joint robust Gauss–Newton solve stays under 3.5σ, and only if the solution lies in front of every camera. The covariance is scaled by the reduced χ², plus a georegistration floor per independent drive. The output is a 95% ellipse. States are `multi_view_estimate` (≥2 views with ≥4° ray spread) or `provisional_single_view`.

## Self-calibration without ground truth (`localization-calibration.json`)

1. Objects with ≥3 rays and ≥12° spread are re-triangulated from **bearings only**. That pseudo-truth is independent of every range cue.
2. For each class and cue, the log-range bias and robust spread against it are measured. Later passes remove the bias and use the measured spread.
3. Bearing noise is measured from the same residuals.
4. The camera georegistration floor is measured by solving each drive's sightings of the same object separately and taking their disagreement beyond internal covariance.

## Running it

```
python asset_localization.py ground-truth     # town hydrant layer, adopter personal fields never requested
python asset_localization.py enrich           # SfM pose + mesh per image with detections (resumable)
C:\Users\mmulq\miniconda3\envs\TDA\python.exe depth_cue.py   # SfM-anchored monocular depth (GPU, resumable)
python asset_localization.py run              # localize → associate → calibrate → localize → associate → evaluate → export
python -m http.server 8000                    # then http://localhost:8000/assets.html
```

`assets.html` shows estimates by class with uncertainty ellipses, rays from every camera that saw the object, per-cue ranges, evidence crops and source views, and the town hydrant layer as a toggle. `#estimate=<id>` deep-links one estimate. Re-run `enrich`, `depth_cue.py` and `run` after the scan worker adds detections.

## Results

Snapshot of 4 November 2026: 10,830 detections across 4,292 SfM-posed images became **3,186 estimated assets**, 1,308 of them triangulated from multiple views. 495 detections had a bearing but no usable range (`ray_only`). 518 had no Mapillary SfM pose.

**Hydrant accuracy against Wellesley's published hydrant layer** (1,278 points; town GIS of unknown survey grade; never used for fitting). The match is the nearest town hydrant within 15 m. That measures placement of real hydrants, not detector precision. 156 estimates matched 110 distinct hydrants.

| Position used as the hydrant location | n | median | p90 | ≤ 2 m | ≤ 5 m |
|---|---:|---:|---:|---:|---:|
| Camera GPS (what the viewers previously showed) | 156 | 7.09 m | 19.14 m | 8% | 30% |
| Single detection, fused range | 883 | 2.07 m | 4.38 m | 48% | 94% |
| Estimated asset, single view | 49 | 2.24 m | 7.69 m | 41% | 88% |
| Estimated asset, triangulated | 107 | 2.02 m | 4.21 m | 50% | 96% |
| **All estimated assets** | 156 | **2.12 m** | 4.46 m | 47% | **94%** |

Range cues against the bearing-only pseudo-truth (median range ratio, robust log spread, n):

| Class | sfm | ground | mono | size |
|---|---|---|---|---|
| fire hydrant | 0.996 · 4% · 600 | 0.986 · 8% · 750 | 1.056 · 12% · 152 | 0.965 · 13% · 743 |
| stop sign | 1.001 · 4% · 529 | — | 1.386 · 29% · 203 | 0.918 · 8% · 712 |
| street name sign | 0.997 · 4% · 378 | — | 1.266 · 17% · 365 | **0.615** · 18% · 677 |
| traffic light | 1.004 · 4% · 1563 | — | 1.035 · 23% · 482 | 0.877 · 23% · 2046 |
| traffic sign | 0.997 · 4% · 1727 | — | 1.187 · 19% · 939 | 1.344 · **66%** · 2553 |

What this shows:

- **The SfM cue is unbiased to within 0.5% for every class**, at the 4% floor of the measurement. The road-plane ground cue is almost as good for hydrants. The self-calibration also found that my street-name-blade height prior was 38% off and the generic "traffic sign" size cue is nearly uninformative, and it corrects or down-weights both automatically.
- **More views do not reduce absolute error.** Triangulated objects have a median *relative* 95% precision of ±0.26 m, but absolute error against the town layer stays about 2 m. The remaining error is shared by all sightings: Mapillary's georegistration of the SfM model to GPS, plus the town layer's own error. They cannot be separated without surveyed truth. Cross-drive disagreement measured 0.0 m over 4,655 pairs because Mapillary merges overlapping drives into one reconstruction.
- The absolute 95% ellipses therefore include a measured 1.8 m-per-axis floor. Two-fold spatial cross-validation of that single scalar gave 87% and 95% coverage. In the full run the ellipse contains the town point **91%** of the time. The map shows both the absolute radius and the relative precision.

## Limits

- Accuracy is measured only for hydrants, against a town GIS layer of unknown survey quality. Other classes inherit the method and the self-calibration but have no independent check.
- Precision of the *detector* is not addressed. A false detection still gets a confident-looking position. Review remains required.
- Traffic lights are located at the signal head, often over the road on a mast arm, not at the pole.
- Association is per class. A stop sign and the street-name blade on the same post stay separate estimates, and so can one sign labelled differently in different frames.
- Images without a Mapillary SfM pose (and Panoramax images) get no estimate. Approved sequence corrections are applied to camera centres. Proposed ones only add a flag.
- I tested correcting each drive's offset with known hydrants as ground control. With leave-one-hydrant-out it made errors **worse** (median 1.4 → 2.5 m, n = 33). The residual error is per-object, not a per-drive shift, so this was not adopted.
