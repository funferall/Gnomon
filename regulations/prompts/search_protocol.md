# Swarm protocol: find each town's traffic regulations

**Goal:** for each Massachusetts municipality you are assigned, find the town's **official document that lists stop sign locations** as a schedule: street, cross street and direction. Turn prohibitions and one-way streets are a bonus.

Typical titles:
- "Traffic Rules and Orders", "Traffic Regulations", "Traffic and Parking Regulations"
- "Rules and Regulations of the Select Board / Board of Selectmen / Traffic Commission / Traffic Committee"
- A general bylaw or city ordinance chapter with a stop-sign schedule (often on ecode360.com or library.municode.com)

Example of what a good one contains (Wellesley, p.54):
```
SCHEDULE IV - STOP SIGNS
LOCATED ON       AT                SO AS TO FACE
Abbott Road      Forest St.        Southbound drivers on Abbott Road (11/47)
```

## How to report (this drives a live dashboard)

Use the **Write** tool with these exact absolute paths, and write **valid JSON only**:

1. When you START a town, write the town file:
   `C:\Users\mmulq\MassGIS Projects\roadside\data\regulations\registry\towns\<slug>.json`
   ```json
   {"slug": "<slug>", "worker": "<agent-id>", "status": "searching"}
   ```
   and your heartbeat file `C:\Users\mmulq\MassGIS Projects\roadside\data\regulations\registry\workers\<agent-id>.json`:
   ```json
   {"current": "<slug>"}
   ```
2. When you FINISH a town, overwrite the town file:
   ```json
   {"slug": "<slug>", "worker": "<agent-id>", "status": "found",
    "document": {"url": "...", "title": "...", "format": "pdf_text", "last_updated": "January 2026",
                 "has_stop_signs": true, "has_turn_prohibitions": true, "has_one_way": true, "verified": true},
    "candidates": ["other promising URLs"], "notes": "one or two sentences"}
   ```
3. After your last town, write the heartbeat as `{"current": null, "state": "done"}`.

### Status values
- **found**: an official document you OPENED that contains a list of stop sign locations (street plus cross street). `verified: true`.
- **partial**: official traffic rules exist, but either there is no stop-sign location list in them, or you could not open or read it (scanned image, broken link, login), or the bylaw says the schedules are kept elsewhere.
- **not_found**: nothing official found within the search budget. Use `"document": null` and list any leads in `candidates`.
- **error**: your tools failed.

### document.format
`pdf_text` (selectable text), `pdf_scanned` (image only), `html`, `ecode360`, `municode`, `docx`, `other`.

## Rules
- Budget: about **6 searches/fetches per town**, then record what you have and move on. Speed matters; there are 349 towns.
- Official sources only: the town's own website, its document centre, or the code host it links to (ecode360, municode, generalcode, ArcGIS). Ignore news, blogs and other states with the same town name (there are many Washingtons, Salems and Franklins).
- Useful searches: `<Town> Massachusetts "traffic rules and orders"`, `<Town> MA traffic regulations stop signs`, `<Town> MA "stop signs" "so as to face"`, `site:ecode360.com <Town> Massachusetts traffic`, `<Town> MA select board traffic regulations pdf`.
- Do not download files to disk, log in, or submit forms. Reading a PDF through your fetch tool is fine.
- Never invent a URL. Only report URLs you actually saw.
