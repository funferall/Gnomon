# Protocol: structure a town's stop-sign list

For each town you are given, read `C:\Users\mmulq\MassGIS Projects\roadside\data\regulations\<slug>\stop_section.txt`. Each line is `<line number><TAB><text>`, extracted from the town's official traffic regulations. Use the Read tool with offset/limit for long files.

Write `C:\Users\mmulq\MassGIS Projects\roadside\data\regulations\<slug>\stop_rows_ai.json` with the Write tool, as valid JSON only:

```json
{"town": "<slug>",
 "rows": [
  {"line": 1234, "on_street": "Abbott Road", "at_streets": ["Forest Street"], "travel_directions": ["S"],
   "direction_text": "Southbound drivers on Abbott Road", "raw": "Abbott Road  Forest St.  Southbound drivers on Abbott Road (11/47)"}
 ],
 "notes": "one or two sentences about the format, and anything you skipped"}
```

## Rules
- **One row per stop sign location.** If a row says "North and southbound", use one row with `"travel_directions": ["N","S"]`.
- **on_street:** the street whose traffic must STOP, the one the sign faces drivers on. Names are often headed "Located on", "Street", "Stop street" or "Entering".
- **at_streets:** the street(s) it meets ("At", "At the intersection of", "Entering", "Through street"). If two are given ("Arnold Rd./Old Colony"), list both.
- **travel_directions:** the compass direction the stopping traffic travels, only if stated: Northbound / Northerly / "facing northbound traffic" becomes "N"; use N, NE, E, SE, S, SW, W, NW. If no direction is stated, use `[]`.
- **Keep street names as printed**, with abbreviations and any typos. Don't expand or fix them; the pipeline validates names against the state road database.
- **Only stop signs.** Skip yield signs, parking, signals, speed limits, one-way streets, turn rules and headers, unless a line is explicitly listed under a stop-sign heading. Multi-way stops ("4-way stop at X and Y") become one row per approaching street when the streets are listed; if not, one row with on_street X and at_streets [Y].
- **Rows wrapped over several lines:** join them; use the first line's number.
- **Never invent rows or streets.** If a section isn't really a stop-sign list, write `"rows": []` and explain in `notes`.
- **Don't use web search**, and don't edit any other files.

When finished, reply with one line per town: slug, number of rows written.
