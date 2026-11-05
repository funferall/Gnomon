# Traffic regulations → GIS: plan

Goal: turn municipal *Traffic Rules and Orders* documents (legal schedules of stop signs, yield signs, turn and U-turn prohibitions, one-way streets, turn-on-red rules) into GIS layers with provenance. Do it for Wellesley first, then design so it scales to Massachusetts' 351 municipalities.

These documents are the legal source of truth for routing rules, yet almost no town publishes them as map data (see `research/ground_truth_sources.md`). The rows look like this:

```
LOCATED ON       AT                SO AS TO FACE
Abbott Road      Forest St.        Southbound drivers on Abbott Road (11/47)
Cameron St. at Washington St.  Northerly towards Washington St.  Left onto Washington St. (3/79)
```

They contain street names and directions, not coordinates. So the work is **extract → parse → geocode to an intersection → place → verify → review**.

## Design principle: deterministic first, models only where rules fail

| Stage | Deterministic (default) | Model (only when needed) | Always |
|---|---|---|---|
| 1. Acquire | Registry of town document URLs; download, hash, detect changes | Discovery agent searches town sites for the document (scaling only) | Store URL, retrieval date, SHA-256 |
| 2. Extract text | `pdftotext -raw` (keeps rows intact even where the layout drifts) | Vision model reads scanned or garbled pages | Page number and raw line kept per record |
| 3. Parse rows | Table schedules (stop, yield, turn-on-red): split *on / at / facing* by matching the town's street-name gazetteer, parse compass directions and the enactment date | Free-form schedules (turn prohibitions, one-way, U-turn, time conditions) → JSON schema, then the **same validators**: street names must exist in the gazetteer, directions must be valid | Unparsed rows go to a review list, never silently dropped |
| 4. Geocode | Intersection of the two street centerlines (TIGER now, MassDOT Road Inventory statewide). No geocoding service needed | Pick between several candidate intersections (streets that meet twice) | Every candidate kept, with an ambiguity flag |
| 5. Place | Sign on the approach leg matching the travel direction, set back from the intersection and offset to the right of travel; turn restriction as from-segment → node → to-segment | **AI placement**: the model sees the aerial image (with centerlines, the approach arrow and the deterministic point drawn on) and nearby street photos, and proposes a refined point | Result must pass gates: near the intersection, on the right approach and side; else rejected |
| 6. Verify | Match to imagery-detected signs (`asset_estimates`), human-placed assets, and the MassDOT sign layer on state roads | — | "Expected but not detected" and "detected but not in the regulations" both become review queues |
| 7. Review | Workbench queue: regulation row, deterministic and AI positions, photos | — | Reviewer, revision and evidence recorded |

Models never invent coordinates directly. They pick a pixel on an image whose georeferencing we control, and every output is checked by code. Every model answer is stored with provider, model, prompt version, cost and latency.

## Model

**The pipeline uses OpenAI `gpt-6-luna` only** (organisation policy: OpenAI; decided 5 November 2026). It is used for reading free-form schedules, and the aerial-placement experiment. Without a gold set, a record is accepted only when at least 2 of 3 independent runs extract it identically ("self-consistency"). Anything else goes to review.

The choice was made after a comparison against `claude-haiku-5-5` and `deepseek-flash` on the same tasks (results below). Luna-6 was the most accurate, the cheapest and the most reliable. The other providers were removed from the code.

## Outputs (per town, then statewide)

- `regulatory_signs.geojson`: stop, yield, no-turn and turn-on-red signs as points. Fields: town, schedule, kind, on/at streets, travel direction, facing bearing, conditions, enactment date, placement method, uncertainty, status, source (document, page, raw text).
- `turn_restrictions.geojson`: from-way / via-node / to-way, OSM-restriction-style (`no_left_turn`, `no_u_turn`, `only_…`), with time conditions.
- `one_way.geojson`: directed street segments between the stated limits.
- `unresolved.json`: rows that could not be parsed or geocoded, with the reason.

## Scaling to Massachusetts

1. **Registry** (`regulations/towns.yaml`): town, document URL, format (PDF text / PDF scan / HTML code site such as eCode360), template family, last hash. A discovery agent drafts it; a person confirms each URL once.
2. **Template families:** many towns derive from the same state model ("Schedule IV – Stop Signs… So as to face"), so a handful of deterministic parsers will cover most. Unknown layouts go to the model extractor with validation; agreement between two models, or with the rule parser, is required before auto-accept.
3. **One statewide road base:** MassDOT Road Inventory (street names, town, one-way) for geocoding everywhere. Town aliases learned from failures go in a per-town alias table.
4. **Change detection:** re-fetch monthly; when a document's hash changes, re-parse and diff records (added, removed or changed regulations) for review. Enactment dates in the rows (`(5/74)`) give history for free.
5. **Throughput and cost:** deterministic stages are free and run in seconds per town. Models run only on free-form rows and on placement. At about 100–300 rows per town, the whole state is roughly 50–100k rows, with placement calls at most one per sign.
6. **Publishing:** a statewide feature service with per-record provenance and review status, attributed to each town's document. Candidate contributions to MassDOT and OSM only after review and licence check.

## Status and results (Wellesley, 5 November 2026)

- [x] **Phase 1, deterministic** (`reg_harness.py`): 251 table rows → **238 regulatory sign points** (212 stop, 8 yield, 18 turn-on-red). Stop rows parse cleanly 92% of the time; 29 rows are unresolved with reasons (islands, squares, driveways, streets missing from TIGER).
  - Placement self-calibrates against imagery-triangulated stop signs. The setback went from 8.0 to 12.2 m and the offset from 5.5 to 6.1 m. Median error is **5.4 m → 4.4 m** (leave-one-out, n = 17; reference positions carry about 2 m error of their own).
- [x] **Phase 1b, model extraction** of free-form schedules (`reg_ai.py`, `llm_providers.py`), scored against a 21-record gold set, 3 runs each:

  | Model | Field accuracy | Exact records | $/run | s/run |
  |---|---|---|---|---|
  | gpt-6-luna | 99.5% | 20/21 | 0.0022 | 31 |
  | deepseek-flash | 99.5% | 20/21 | 0.0093 | 65 (1 of 3 runs hit the output cap) |
  | claude-haiku-5-5 | 98.4% | 18/21 | 0.0042 | 29 |

  Records where at least 2 models agree became **7 turn restrictions and 6 one-way segments**. One turn (Service Road) was flagged by the geometry gate. One-way directions agree with from→to geometry within 54°.
- [x] **Phase 2, AI placement on aerial imagery** (`reg_place_ai.py`), median error against triangulated signs:

  | Method | Median | Better than rule | Cost (17 signs) |
  |---|---|---|---|
  | Rule, self-calibrated | **4.4 m** | — | free |
  | gpt-6-luna | 5.3 m | 8/17 (vs uncalibrated rule) | $0.014 |
  | claude-haiku-5-5 | 6.0 m | 11/17 | $0.007 |
  | deepseek-flash | 6.6 m | 9/17 | $0.117 |

  **Finding:** from 11 cm aerials, models do not beat a calibrated rule, because sign posts are mostly invisible from above. Use models where they are strong: reading documents (Phase 1b), and checking street-level photos.
- [ ] **Next: targeted street-level verification.** For each expected sign *not* yet detected (190 of 212 stop signs so far), select camera views facing the expected location. Ask a vision model "is this sign visible, and where?" Triangulate the box with the existing SfM pipeline (`asset_localization.py`). This turns "expected" into "observed" with metre-level positions.
- [ ] Phase 3: workbench layers and review queue for regulation records (expected-but-not-detected, detected-but-not-regulated).
- [ ] Phase 4: town registry and a second town (Newton has a public stop-sign layer to validate against).

**Model choice:** gpt-6-luna only, with 2-of-3-run self-consistency in place of cross-model agreement. On Wellesley that holds back 6 records (5 U-turn rows whose direction varies between runs, and 1 private way). None of them feed the turn or one-way layers.
