# Massachusetts roadside imagery pilot

## Run the prototype

From PowerShell in this folder:

```
python -m pip install -r requirements.txt
python roadside.py --limit 10
ollama pull lfm3-vl:2b
ollama serve
python -m http.server 8000
```

Open http://localhost:8000. The first inference run downloads YOLO-World weights and its text encoder; it may require additional network access and takes time on CPU. Internet access is also required for imagery, Leaflet and map tiles. Sign OCR uses the local LFM3-VL-2B vision model through Ollama; its first model load may take several seconds, while warm requests run in well under a second on the available GPU. To inspect coverage without installing the detection model, run `python roadside.py --inventory --limit 10` (requires `requests`). To use another small area, provide `--bbox west,south,east,north`. The API returns one page, at most 50 images, with no demonstrated newest-first ordering; this is not a coverage census and does not guarantee the latest image. Re-running overwrites the GeoJSON. API and model errors need attention at the console.

Orange markers indicate at least one model candidate, blue markers show an image with no candidate or an inventory-only image. Each point represents the camera position, not an asset location. Click for the capture date, contributor, license, image and candidate labels. Results are unreviewed, may overlap, and are not a complete inventory. Sign crops can be read with a local vision model. Physical object positions are now estimated separately from camera markers (see LOCALIZATION.md and assets.html: about 2.1 m median error on Wellesley hydrants vs 7.1 m for camera GPS); they are unreviewed, and the program does not produce turn restrictions.

## What we established (4 November 2026)

A live request to the Panoramax OSM France instance returned images in downtown Worcester. The pilot focuses on Bowdoin Street near Chestnut Street, including photographs captured 6 June 2026. A downloaded image (data/sample.jpg) visibly shows Chestnut and Bowdoin street-name signs, stop signs, and a fire hydrant. A local YOLO-World run on three nearby images returned nine unreviewed candidates: street-name signs, general traffic signs, and a hydrant. This is a smoke test, not a measured precision or recall result. This proves that suitable free imagery and observable targets exist at this location; visual inspection is not a model accuracy test. Individual STAC records link to CC BY-SA 4.0 and identify the contributor. Confirm each record's license and attribution before reuse; source terms and licenses can change. Preserve creator, license, image link, collection and timestamp for derived data.

A very small, non-representative test queried one 0.01° × 0.01° box centered on each city center, with the first page capped at 10 images. Worcester returned 10; Boston, Springfield, Pittsfield, Lowell and Barnstable each returned zero. A separate box on I-90 in Grafton returned 10 with November 2025 captures. A capped result is not a count of all photos; zero means only that this particular Panoramax instance returned no items in that box at query time. Neither result measures coverage of a city, other instances, providers, or the state. The 2026 photo is recent, but there is no evidence it is the latest available across providers.

## Sources and choices

- [Panoramax STAC API](https://docs.panoramax.fr/backend/api/api/) exposes images and metadata; [use guidance](https://docs.panoramax.fr/how-to-contribute/use-panoramax/) says to respect image licenses. Panoramax is federated; one instance is not a complete catalog.
- [Mapillary map data](https://help.mapillary.com/hc/en-us/articles/4407521157138-Downloading-map-data-via-the-Mapillary-web-app) advertises 1,500 traffic-sign and 42 point-feature classes, with downloads and terms. Compare it as a separate provider and establish current access, API limits and rights for bulk local processing and derived inventory before building a statewide pipeline. The chat's blanket assumption that all imagery has identical rights should not be relied on.
- [KartaView](https://kartaview.org/doc/faq) describes free street imagery and location/date search. Verify functioning access, image licenses and actual Massachusetts observations before including it.
- [MassGIS Roads](https://www.mass.gov/info-details/massgis-data-massgis-roads) is a statewide, regularly refreshed road-centerline denominator, not imagery or a ready-to-route network. Its duplicate coincident routes should be handled when measuring unique road length.
- [Ultralytics license](https://www.ultralytics.com/license) must be reviewed before deployment; open source does not mean unrestricted commercial licensing. Inference is local but model weights must be downloaded.

## Plan toward a reliable statewide inventory

1. Acquire MassGIS road centerlines and municipality boundaries. Split or sample unique road geometry at a declared interval (e.g. 25 m), exclude non-target road types explicitly, and store a stable denominator. Deduplicate coincident geometry. Do not equate photo counts with road coverage.
2. For each provider, inventory all available sequences using documented pagination and rate limits; retain query time, capture time, heading, image location, license, links and attribution. Spatially match to road samples within a stated tolerance (e.g. 25 m), with a sensitivity check at 10 and 50 m. Report road length with imagery, date distribution, newest available capture per sample, municipality and road class; identify gaps, heading limitations and unknown dates. Query Panoramax federation, Mapillary and KartaView separately; union only comparable and authorized records. Tile the state with overlap and deduplicate image IDs. Record API failures separately from true empty areas.
3. Select a stratified set of urban, suburban and rural streets and manually label all visible objects in held-out images. Measure precision and recall by class, size, municipality and imagery age, plus OCR exact-match accuracy. Split by street/sequence to prevent adjacent-frame leakage. Inspect difficult signs and occlusion. Benchmark against Panoramax images and, where authorized, Mapillary's existing detections.
4. Improve local vision using high-resolution tiled detection, a US traffic-sign classifier and OCR for street names and numeric limits. Preserve bounding boxes, scores, model versions and original images/links. Review candidates with a UI that overlays boxes, allows edits and records evidence and reviewer. Current open-vocabulary labels are uncalibrated and can miss small signs or confuse categories.
5. Estimate asset position from multiple calibrated views, camera pose and triangulation or depth, with uncertainty; cluster observations without merging nearby distinct signs. Human review can place points where geometry is inadequate. Road-side and approach association requires heading, geometry and context. Never present camera GPS as a surveyed feature location.
6. For routing, map only reviewed restriction signs to incoming and outgoing network edges and conditional rules, check orientation, exceptions and current validity, then validate against Overture connectors and local ground truth. A stop sign alone is not a turn restriction. Preserve source, dates, confidence, reviewer and uncertainty.
7. Estimate compute, image egress, storage and review labor from the pilot before scaling. If gaps remain, coordinate collection with MassDOT/municipalities or run an openly licensed capture campaign; verify rights and acquisition costs. No evidence currently supports complete or uniformly recent statewide coverage from free sources.
## Using the image viewer

The map markers represent cameras. Select a marker or use the arrows in the viewer to move between images. Drag the divider to resize the map and viewer; it also responds to the up and down arrow keys when focused. Candidate icons and boxes identify detection classes; click a detection or its box to see a separate enlarged crop. Sign OCR runs locally through Ollama using LFM3-VL-2B and displays the result under the crop. Set `window.VISION_OCR_MODEL` before loading the app or pass `?ocrModel=<model>` in the URL to use another installed Ollama vision model. Recognition can be wrong or empty, especially for small or oblique text. No recognized text is saved to the GeoJSON. Panoramax imagery, map tiles and Leaflet still require internet access.
