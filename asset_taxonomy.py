"""Task scope: road-routing controls plus the explicitly requested infrastructure exceptions."""
VERSION='routing-v2'
LABELS=['stop sign','speed limit sign','one way sign','street name sign','traffic sign','fire hydrant','traffic light','bollard','storm drain','manhole cover']
REMOVED=['trash can','utility pole','street light','parking meter','mailbox','bench','bicycle rack','electrical cabinet','guardrail','bus stop sign']
# Regulatory bus-only/access signs remain discoverable as traffic signs; ordinary stops are excluded.
