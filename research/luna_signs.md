# Massachusetts municipal traffic-control GIS inventory scan

Research scope: official municipal/state GIS portals or services linked from official pages. Checked 4 Nov 2026. A missing public layer here means not found in these public catalogs, not proof the municipality holds no internal data.

## Findings

### Wellesley (priority)
- Town site routes users to “Maps & Property Info”; town engineering procurement documents say GIS maps may be furnished to consultants, but the public-site search did not surface a sign, street-name sign, signal, bollard/barrier, or regulatory-control GIS layer/service or download. [Town maps entry](https://www.wellesleyma.gov/) · [Engineering RFP mentioning GIS maps](https://www.wellesleyma.gov/DocumentCenter/View/42930/RFP?bidId=)
- Conclusion: no publicly verified asset inventory found; evidence suggests map access exists, not that inventory data exists. No fields/count/update date/open-download/license could be verified.

### Boston
- The official City GIS REST MapServer exposes **Traffic Signals** (point layer ID 12), explicitly described “City of Boston traffic signals.” Direct metadata: https://gisportal.boston.gov/arcgis/rest/services/Infrastructure/OpenData/MapServer/12 ; query/download endpoint: https://gisportal.boston.gov/arcgis/rest/services/Infrastructure/OpenData/MapServer/12/query . Fields: `OBJECTID`, `Count_`, `Int_Number`, `Location`, `Dist`, geometry. Count not verified. Service supports JSON/GeoJSON/PBF queries; no attachment or copyright/license statement shown in metadata. [Official service directory](https://gisportal.boston.gov/arcgis/rest/services/Infrastructure/OpenData/MapServer) (also lists Street Lights ID 11, Boston Segments ID 8, MassDOT Road Inventory ID 14).
- This is a signal-location inventory, not signs or regulatory restrictions. The City service has no sign, street-name sign, bollard/access-barrier layer in the published layer list reviewed.

### Cambridge
- Official GIS Data page describes 200+ city layers and points to the GIS Data Dictionary, GitHub download site, and ArcGIS Online group; Cambridge Open Data portal says data are public-domain under ODC PDDL “whenever possible.” [GIS data catalog](https://www.cambridgema.gov/gis/gisdata) · [Open Data portal/terms statement](https://data.cambridgema.gov/)
- Search did not identify a directly relevant sign/sign-post, street-name sign, traffic signal, bollard/barrier, or restriction inventory. The catalog is a recommended next place to query by layer name; no candidate feature metadata, count, or update date verified in this scan.

### Dedham
- Town Engineering GIS page says GIS Division maintains geographic data/services and provides GIS maps/applications; no directly relevant sign/control inventory located in the official public material reviewed. [Official GIS page](https://www.dedhamma.gov/town-departments/engineering/gis)
- Town reports list a 2021 Town-wide traffic-signal evaluation of town-owned signals and flashing beacons, a useful validation/document lead, but not a downloadable point inventory. [Reports & plans](https://www.dedham-ma.gov/town-departments/engineering/reports-plans)
- A third-party-hosted ArcGIS service called `Dedham_Crash_Map_Basemap` surfaced in broad search; it is not official-source-linked and is not evidence of asset inventory, so excluded.

### Bedford
- Town GIS/Engineering pages provide mapping information but no relevant publicly downloadable GIS layer found in the search. [GIS & town maps](https://www.bedfordma.gov/386/GIS-Town-Maps) · [Engineering/GIS Division](https://bedfordma.gov/384/Engineering-GIS-Division)
- Bedford publishes its Traffic Rules & Regulations, including Schedule 5 stop/yield sign locations and regulation text. This is a regulatory schedule (strong validation of legally controlled stop/yield locations), not a georeferenced physical sign inventory. It may omit sign-side asset attributes and other sign types. [Traffic Rules & Regulations](https://www.bedfordma.gov/252/Bedford-Traffic-Rules-Regulations)

### Somerville
- Official City ArcGIS REST root lists `PublicGISViewer` and `TrafficAndParking` MapServer services. [Official REST services root](https://maps.somervillema.gov/arcgis/rest/services)
- `TrafficAndParking` service was not inspectable in this scan (REST request timed out), and no specific sign, street-name sign, signal, bollard/barrier, or regulatory-control layer metadata/fields/count/download were verified. Treat as viewer/service lead, not confirmed inventory. [TrafficAndParking service](https://maps.somervillema.gov/arcgis/rest/services/TrafficAndParking/MapServer)

## Statewide/reference data and semantics
- MassGIS Roads is statewide street centerline geometry with names/address ranges and roadway attributes, not a physical sign inventory. MassGIS says primary street names generally correspond to names posted on street signs; useful for matching sign records to road names. [MassGIS Roads metadata](https://www.mass.gov/info-details/massgis-data-massgis-roads)
- MassDOT Road Inventory/geoDOT is roadway-level inventory and may contain posted speed attributes; do not interpret those as surveyed locations of physical speed-limit signs. [MassDOT GIS](https://www.mass.gov/gis-for-transportation)
- MassDOT’s traffic-sign page describes its sign maintenance role on state highways and standard sign-book reference; it does not provide a local municipal asset layer. [MassDOT Traffic Signs](https://www.mass.gov/info-details/traffic-signs)
- Bedford's schedule is the only located primary legal/regulatory listing in this scan. For one-way/turn restrictions and speed limits, ordinances/traffic regulations are best treated as legal-control validation, while field sign inventories establish physical presence. These concepts can differ.

## Recommended acquisition/matching path
1. Start with Boston Traffic Signals layer as a reusable schema/example; query its `Location`, `Int_Number`, and `Dist` fields against signalized intersections and validate count/ownership with City traffic engineering records.
2. For Wellesley, request/locate the town GIS public viewer/service layer catalog through the official Maps & Property Info / Engineering GIS entry points; target point assets with sign type/MUTCD code, face/text, facing direction, support/post ID, status, owner, install/inspection date. No direct public download confirmed here.
3. For Dedham, pair the 2021 signal evaluation with any GIS/asset source; for Bedford use Schedule 5 stop/yield locations as a regulatory cross-check; Somerville inspect TrafficAndParking layer definitions directly.
4. Match sign street-name text to MassGIS Roads name fields with normalized aliases and spatial nearest-road/intersection checks, but preserve raw sign text and direction. Validate regulatory controls from town bylaws/traffic commission orders; don't infer signs from road speed or centerlines.
5. For street-name signs, distinguish municipal street-name blades from commercial/adopt-a-road/wayfinding signage. For barriers, distinguish permanent bollards/access controls from temporary construction devices.

## Evidence limits
No counts or survey dates are asserted except the Dedham evaluation year (report date/document reference). Service metadata's layer availability/last edit is not equivalent to a field survey date. No explicit license/terms were found for the Boston REST layer or Wellesley/Dedham/Bedford/Somerville municipal GIS sources in the pages reviewed; Cambridge states ODC PDDL whenever possible. Public REST query capability does not itself establish a license grant.
