# Existing roadside-asset data: Wellesley and Massachusetts

Checked 5 November 2026 (three web-research agents, with key items re-verified by direct queries). VERIFIED means the service or document was fetched and counted. LEAD means it was seen but could not be confirmed.

## Wellesley

| Source | What it holds | Count / date | Use for Gnomon |
|---|---|---|---|
| [Traffic Regulations PDF](https://www.wellesleyma.gov/2000/Traffic-Regulations) (VERIFIED, 71 pp., cover "Updated January 2026") | Legal schedules: one-way streets (Sched. II), U-turn and turn prohibitions (III, III-A), stop signs as *on / at / facing* (IV), yield (VIII), right-turn-on-red (IX–X), mandatory turn lanes (VI). No local speed schedule. | text PDF, ~700 KB | **Best ground truth for routing signs.** Needs parsing and geocoding to intersections. |
| `Available_Hydrants` + `Adopted_Hydrants` (VERIFIED) | Hydrant points | 1,109 + 169; last edit 2026-10-13 | Already the hydrant accuracy benchmark. Adopter contact fields are never stored. |
| `Open_Data_Layers` (VERIFIED) | Road centerlines (class, ownership, surface; no speed or one-way), sidewalks, driveways, buildings, parcels | 1,534 centerlines; last edit 2026-10-29 | Road reference; no signs. |
| `OpenDataLayers2` (VERIFIED) | Curb ramps 1,617, sidewalk centerlines, public shade trees 7,750 | last edit 2026-10-29 | Context only. |
| `Impervious_Surface_Public/2` "Drain BMPs" (VERIFIED) | 841 stormwater BMPs (bioretention, leaching basins) | last edit 2026-07-29 | **Not** a catch-basin inventory. |
| MapWellesley hub (map-wellesleyma.hub.arcgis.com) | Reachable; catalog listing empty | — | — |

The town does **not** publish signs, signals, street-name signs, catch basins, manholes, streetlights, bollards or pavement markings as GIS layers.

## Statewide

| Source | What it holds | Count | Notes |
|---|---|---|---|
| [MassDOT Sign layer](https://gis.massdot.state.ma.us/arcgis/rest/services/Assets/SignsSignals/MapServer/1) (VERIFIED) | Sign points with MUTCDCode, MUTCDDescription, TravelDirection, SideofRoad, SignOrientation | 216,075 statewide; 619 within Wellesley (1,615 in a bbox around it) | **State highways only** (Rtes 9, 16, 135 etc. in Wellesley). Around Wellesley: Stop 124, Left Turn Prohibition 76, One Way 65, Speed Limit 56, Do Not Enter 36, … Best positioned-sign ground truth. |
| MassDOT Signals (same service, layer 0) (VERIFIED) | Signal locations on MassDOT roads | 1,626; Wellesley 7 | |
| [MassDOT Road Inventory 2025](https://geo-massdot.opendata.arcgis.com/datasets/MassDOT::road-inventory-2025) (VERIFIED, modified 2026-10-14) | `Oneway` (FT/TF), `Operation` (one-way / two-way), speed limit, truck exclusions | 504,907 segments | One-way by segment; **no turn restrictions**. |
| OpenStreetMap (LEAD) | Turn-restriction relations, stop nodes, signals, traffic_sign, hydrants, one-way ways | not obtained: every Overpass server was at capacity | Rerun the count query later. |
| Mapillary map features (VERIFIED docs, not called) | Mapillary's own detected traffic signs/points | — | Token required; bulk extraction restricted by terms. |

## Other towns

| Source | What it holds | Count | Notes |
|---|---|---|---|
| [Boston "Signs (Cartegraph)"](https://data.boston.gov/dataset/signs-cartegraph) (VERIFIED, PDDL, updated 2026-11-01) | Sign assets with code, facing and arrow direction, size, support, status, lat/lon, **photo URL** | 20,138 existing signs (33,485 rows incl. extra photos) | Mostly parking regulation. Uses Boston's own codes (MS-7, T-23, R-1…), not MUTCD, so decode with the data-dictionary PDF. Strong for detector training and localization tests. |
| [Newton Traffic Signs](https://gisweb.newtonma.gov/server/rest/services/Data/MapServer/2) (VERIFIED) | Stop 677, Yield 6, keyed to intersection | 683 | Stop/yield only, no facing. Signals in layer 3. |
| Cambridge / Boston / Springfield / Worcester signals (LEAD / VERIFIED earlier) | Signal locations | — | See `luna_signs.md`, `luna_statewide.md`. |
| Somerville TrafficAndParking, Worcester OpenData Transportation (LEAD) | Unknown | — | Hosts refused or did not resolve. |

No public **turn-restriction GIS layer** was found anywhere in Massachusetts. Wellesley's Traffic Regulations schedules are the closest equivalent.
