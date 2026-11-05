#!/bin/bash
# Refresh Wellesley asset positions from the detections scanned so far, then re-match the regulations against them.
set -e
cd "/c/Users/mmulq/MassGIS Projects/roadside"
PY=/c/Users/mmulq/miniconda3/python.exe; TDA=/c/Users/mmulq/miniconda3/envs/TDA/python.exe
echo "== enrich $(date)";  $PY -u asset_localization.py enrich
echo "== depth $(date)";   $TDA -u depth_cue.py
echo "== run $(date)";     $PY -u asset_localization.py run
echo "== regulations $(date)"; $PY -u reg_harness.py run --town wellesley
echo "== crosscheck $(date)"; $PY -u reg_crosscheck.py
echo "== statewide $(date)"; $PY -u -c "import reg_aiparse as A; A.rebuild_statewide()"; $PY -u reg_statewide.py
echo "== done $(date)"
