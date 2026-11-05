# Massachusetts imagery coverage — 4 November 2026

## Results

The Panoramax federated GeoParquet export had HTTP Last-Modified 1 November 2026 12:10:42 GMT. A DuckDB remote query selected the bounding box (-73.51, 41.20, -69.85, 42.90), returning 61,645 records. We filtered coordinates to the U.S. Census Bureau's 2024 1:500,000 Massachusetts state polygon and spatially joined to 2024 Massachusetts county subdivisions. After filtering and deduplicating IDs, the snapshot contains **45,895 images, 318 sequences and 135 named Census county subdivisions**. County subdivisions are used as a practical municipality proxy; duplicate names are grouped by name. State boundary simplification, GPS uncertainty and edge effects can misassign individual photos. Images can be taken off-road. These numbers represent available metadata in this weekly snapshot, not verified road coverage or provider-wide completeness.

| Capture year | Image records |
|---|---:|
| 2020 | 1 |
| 2021 | 4 |
| 2023 | 8 |
| 2024 | 7 |
| 2025 | 44,227 |
| 2026 | 1,648 |

The most recent recorded capture is 30 October 2026 in Shelburne; this is the latest in the snapshot, not necessarily the newest across all services. Images from 2026 occur in 25 subdivisions: 1,177 in Worcester and 385 in Shrewsbury, among others. Among all years, Framingham, Westborough, Plymouth and Auburn have the largest record counts. Counts overrepresent closely spaced images and do not measure road length or the number of visible signs.

45,860 records identify the OSM France Panoramax instance and 35 identify MapComplete; all 45,895 have CC-BY-SA-4.0 as their catalog license. Check individual source records and the federation's particular derived-data rules before publication. The catalog is a harvested subset of participating instances, updated periodically. Images hosted elsewhere, images not yet harvested, and other services are not counted. We did not validate each capture timestamp, location, viewpoint or license. Duplicates across services can exist.

Open **coverage.html** via the local server. Circles summarize 0.02-degree cells and link to their latest image. The capture-year filter is based on the latest image in each cell; counts include every year. The map is not a road-coverage map and some positions can be off-road. Detailed outputs: `data/panoramax_massachusetts_images.csv` (image metadata and URLs), `data/panoramax_towns.csv` (town summaries), `data/coverage_summary.json`, and `data/coverage_grid.geojson`. Metadata is included; downloading 45,895 photographs was not needed for coverage analysis.

## Other sources

- KartaView: its documented openstreetcam.org API hostname failed TLS verification on this machine, while `https://api.kartaview.org/2.0/photo/` returned responses. At Bowdoin Street, Worcester, a photo captured 24 November 2021 was returned (photo 1393206625, sequence 3960841). A separate first-page point query at 24 city/area centers returned one photo near Barnstable and zero at the other points. These point searches were limited, endpoint behavior and geographic search radius have not been validated, and zero is not evidence that a town lacks coverage. Raw responses are saved in `data/kartaview_samples.json` and `data/kartaview_bowdoin.json`. Further large-scale investigation should confirm API query semantics and the documented rate limits before crawling; imagery licensing and derivative rights must be verified.
- Mapillary: no personal access token was available in this environment. The API and coverage were not measured, and may materially change the result. Set up authorized access and run a separately documented collection; do not treat missing Mapillary data as a coverage gap. Review its image and data terms before bulk local processing or reuse.

## Model recommendation

The current prototype runs Ultralytics YOLO-World `yolov8s-worldv2.pt` using seven open-vocabulary labels, then Tesseract.js on a selected crop in the browser. It is an uncalibrated proof of concept. YOLO-World is not guaranteed to detect all classes, particularly small signs; browser OCR is not ground truth. Ultralytics licensing deserves review for deployment.

Test a local Qwen3-VL-4B-Instruct (or a suitably quantized version) **as a second-stage crop reader/classifier**, alongside the existing detector, not as a proven replacement. Ask for exact visible text, sign type and an explicit unreadable response; preserve the crop, raw output and model version for human review. Benchmark it against Tesseract and a dedicated scene-text OCR model on a held-out set of manually transcribed Massachusetts signs; measure exact text accuracy, false reads, class precision/recall, throughput and memory. Sign detection should also be evaluated separately against a dedicated traffic-sign detector with high-resolution tiled inference. Qwen's model card describes OCR capabilities, but has not been evaluated on these images here. This computer has an NVIDIA RTX 4060 Laptop GPU with 8 GiB VRAM; quantized 4B may be practical, but memory use and speed depend on the runtime, image size, context and other processes and must be measured. Never infer a legal turn restriction from an unreviewed model response.

## Reproduce

1. `python -m pip install -r requirements-coverage.txt`
2. Download the 2024 Census boundaries to `data/states.zip` and `data/towns.zip` from the URLs below.
3. Run `python extract_coverage.py`, then `python build_coverage.py`. This queries the current Panoramax export and overwrites the snapshot outputs; numbers may change. The export is around 25.6 GB but DuckDB reads remote parquet ranges rather than intentionally downloading the entire file.
4. Run `python -m http.server 8000` and open `/coverage.html`.

Sources: [Panoramax export](https://docs.panoramax.fr/federated-catalog/data_export/), [Panoramax federation and license requirements](https://docs.panoramax.fr/federated-catalog/), [Census state boundary](https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip), [Census Massachusetts subdivisions](https://www2.census.gov/geo/tiger/TIGER2024/COUSUB/tl_2024_25_cousub.zip), [KartaView API](https://kartaview.org/doc/photos), [Qwen3-VL-4B model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [Ultralytics license](https://www.ultralytics.com/license).

## Mapillary coverage layer

Run `python extract_mapillary_coverage.py` with `MAPILLARY_ACCESS_TOKEN` in the environment (on Windows it also reads the user environment). The script queries zoom 9 public sequence tiles that intersect the Census state polygon, filters decoded line vertices to Massachusetts, and groups their sequence IDs into 0.02-degree cells. It records request failures without including token-bearing URLs. The results are written to `data/mapillary_coverage_grid.geojson` and `data/mapillary_coverage_summary.json`; they can be selected in `coverage.html`.

Mapillary counts are **unique sequence IDs**, whereas Panoramax counts are **images**; they cannot be compared as if they were the same measurement. Tile geometry is simplified, clipped and sampled by vertices, so an occupied cell crossed between vertices can be missed. Sequences can extend across cells or the state line, and sequence dates do not provide per-road newest imagery. Tiles can omit partially processed imagery and may prioritize newer sequences when feature caps apply. This is an exploration layer, not a census, a percent of road mileage, or confirmation of the newest image at each point. API responses, date fields and timestamps have not been independently verified. See [Mapillary's coverage tile guidance](https://forum.mapillary.com/t/feedback-wanted-new-quality-score-field-on-mapillary-images-and-sequences/10397) and [tile cap discussion](https://forum.mapillary.com/t/incomplete-vector-tiles/8973/5).

On 4 November 2026, 19 of 19 zoom 9 Mapillary tiles were retrieved successfully. After testing sampled vertices against the state polygon, 100,189 unique sequence IDs touched 3,355 grid cells. The sequence-tile timestamps include 3,486 distinct IDs dated 2026 and 5,072 dated 2025; date values are unverified and may reflect device-clock errors (a few records have dates before 2013). A sequence can have multiple tile timestamps and occur in more than one year or cell, so group totals are not additive. No attempt was made to reconcile Mapillary and Panoramax duplicates. The exact run metadata is in `data/mapillary_coverage_summary.json`.

## KartaView and Mapilio added

On 4 November 2026, 19 of 19 KartaView zoom-9 tiles returned successfully and 2,099 0.02-degree cells contained at least one sampled coverage-track vertex in the simplified state boundary. These tiles do not contain image IDs, capture dates, or per-image licenses. A KartaView Worcester sequence returned 85 image records (2021); one image was downloaded for inspection.

All 51 Mapilio zoom-10 tiles returned successfully. They yielded 14 unique sequence IDs with sampled vertices in 50 grid cells; these are simplified tile geometries, not a count of photos or road mileage. One sequence intersecting Massachusetts returned 250 image metadata records (2023); one image was downloaded. The sequence-detail response does not supply image coordinates, so individual image locations have not been verified. Coverage gaps in either layer may reflect tile simplification, incomplete service data, GPS/boundary errors or actual gaps. No cross-provider deduplication or statewide completeness validation was performed.

The two downloaded image files are in `data/samples`; see `samples.html`. `data/other_image_manifest.json` contains source IDs, capture dates, creator identifiers, source and image URLs, and license/terms links for all 335 retrieved image metadata records. KartaView's creator ID is known, but its display name was not available from the tested public endpoint. Mapilio creator is eclipse. The two providers did not provide an image-specific license field in the responses tested; the manifest explicitly labels each license as the provider-wide published policy, not a verified individual license. Mapilio describes its imagery as CC BY-SA without specifying a version in its public policy. It separately says the policy is not a blanket grant for AI-generated datasets; clarify the intended GIS output and any redistribution before using it operationally. KartaView's terms describe CC BY-SA 4.0 and credit to Grab and KartaView contributors.

Terms references and retrieval-time snapshots are in `data/licenses`. The KartaView direct website returned a JavaScript shell to our request, so its saved HTML is not the full terms; `kartaview_terms_extracted.txt` is a search-index excerpt, not a complete legal snapshot. Use the live provider terms as authority. The CC BY-SA version and exact reuse obligations should be verified for the specific Mapilio imagery and intended output.

Neither KartaView nor Mapilio required an account for the tested public coverage, metadata and sample-image requests. Rate limits and private uploads may require one. The sample-fetch script and coverage extractor are `fetch_other_samples.py` and `extract_other_coverage.py`; repeated broad queries should respect provider limits.
