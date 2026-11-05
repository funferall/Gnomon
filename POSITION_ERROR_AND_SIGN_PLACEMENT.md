# Roadside imagery position errors and provisional sign placement

Prepared 4 November 2026 for the Wellesley asset-mapping prototype.

## Finding

The latitude and longitude attached to a street photograph can be wrong even when the image is clear and neighboring photographs form a smooth track. A systematic GPS or timing error can produce an apparently plausible image sequence running parallel to its actual road. Any sign locations triangulated from those camera positions can inherit that displacement. Coordinate projection is a different issue: the example investigated here is consistent with an error in the source camera positions, rather than evidence of a Leaflet map-projection bug.

Keep four kinds of geometry distinct: the original source camera position; a provider-computed camera position; a proposed or reviewed local camera-position correction; and the physical asset position inferred or manually placed from the images. They have different provenance and uncertainty. A camera marker must not be interpreted as a sign location.

## Wellesley example: May 14, 2026

The user reported a track from contributor **Lanka6359** (creator ID `1139817854492667`) running through a field southeast of the correct, parallel road. The inventoried records include 81 processed images associated with this contributor and date, across two sequences at the time of the initial check. The principal affected sequence is `ZXP7Qb6saomwWY423nTKNV`. The investigated portion contains **79 inventoried images**, from `2026-05-14T08:22:08.333+00:00` through `08:22:23.966+00:00`. That is the sampled interval, not a claim that all images in the full source sequence have been retrieved.

A representative [Mapillary image, ID 1932449260723461](https://www.mapillary.com/app/?pKey=1932449260723461), shows a two-way road with a double yellow line, farm fencing on the left, a hydrant on the right, and a street-name sign reading Schaller Street. These visible features and the user's report support investigating Washington Street/Route 16 as the traveled road. They do not by themselves establish surveyed camera coordinates.

| Position for this representative image | Longitude | Latitude |
|---|---:|---:|
| Original API geometry | -71.311108383333 | 42.275764950000 |
| Mapillary computed geometry | -71.311106804950 | 42.275762630615 |
| Local proposed translation | -71.311657226242 | 42.276187078428 |

The representative image also has a visible GPS/time watermark. Its displayed GPS (`N42.275635 W71.311296`) is not identical to the API point, which is another reason to audit frame timestamps, interpolation and camera/GPS synchronization. The watermark is additional source evidence, not independent surveyed truth.

The original point is **8.29 m from the mapped Schaller Street centerline** but **64.58 m from Washington Street** in the Census road reference. Thus an individual nearest-road snap could choose Schaller Street even though the sequence direction and street scene support a different traveled road. The position-QA implementation flags the representative image because its track direction disagrees with the nearest road.

For all 79 investigated images, Mapillary computed positions differ from original GPS positions by a median **1.11 m**, with a maximum **5.65 m**. Those computed positions are useful independent API evidence but do not remove the roughly 65 m discrepancy in this example. The application previously requested only the original `geometry` field, not `computed_geometry`.

A robust translation was fitted to the nearby **Washington Street** reference line in **EPSG:26986**, whose units are meters:

- Easting adjustment: **-45.38 m** (west).
- Northing adjustment: **+46.79 m** (north).
- Total translation: **65.18 m**, approximately northwest.
- Median distance to that reference road: **64.94 m before**, **0.54 m after**.
- 90th-percentile distance: **65.95 m before**, **1.11 m after**.

**These after-fit distances are residuals against the chosen road centerline, not demonstrated positional accuracy.** Fitting points to a road necessarily makes them close to that road. The reference line is Census TIGER/Line 2024, not a surveyed vehicle trajectory. Vehicles normally occupy lanes rather than the centerline. A straight parallel road cannot constrain error along the road: the sequence might still be too far forward or backward after this fit. Intersections, driveway edges, distinct buildings, visible sign supports and other visual tie points must be checked in the roadside and aerial imagery before approval. The correction remains **proposed**, not approved. Its application is limited to the investigated capture-time interval; it must not silently propagate to other parts of the sequence.

## Other forms of error to expect

1. **Constant lateral offset:** the entire track is shifted sideways; a short-window translation can sometimes help.
2. **Slow drift:** the displacement changes through time; a single translation is inadequate. Fit a piecewise smooth correction anchored by independently verified tie points.
3. **GPS spikes or impossible jumps:** isolate outlier observations rather than bending the whole route to accommodate them.
4. **Camera/GPS clock mismatch:** a correct GPS track is attached to the wrong video times. This often creates along-road errors that change with speed or appear clearly at turns. Estimate a time offset from turns/stops and visual landmarks before considering a spatial warp.
5. **Wrong or uncertain camera heading:** pixel bearings can be wrong even when camera GPS is usable. Preserve and compare source and computed headings. A forward-facing camera assumption is unsafe for side-facing cameras and panoramas.
6. **Ambiguous or incomplete road reference:** parking drives, new roads, paths, bridges, divided carriageways and parallel roads can defeat simple proximity rules. A photograph can legitimately be off-road. A road-distance flag is a request for review, not proof of an image error.
7. **Different capture dates:** the roadside photograph, reference road network and aerial imagery may show different construction states. Comparison across 2021, 2023 and 2025 imagery helps reveal this.

Mapillary documents that image-location accuracy affects reconstructed map-feature positions, and that its original and computed positions are distinct. See [Mapillary map-feature guidance](https://help.mapillary.com/hc/en-us/articles/115002332165-Map-features), [original versus computed positions](https://forum.mapillary.com/t/sfm-lat-lon-not-in-api-lat-lon-question/2881/3), and its [GPS synchronization guidance](https://help.mapillary.com/hc/en-us/articles/115001717829-Using-a-separate-GPS-device-with-your-camera). Provider-computed positions should be checked, not treated as automatic ground truth.

## General camera-position correction method

**Preserve and compare.** Retain original GPS, timestamps, source/computed headings and positions, sequence ID, creator, API retrieval date and raw metadata. Keep derived camera transforms in a separate, versioned table with a capture-time range, method, residual diagnostics, reviewer and reason. Never overwrite the provider geometry or submit changes back to the provider as part of this local workflow.

**Detect at both image and sequence levels.** Measure distance to plausible roads and compare local track direction with nearby road tangents. Look for consistent cross-track offsets, abrupt changes, implausible velocities, discontinuities and disagreement between original and provider-computed positions. Track direction should come from neighboring camera locations when appropriate; the camera can face sideways relative to travel. Use road names, intersections, visible restrictions, aerial landmarks and trajectory continuity to disambiguate candidates. Check both individual images and the distribution of errors across a sequence.

**Match the whole route.** A general implementation should use several candidate roads per observation and score distance, heading, connectivity, travel direction, speed and transition continuity. A hidden-Markov/Viterbi or comparable trajectory-matching approach can choose a coherent route while retaining competing hypotheses. Short windows with consistent errors can use robust translation or rotation fits. Other windows may require timing correction, piecewise adjustments, or visual reconstruction tied to independent ground controls. Do not force every point onto the nearest road.

**Validate before applying.** Hold out some visual tie points from the fit. Inspect intersections and corners because they constrain along-road error better than a long straight segment. Compare plausible parallel-road hypotheses. Preserve lane offsets rather than equating vehicle position with road centerline. Report uncertainty and failure cases. If evidence cannot distinguish roads or positions, retain multiple candidates or an unresolved flag.

**Propagate carefully.** Approved camera adjustments affect ray directions/positions used for asset localization, duplicate association and network-edge assignment. Recompute those derived products and record their dependencies. Do not silently move a human-placed asset. A small reprojection or road-fit residual alone cannot justify an asset's positional-accuracy claim.

## First assumed placement of signs

The aim is a useful provisional location that a reviewer can refine, not an arbitrary point presented as a precise inventory feature. The statement that '99% of signs are near roads' should be treated as a working prior until measured on this dataset. Useful exceptions include signs for another nearby road, signs across a median, gantries, parking/access roads and off-road signs. Hydrants, drains and covers need separate placement priors.

1. **Resolve the camera's likely road and position quality first.** Prefer an independently validated pose. If the camera is flagged or its correction is only proposed, mark all derived asset estimates accordingly and widen uncertainty. A camera-location correction is not an asset-location correction.
2. **Estimate a viewing ray.** Use camera intrinsics, distortion, orientation and the correct panorama-face transform. In a calibrated pinhole view, the horizontal angle is approximately `atan((u - cx) / fx)`, where `u` is the object's pixel center; rotate the complete 3D ray by the camera pose and recorded face yaw/pitch. Use the full calibration model where needed. Without reliable intrinsics or heading, produce an uncertain region rather than a confident point.
3. **Represent the initial estimate as a range or region.** If no defensible distance is available, use an explicitly labelled broad distance prior along the viewing ray. Display its provisional representative point together with a search wedge/uncertainty region; do not imply that a guessed range is measured depth. Metric-depth predictions or standard sign dimensions can supply additional range hypotheses only after domain validation. Upscaling tiny boxes does not restore missing information.
4. **Use road proximity as a soft constraint.** Intersect plausible ray/range hypotheses with likely roadside corridors, based on the correct traveled road and estimated road width. Include near-verge, far-verge, median and overhead alternatives when visible. A strong ray consistent with a sign on the far side of the road should not be replaced by a closer near-side snap. Retain alternate road assignments at intersections and parallel roads.
5. **Determine the correct side in world coordinates.** Use the road's local tangent and the world-space asset estimate, together with travel direction. A sign on the right side of an image is not necessarily on the right side of the traveled road: the camera can face sideways or backward, and the sign may serve a crossing road. Compare sign face, support and observed approach direction across views. Keep physical sign position, sign-facing direction and affected traffic approach as separate attributes.
6. **Refine with aerial imagery and landmarks.** Compare the provisional region with pavement edges, verges, driveways, intersections, median islands, shadows and visible sign supports in the 2021/2023/2025 MassGIS imagery. Aerial imagery often cannot resolve a small sign face; it helps constrain its support and context. Align ground-level landmarks and road edges rather than assuming the newest aerial imagery is contemporaneous with the source photo. Do not confuse the bottom of a sign-panel box with a post's ground-contact point.
7. **Refine with multiple images.** Match the same physical sign across frames and passes. Intersect calibrated rays robustly or use a 3D reconstruction, rejecting weak baseline, nearly parallel rays and inconsistent observations. Estimate uncertainty from camera pose, matching and range/depth errors. A sign center can be reconstructed in 3D and projected to horizontal map coordinates; a ground-plane intersection is appropriate only for a verified ground-contact/support point.
8. **Let the reviewer finish and record provenance.** Show the original images, alternate positions, uncertainty and source dates. A reviewer can drag the provisional marker, select the correct road side and link repeat observations to one asset. Save the method, old/new coordinates, reviewer, reason, uncertainty and affected network approach. Keep unresolved candidates visible. Validate a representative sample against surveyed or field-observed assets before claiming location accuracy.

For the first implementation of automatic placement, use separate states such as `camera_only`, `provisional_ray_region`, `multi_view_estimate`, `human_placed` and `field_verified`. Keep provisional point/region layers distinct from the reviewed asset inventory. Avoid a narrow numeric uncertainty if calibration is unverified. Regulatory meaning and network applicability require additional review of text, arrows, exceptions, conditions and approach direction; physical proximity alone does not create a routing rule.

## What is implemented

- `position_quality.py` preserves original image coordinates and can enrich a chosen sequence with Mapillary original/computed pose metadata. All 79 images in the investigated interval were enriched.
- A town-wide positional QA snapshot was run on **63,014 inventoried camera records**. The checks use distance to local/secondary/primary/ramp road references and track-versus-nearest-road direction. Flags are screening indicators, not a confirmed error rate. This is a snapshot while ingestion continues.
- The Washington Street example has a stored **proposed** translation with fit statistics and a capture-time validity range. Original `images.lon/lat` values were not changed. A pose correction is not an approved sign location.
- `image_pose_metadata`, `position_qa`, `sequence_alignments` and `alignment_events` retain separate provenance and review state. `data/wellesley/position-quality.json` and `position-shifts.geojson` expose the diagnostic snapshot and proposed shifts without credentials.
- Both viewers now have a **Camera positions** selector: Original GPS, API computed, Preview QA proposals, and Approved corrections. The preview moves affected camera markers only. An API-computed coordinate is available only for images actually enriched; otherwise the display falls back to original GPS.
- In the local reviewer, the Camera position QA panel exposes available flags and alignment information. Approval or reversion requires reviewer initials and a note describing visual checks, and is audited. Approval changes which camera positions the display can use; it does not overwrite source coordinates, move manually placed assets, or automatically re-triangulate signs. No correction for this example has been approved by the program.
- The human reviewer already supports manual asset placement on MassGIS aerial imagery, uncertainty entry, label/text/routing-role correction, duplicate linking and undo. It does **not yet automatically generate sign-ray/range regions, triangulate physical sign positions, solve camera timing errors, run full probabilistic route matching, or determine every sign's correct road side**. Those are the next implementation stages described above.
- Database write periods were shortened during API enrichment, and scan connections now wait longer for transient locks; a worker stalled during the initial QA enrichment was restarted. Inference need not be rerun solely because a camera's geographic position changes; geometry-dependent asset estimates do need recomputation once that stage exists.

## Reproduction

```
python position_quality.py enrich --sequence ZXP7Qb6saomwWY423nTKNV
python position_quality.py propose --sequence ZXP7Qb6saomwWY423nTKNV --road "Washington St"
python position_quality.py qa
python position_quality.py export
python review_server.py
```

Review at **http://localhost:8001** or inspect the read-only viewer at **http://localhost:8000/index.html?dataset=wellesley**. Refresh the page after these updates. Select Preview QA proposals to inspect the May 14 sequence's proposed shift; compare against Original GPS and aerial layers before approval. Image inference and inventory continue independently, so snapshot counts will change. Proposals are local, time-bounded and reversible; they do not edit Mapillary.
