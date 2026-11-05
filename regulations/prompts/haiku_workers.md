# Orchestrator prompt for a fresh Claude Code session

Launch up to 15 background subagents with model **haiku** (general-purpose), named `haiku-01` … `haiku-15`. Give each one the WORKER PROMPT below with its own worker name filled in. Do not do the research yourself. When a subagent finishes, report its one-line summary; if towns remain and the web-search budget allows, launch a replacement with the next unused name.

## WORKER PROMPT (fill in <WORKER>)

You are worker <WORKER> in a swarm that finds Massachusetts towns' official traffic regulations. A live dashboard shows your progress. Repository: `C:\Users\mmulq\MassGIS Projects\roadside`. Run commands with Bash from that folder, using this Python: `"/c/Users/mmulq/miniconda3/python.exe"` (below: PY).

LOOP until `next` prints DONE:
1. `cd "/c/Users/mmulq/MassGIS Projects/roadside" && PY swarm.py next --worker <WORKER> --queue codex --from-end`
   This prints `NEXT <slug> | <Town>, Massachusetts (<County> County) | previously: ...`, sometimes with an already-known URL that LACKS the stop-sign list.
2. With WebSearch (and WebFetch if useful), find the town's official document that lists STOP SIGN locations by street and cross street. Typical titles: "Traffic Rules and Orders", "Traffic Regulations", "Traffic and Parking Regulations", or Select Board / Board of Selectmen / City Council / Traffic Commission rules with schedules. Many towns keep these separate from their general bylaws. Official town or city websites only (DocumentCenter, ArchiveCenter, showpublisheddocument links) or the official code host. Ignore other states and news. At most 4 searches per town. Never construct or guess URLs.
3. Submit, best URL first:
   `PY swarm.py submit <slug> <url1> [<url2> ...] --worker <WORKER> --note "<one sentence>"`
   If nothing usable was found: `PY swarm.py submit <slug> --worker <WORKER> --note "<what you searched>"`
   The command downloads and verifies the documents and prints `RESULT <slug>: found | partial | not_found`. Don't edit JSON by hand and don't retry a not_found.
4. **If WebSearch stops working** (budget or rate limit), do NOT submit the town. Instead run `PY swarm.py release <slug> --worker <WORKER>`, then stop and report that the search budget ran out.

Never modify repository code, log in, submit web forms, try to get past CAPTCHAs, or download files yourself. Finish with one line: how many towns you completed and how many were found.
