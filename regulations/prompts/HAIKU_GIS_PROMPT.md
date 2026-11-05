# GIS-data swarm: worker prompt (one per Haiku agent, fill in <WORKER>)

You are worker <WORKER> in a swarm that inventories every Massachusetts town's public GIS data. A live dashboard shows your progress (swarm.html#gis). Repository: `C:\Users\mmulq\MassGIS Projects\roadside`. Run commands with Bash from that folder, using this Python: `"/c/Users/mmulq/miniconda3/python.exe"` (below: PY). Prefix every command with `cd "/c/Users/mmulq/MassGIS Projects/roadside" && `.

Run every command in the foreground and wait for it (submit can take up to 3 minutes; use a 300000 ms timeout).
Do at most 15 towns, then stop, and do not call `next` again once you have finished 15. Watch for neighbouring towns with similar names too (Attleboro / North Attleborough). LOOP:

1. `PY gis_swarm.py next --worker <WORKER>`
   Prints `NEXT <slug> | <Town>, Massachusetts`, the town website, and what an ArcGIS catalog search already found. If it prints `DONE`, stop.
2. Find the town's GIS resources by reading its website:
   - `PY gis_swarm.py links <website>` prints the GIS-looking links on a page. Follow the most promising ones (GIS, Maps, GIS / Mapping, Engineering, DPW / Public Works, Assessor) by running `links` on them. At most 4 `links` calls per town.
   - If the website is "unknown", or `links` prints a WARNING that it redirected to a different site, use ONE WebSearch (`<Town> Massachusetts official town website GIS maps`) to find the official site, and add `--website <official url>` when you submit.
   - IMPORTANT: many Massachusetts town names also exist in other states (Berkley MI, Salem OR, Franklin TN, Washington ...). Only submit links that clearly belong to the Massachusetts town: reached from its official website, or with "MA"/"Massachusetts" in the address or title. Reject anything with another state in the URL (e.g. `berkleymi`, `-nh`, `ct.gov`).
   - Collect, by kind:
     `viewer`   online map viewer (AxisGIS, MapGeo, MapsOnline / PeopleGIS, MainStreetMaps, ArcGIS web app, Tighe & Bond, etc.)
     `opendata` open-data portal / hub with downloads
     `rest`     ArcGIS Server services directory (URL containing `/rest/services`)
     `layer`    a single FeatureServer / MapServer layer URL
     `download` a direct data file (.zip, .shp, .kml/.kmz, .geojson, .csv, .gdb)
     `document` a PDF map or inventory (e.g. a sign inventory or street list)
     `other`    anything else GIS-related
   - Anything about signs, stop signs, traffic, streets/roads, pavement or sidewalks matters most.
3. Submit, best links first (only URLs you actually saw in `links` output or search results; never guess or build URLs):
   `PY gis_swarm.py submit <slug> --worker <WORKER> --link "viewer|<url>|<short title>" --link "rest|<url>|<short title>" --note "<one sentence>"`
   If nothing was found: `PY gis_swarm.py submit <slug> --worker <WORKER> --note "<what you checked>"`
   The script verifies every link (ArcGIS directories are crawled and their layers counted) and prints `RESULT <slug>: found | partial | not_found`. Don't retry, don't edit files.

Rules: no logins, no web forms, no CAPTCHAs, don't download files yourself, never modify repository code. At most 1 WebSearch per town; if WebSearch stops working, carry on without it. Finish with one line: towns completed, and how many had sign layers.
