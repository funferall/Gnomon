# Massachusetts road routability and asset inventory findings

Checked 2026-11-04. Scope: official state/municipal sources, with emphasis on western/central MA and Cape. “Not found” means no public downloadable inventory surfaced in this targeted search, not proof none exists internally.

## Statewide road layers are not asset inventories or routing networks

- [MassGIS Roads](https://www.mass.gov/info-details/massgis-data-massgis-roads) is statewide road centerlines derived from MassGIS NG911 / Master Address Database. The current Mass.gov page says weekly refresh, ongoing municipal/address/parcel/USPS/public-safety sourced maintenance. It is intended for geocoding and spatial analysis; MassGIS explicitly says it is not a routable network and needs connectivity validation plus routing attributes, restrictions, costs. Separate coincident lines can represent street names and numbered routes. Address ranges became independently generated/public in 2026; prior commercial restriction removed. Download links (File GDB / shapefile) are on the official page and MassGIS Data Hub. This is broad statewide street geometry, not sign/signal/barrier locations or verified access restrictions.
- [MassGIS-MassDOT Roads](https://www.mass.gov/info-details/massgis-data-massgis-massdot-roads) is the official state-maintained transportation/road-inventory centerline product, representing public and many private roadways and carrying MassDOT linear-reference/road inventory attributes. It is a hybrid, and must not be equated with an all-local-streets, field-verified asset inventory. It is older lineage (mostly 1990s aerial-interpreted linework, subsequently maintained/updated); page offers shapefile, file GDB and WFS. Road inventory attribute coverage does not establish traffic-control objects or turn restrictions.
- MassDOT [GIS for Transportation / GeoDOT](https://www.mass.gov/gis-for-transportation) offers MassDOT datasets and road inventory updates/requests. MassDOT's public [SignsSignals MapServer](https://gisstg.massdot.state.ma.us/arcgis/rest/services/Assets/SignsSignals/MapServer) presently exposes only layer `Signals` (ID 0); layer details at https://gisstg.massdot.state.ma.us/arcgis/rest/services/Assets/SignsSignals/MapServer/0. Official REST metadata describes 1,573 point locations on MassDOT-owned roadways; points represent a location, may aggregate multiple signals, and types include intersection, pedestrian, drawbridge. Fields include LOCATION, PARENT, DESCRIPTION, SIGNALID, GISID (among others). Extent is statewide. This is explicitly state-road-only, not municipal coverage. REST service supports JSON/geoJSON queries; can export with `.../0/query?where=1%3D1&outFields=*&f=geojson` (request counts via `returnCountOnly=true`). Metadata queryable; count 1,573 is service description, not a separately recomputed live query in this research.
- MassDOT asset management literature says signs, signals and drainage structures are among managed assets, but public evidence located here does not establish a public statewide downloadable street-sign, hydrant, catchbasin, manhole, barrier, or turn-restriction dataset. MassDOT internal/work-order systems and GeoDOT do not imply public availability.

## Municipal evidence / exports

### Springfield

- Official [Springfield GIS REST service](https://maps.springfield-ma.gov/arcgis/rest/services/OMSLive/oms_live_traffic_signals/MapServer) is a live Cartegraph traffic-signal MapServer, with layer `springfield.GIS.DPW_Signal_Polygons` (ID 0), query formats JSON/geoJSON. Layer query endpoint: https://maps.springfield-ma.gov/arcgis/rest/services/OMSLive/oms_live_traffic_signals/MapServer/0/query?where=1%3D1&outFields=*&f=geojson . It is signal polygons, not individual signal-head points. Service comments dated 2023-07-21. Extent aligns Springfield; no fields/count verified here. This is a ready-to-query operational municipal signal export, but publication/staleness semantics beyond the Cartegraph “Live” title are undocumented.
- Official [sign maintenance page](https://www.springfield-ma.gov/dpw/signs) states city is currently inventorying city-owned signs and estimates upwards of 20,000. This is evidence of active inventory effort, not a public sign dataset; likely incomplete while in progress.

### Worcester

- Official [GIS page](https://www.worcesterma.gov/innovation-technology/gis) says GIS downloads are available from Informing Worcester open-data site at no cost; data not published there may require formal data request (page lists fee-bearing process).
- City [traffic signal page](https://www.worcesterma.gov/mobility/projects-engineering/traffic-signals) says inventory system developed in 2023 for city-owned signals; reports 175 signals, 34 MassDOT-owned signals within city, and 110 RRFBs / other warning and school beacons. A 2025 pavement management report says inventory has been continually updated by staff and at that time counted 176 signals, 71 RRFBs, 15 flashing beacons, 4 school-zone flashers and 4 speed-feedback boards. Counts vary by date/scope; treat as operational evidence, not downloadable all-asset data. Consultant describes a GIS dashboard with equipment, condition, operability, timing, geometry and photos, but no public export URL was located. City's inventory is municipal road ownership; MassDOT-owned signals are a separate completeness gap.

### Amherst

- Official [GIS data page](https://www.amherstma.gov/1432/Get-Amherst-GIS-Data) provides selected data layers and a data request route. It explicitly calls the data public domain, as-is, without accuracy/completeness warranty. Targeted search found no public traffic-control or street asset dataset; request-only/enterprise data may exist.

### Northampton

- Official [Maps & GIS page](https://www.northamptonma.gov/746/Maps-GIS) says DPW GIS records location of infrastructure/assets above and below ground, linked to maintenance data. Engineering plans, utility maps, or enterprise GIS data require request to DPW. A published [traffic signal map PDF](https://www.northamptonma.gov/DocumentCenter/View/846/Signals_Map) exists, but is a static map, not a feature/download export. Signal inventory coverage/updates and licensing not stated.

### Pittsfield

- City public ArcGIS REST catalog at https://services3.arcgis.com/FvqmbdgeOdN6wKrI/ArcGIS/rest/services surfaced street lights, outfalls, road-work, and `Parking_Traffic_Orders`; no signs/signals/hydrants/manholes inventory identified in this search. Parking/traffic orders might encode some legal restrictions but are not a complete sign-derived turn/access restriction layer. Official [street maintenance page](https://www.pittsfieldma.gov/593/Street-Maintenance) says Traffic Division maintains signals, beacons, flashers and signs; Highway Division maintains ~210 miles accepted and unaccepted roads, drainage and catch basins. No public downloadable export confirmed. Data licensing unclear.

### Barnstable / Cape

- Official [Barnstable GIS page](https://www.barnstable.gov/Departments/GIS/) describes long-running GIS and public map access, including a public/private road map, but no direct public asset-download catalog was located. An official town map PDF from the GIS unit (2018) depicts point layers for traffic signals, signs, manholes, catchbasins, and bollards, demonstrating that these asset classes are mapped. Its map legend is evidence of existence, not a current, complete, downloadable inventory; no update cadence or license found.
- Town procurement addendum states its traffic-signal inventory is in an MS Access-based ESRI GIS, and a consultant completed assessment at 24 signalized intersections. Signals are town-maintained; this is not a public data feed. Cape Cod Commission traffic counts viewer is not an asset inventory.

## Routability implications

- No located statewide official dataset encodes all turn bans, one-way travel, private/restricted access, seasonal/time-window restrictions, or physical blockage/barrier status for all streets.
- Road centerline directional or classification fields (where present) should not be assumed current/legal restriction truth. Traffic-sign point inventories may help derive restrictions only if sign type, orientation, effective dates/time conditions and side-of-road semantics are available; none of the inspected western/central public sources provided such a ready statewide export.
- Municipal coverage is highly uneven: Springfield has a queryable signal service; Worcester has a maintained but apparently not openly exported signal system; Northampton/Barnstable publish maps and describe GIS inventories; Amherst points to selected downloads/request; Pittsfield operationally maintains assets but no matching public feature service surfaced.
- Hydrant inventories are fire/water-service assets and rarely establish road passability; catchbasins/manholes are useful ancillary street features but not routability controls. Barnstable official map confirms these classes are mapped locally; no statewide or broad municipal public export established here.

## Licensing and reproducibility notes

MassGIS Roads is public-downloadable now (former address-range commercial lock explicitly removed), and Amherst expressly asserts public-domain data with disclaimers. Springfield REST is openly queryable; its service metadata has no explicit license statement. The other municipal signal/asset references do not state reuse terms. Before redistributing municipal extracts, inspect each portal's terms/metadata. No people were contacted and no credentials used.
