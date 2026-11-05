"""Estimate where detected roadside objects physically are, from Mapillary structure-from-motion geometry.

Camera GPS is not an asset location. For each detection this module builds a calibrated world ray from
Mapillary's SfM camera rotation, then measures range three independent ways:

  sfm     metric depth of Mapillary's own triangulated SfM points that fall inside the box
  ground  intersection of the box's ground-contact ray with a road plane fitted to the SfM points
          (camera height above the road is measured per image, not assumed)
  size    angular height of the box against a standard physical height for the class (MUTCD panels etc.)

The cues are fused in log-range with outlier rejection, so a detection becomes a point with a covariance.
Detections of the same class are then associated across frames and passes and solved jointly
(bearings + ranges, robust Gauss-Newton). A `calibrate` pass re-triangulates wide-baseline multi-view
objects from bearings alone, which gives pseudo-truth that is independent of every range cue. Per-class cue
bias and spread are measured against it, so no ground truth is needed to tune a new town.
`evaluate` scores hydrants against Wellesley's published hydrant layer, which is never used for fitting.

Provider coordinates and human placements are never modified. Outputs live in their own tables:
sfm_pose, observation_geometry, asset_estimates, asset_estimate_evidence.
States: provisional_single_view | multi_view_estimate. Nothing here is `human_placed` or `field_verified`.
"""
import argparse, concurrent.futures as cf, hashlib, json, math, sqlite3, struct, datetime as dt
from collections import defaultdict
from pathlib import Path
import numpy as np, requests
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation as Rot
from pyproj import Transformer
from wellesley_pipeline import ROOT, OUT, graph, now
from sfm_geometry import FACES, face_to_cam, cam_to_face, flat_to_cam, cam_to_flat

VERSION = 'sfm-fusion-v1'
TO = Transformer.from_crs(4326, 26986, always_xy=True); BACK = Transformer.from_crs(26986, 4326, always_xy=True)
MESH_DIR = OUT / 'sfm' / 'mesh'
CALIBRATION = OUT / 'localization-calibration.json'
POSE_FIELDS = 'id,computed_geometry,computed_altitude,computed_rotation,computed_compass_angle,atomic_scale,camera_type,camera_parameters,sequence,merge_cc,mesh,captured_at'
# Physical heights (m) of what the detector boxes, with relative spread. MUTCD conventional-road sizes;
# street-name blades vary 6-8 in, one-way may be R6-1 (12 in) or R6-2 (24 in), "traffic sign" is any panel.
SIZE = {'stop sign': (0.76, .12), 'speed limit sign': (0.76, .12), 'one way sign': (0.42, .45), 'street name sign': (0.19, .25),
        'traffic sign': (0.70, .40), 'fire hydrant': (0.78, .15), 'traffic light': (1.05, .20), 'bollard': (0.95, .20)}
GROUND_CONTACT = {'fire hydrant', 'bollard'}   # bottom of box touches the ground
ON_GROUND = {'manhole cover', 'storm drain'}    # whole object lies in the road plane
DEFAULT_BEARING_SIGMA_DEG = 0.8
# Absolute floor (m, per axis) for SfM georegistration + reference-layer error. Measured, not assumed: median
# hydrant error vs the town layer is 2.1 m = 1.18 sigma; 2-fold spatial cross-validation of this one scalar gave
# 87% / 95% coverage of the 95% ellipse. It does not shrink with more drives: Mapillary merges overlapping drives
# into one reconstruction (merge_cc), so their georegistration errors are shared, not independent.
CAMERA_FLOOR_M = 1.8


def setup(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS sfm_pose(provider TEXT,image_id TEXT,status TEXT,payload TEXT,mesh_file TEXT,ground TEXT,error TEXT,fetched_at TEXT,PRIMARY KEY(provider,image_id));
    CREATE TABLE IF NOT EXISTS observation_geometry(observation_id TEXT PRIMARY KEY,provider TEXT,image_id TEXT,label TEXT,state TEXT,camera_x REAL,camera_y REAL,camera_z REAL,azimuth_deg REAL,elevation_deg REAL,range_m REAL,range_sigma_log REAL,x REAL,y REAL,cues TEXT,flags TEXT,version TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS asset_estimates(id TEXT PRIMARY KEY,class TEXT,state TEXT,x REAL,y REAL,lon REAL,lat REAL,uncertainty95_m REAL,ellipse TEXT,n_observations INTEGER,n_images INTEGER,n_sequences INTEGER,max_ray_angle_deg REAL,reduced_chi2 REAL,flags TEXT,version TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS asset_estimate_evidence(asset_estimate_id TEXT,observation_id TEXT,PRIMARY KEY(asset_estimate_id,observation_id));''')
    c.commit()


# ---------------------------------------------------------------- posed cameras
class Camera:
    """One posed image: world (EPSG:26986 x,y + altitude z) centre, rotation, SfM points and road plane."""
    def __init__(self, provider, image_id, pose, mesh_file, ground, shift=(0, 0)):
        self.provider, self.image_id = provider, image_id
        self.kind = pose.get('camera_type') or 'spherical'; self.params = pose.get('camera_parameters')
        lon, lat = pose['computed_geometry']['coordinates'][:2]
        x, y = TO.transform(lon, lat); self.C = np.array([x + shift[0], y + shift[1], pose.get('computed_altitude') or 0.0])
        # Grid convergence: rotate true-north ENU into EPSG:26986 grid axes (~0.1 deg in Wellesley, done exactly).
        xn, yn = TO.transform(lon, lat + 1e-4); g = math.atan2(xn - x, yn - y)
        G = np.array([[math.cos(g), math.sin(g), 0], [-math.sin(g), math.cos(g), 0], [0, 0, 1]])
        self.R = Rot.from_rotvec(pose['computed_rotation']).as_matrix()   # world(ENU)->camera
        self.W = G @ self.R.T                                             # camera bearing -> grid world
        self.sequence = pose.get('sequence'); self.points = None
        if mesh_file and Path(ROOT / mesh_file).exists(): self.points = np.load(ROOT / mesh_file)  # camera frame, metres
        self.ground = ground

    def bearings(self, u, v, box):
        if box.get('view', 'flat') == 'flat': return flat_to_cam(u, v, box['width'], box['height'], self.params, self.kind)
        return face_to_cam(u, v, box['width'], box['view'])

    def project(self, b, box):
        if box.get('view', 'flat') == 'flat': return cam_to_flat(b, box['width'], box['height'], self.params, self.kind)
        return cam_to_face(b, box['width'], box['view'])


# ---------------------------------------------------------------- enrichment: SfM pose + per-image mesh
def decode_mesh(blob, scale):
    """Mapillary mesh protobuf: field 1 floats (xyz, camera frame, atomic-reconstruction units), field 2 faces.
    Verified against the sfm_cluster point cloud: world = C + R^T (v / atomic_scale), 1 mm median residual."""
    i, verts = 0, []
    def varint(i):
        s = r = 0
        while True:
            x = blob[i]; i += 1; r |= (x & 0x7f) << s; s += 7
            if x < 0x80: return r, i
    while i < len(blob):
        key, i = varint(i); field, wire = key >> 3, key & 7
        if wire == 5: verts.append(struct.unpack_from('<f', blob, i)[0]); i += 4
        elif wire == 0: _, i = varint(i)
        elif wire == 2:
            n, i = varint(i)
            if field == 1: verts += struct.unpack_from('<%df' % (n // 4), blob, i)
            i += n
        elif wire == 1: i += 8
        else: raise ValueError('unexpected protobuf wire type')
    v = np.asarray(verts, np.float32).reshape(-1, 3) / float(scale or 1)
    return v[np.linalg.norm(v, axis=1) > 1.0]   # drops the 8-vertex placeholder cube at the origin


def fit_ground(points, R):
    """RANSAC plane z = a*e + b*n + c through SfM points below the camera (ENU relative to camera)."""
    if points is None or len(points) < 12: return None
    P = points @ R  # camera frame -> ENU offsets from camera (R is world->camera, so v @ R == R^T v)
    hd = np.hypot(P[:, 0], P[:, 1]); P = P[(hd > 2) & (hd < 25) & (P[:, 2] < -0.8) & (P[:, 2] > -4.5)]
    if len(P) < 10: return None
    rng = np.random.default_rng(0); best = None
    A = np.c_[P[:, 0], P[:, 1], np.ones(len(P))]
    for _ in range(200):
        s = P[rng.choice(len(P), 3, replace=False)]
        try: coef = np.linalg.solve(np.c_[s[:, 0], s[:, 1], np.ones(3)], s[:, 2])
        except np.linalg.LinAlgError: continue
        if math.hypot(coef[0], coef[1]) > .15: continue
        inl = np.abs(A @ coef - P[:, 2]) < .12
        if best is None or inl.sum() > best.sum(): best = inl
    if best is None or best.sum() < 8: return None
    coef, *_ = np.linalg.lstsq(A[best], P[best, 2], rcond=None); res = A[best] @ coef - P[best, 2]
    return {'a': float(coef[0]), 'b': float(coef[1]), 'height_m': float(-coef[2]), 'inliers': int(best.sum()), 'rms_m': float(np.sqrt(np.mean(res ** 2)))}


def enrich(c, limit=0, workers=6):
    setup(c); MESH_DIR.mkdir(parents=True, exist_ok=True)
    rows = c.execute('''select distinct o.provider,o.image_id from observations o left join sfm_pose p on p.provider=o.provider and p.image_id=o.image_id
                        where o.provider='mapillary' and (p.status is null or p.status='error')''').fetchall()
    if limit: rows = rows[:limit]
    print('SfM enrichment for', len(rows), 'images', flush=True)

    def work(row):
        provider, i = row
        try:
            pose = graph(i, {'fields': POSE_FIELDS})
            if not (pose.get('computed_rotation') and pose.get('computed_geometry')):
                return provider, i, 'no_sfm', pose, None, None, None
            mesh_file, ground = None, None
            if pose.get('mesh', {}).get('url'):
                r = requests.get(pose['mesh']['url'], timeout=60)
                if r.ok:
                    pts = decode_mesh(r.content, pose.get('atomic_scale'))
                    f = MESH_DIR / (i + '.npy'); np.save(f, pts); mesh_file = str(f.relative_to(ROOT)).replace('\\', '/')
                    ground = fit_ground(pts, Rot.from_rotvec(pose['computed_rotation']).as_matrix())
            pose.pop('mesh', None)   # signed CDN URL: never persist it
            return provider, i, 'ok', pose, mesh_file, ground, None
        except Exception as e:  # never serialise request exceptions; URLs can carry credentials
            return provider, i, 'error', {}, None, None, type(e).__name__

    done = 0
    with cf.ThreadPoolExecutor(workers) as pool:
        for provider, i, status, pose, mesh_file, ground, err in pool.map(work, rows):
            # One short transaction per row: the GPU scan worker shares this database.
            with c: c.execute('insert or replace into sfm_pose values(?,?,?,?,?,?,?,?)', (provider, i, status, json.dumps(pose), mesh_file, json.dumps(ground), err, now()))
            done += 1
            if done % 100 == 0: print('enriched', done, '/', len(rows), flush=True)
    c.commit(); print(dict(c.execute('select status,count(*) from sfm_pose group by status')), flush=True)


# ---------------------------------------------------------------- per-observation geometry and range cues
def load_calibration():
    try: return json.loads(CALIBRATION.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}


def camera_shifts(c):
    """Approved local sequence corrections apply inside their capture interval; proposals only flag."""
    out = {}
    try: rows = c.execute('select sequence,dx_m,dy_m,status,statistics from sequence_alignments').fetchall()
    except sqlite3.OperationalError: return out
    for seq, dx, dy, status, stats in rows:
        s = json.loads(stats or '{}'); out[seq] = (status, dx, dy, s.get('capture_start'), s.get('capture_end'))
    return out


def foreground_range(r):
    """Nearest coherent depth group among SfM points inside a box (background shows through around objects)."""
    r = np.sort(r[r > 1.5])
    if not len(r): return None
    groups, start = [], 0
    for k in range(1, len(r) + 1):
        if k == len(r) or r[k] / r[k - 1] > 1.12: groups.append(r[start:k]); start = k
    g = next((g for g in groups if len(g) >= 2), groups[0])
    lr = np.log(g); mad = 1.4826 * np.median(np.abs(lr - np.median(lr))) if len(g) > 2 else .08
    sigma = .18 if len(g) == 1 else max(.04, mad / math.sqrt(len(g)) + .03)
    return float(np.median(g)), float(sigma), int(len(g))


def observation_geometry(cam, label, box, cal, mono=None):
    x0, y0, x1, y1 = box['xyxy']; size_w, size_h = box['width'], box['height']; uc = (x0 + x1) / 2
    flags = []; edge = 2.0
    clipped = x0 < edge or y0 < edge or x1 > size_w - edge or y1 > size_h - edge
    if clipped: flags.append('box_touches_view_edge')
    rays = cam.bearings(np.array([uc, uc, uc]), np.array([(y0 + y1) / 2, y1, y0]), box)   # centre, bottom, top
    d = rays @ cam.W.T   # world (grid) directions
    centre = d[0]
    az = math.degrees(math.atan2(centre[0], centre[1])) % 360; el = math.degrees(math.asin(np.clip(centre[2], -1, 1)))
    horiz = math.hypot(centre[0], centre[1]); cues = {}

    # cue 1: SfM points inside the box
    if cam.points is not None and len(cam.points):
        b = cam.points / np.linalg.norm(cam.points, axis=1, keepdims=True); u, v, ok = cam.project(b, box)
        m = ok & (u >= x0 - 1) & (u <= x1 + 1) & (v >= y0 - 1) & (v <= y1 + 1)
        if m.any():
            fr = foreground_range(np.linalg.norm(cam.points[m], axis=1))
            if fr: cues['sfm'] = {'range_m': fr[0] * horiz, 'sigma_log': fr[1], 'points': fr[2]}

    # cue 1b: dense monocular depth anchored per face to the same SfM points (depth_cue.py). Gap-filler only:
    # where the box already holds SfM points the two would share evidence, so it is not double-counted.
    if mono and mono[0] and 'sfm' not in cues:
        cues['mono'] = {'range_m': mono[0] * horiz, 'sigma_log': math.hypot(.12, mono[1] or .2), 'fit_points': mono[2]}

    # cue 2: ground-contact ray against the per-image road plane
    g = cam.ground or cal.get('ground_fallback')
    if g and (label in GROUND_CONTACT or label in ON_GROUND) and not (label in GROUND_CONTACT and y1 > size_h - edge):
        ray = d[0] if label in ON_GROUND else d[1]; ray_h = math.hypot(ray[0], ray[1])
        denom = ray[2] - g['a'] * ray[0] - g['b'] * ray[1]
        if denom < -0.02:
            lam = -g['height_m'] / denom; rng = lam * ray_h
            dep = math.atan2(-ray[2], ray_h); px = math.radians(90) / size_w if box.get('view', 'flat') != 'flat' else 1 / ((cam.params or [.85])[0] * max(size_w, size_h))
            s_th = math.hypot(1.5 * px, math.radians(.35)); s_h = .12 if cam.ground else .45
            sig = math.hypot(s_h / g['height_m'], s_th / max(1e-3, math.sin(dep) * math.cos(dep)))
            if 1 < rng < 80 and sig < .8: cues['ground'] = {'range_m': rng, 'sigma_log': sig, 'camera_height_m': g['height_m']}

    # cue 3: angular size vs standard physical height
    if label in SIZE and not clipped and (y1 - y0) >= 6:
        H, rel = SIZE[label]; alpha = math.acos(float(np.clip(rays[1] @ rays[2], -1, 1)))
        if alpha > 1e-4:
            rng = H / (2 * math.tan(alpha / 2)) * horiz
            cues['size'] = {'range_m': rng, 'sigma_log': math.hypot(rel, 2.0 / (y1 - y0)), 'box_height_px': y1 - y0}

    # apply self-calibration (per class, per cue): remove log bias, replace spread with the measured one
    cc = cal.get('cues', {}).get(label, {})
    for k, q in cues.items():
        q['raw_range_m'] = q['range_m']
        if k in cc and cc[k].get('n', 0) >= 8:
            q['range_m'] = q['range_m'] * math.exp(-cc[k]['bias_log']); q['sigma_log'] = math.hypot(q['sigma_log'] * .5, cc[k]['sigma_log']); q['calibrated'] = True
    used = {k: q for k, q in cues.items() if 1 < q['range_m'] < 120}
    # robust fusion in log-range: drop the worst cue while the set is inconsistent
    while len(used) > 1:
        w = {k: 1 / q['sigma_log'] ** 2 for k, q in used.items()}; mu = sum(w[k] * math.log(q['range_m']) for k, q in used.items()) / sum(w.values())
        z = {k: abs(math.log(q['range_m']) - mu) / q['sigma_log'] for k, q in used.items()}; worst = max(z, key=z.get)
        if z[worst] < 3: break
        used[worst]['rejected'] = True; flags.append('cue_conflict_' + worst); used.pop(worst)
    if not used: return az, el, None, None, cues, flags + ['no_range_cue']
    w = {k: 1 / q['sigma_log'] ** 2 for k, q in used.items()}
    mu = sum(w[k] * math.log(q['range_m']) for k, q in used.items()) / sum(w.values())
    return az, el, math.exp(mu), math.sqrt(1 / sum(w.values())), cues, flags


def localize(c, cal=None):
    setup(c); cal = load_calibration() if cal is None else cal; shifts = camera_shifts(c)
    poses = {(p, i): (json.loads(pl), mf, json.loads(g or 'null')) for p, i, pl, mf, g in c.execute("select provider,image_id,payload,mesh_file,ground from sfm_pose where status='ok'")}
    hs = [g['height_m'] for _, _, g in poses.values() if g]; cal = dict(cal)
    if hs: cal['ground_fallback'] = {'a': 0, 'b': 0, 'height_m': float(np.median(hs))}
    try: mono = {r[0]: r[1:] for r in c.execute('select observation_id,range_m,fit_mad_log,fit_points from observation_depth')}
    except sqlite3.OperationalError: mono = {}
    rows = c.execute('select id,provider,image_id,label,box from observations').fetchall(); out = []; cams = {}; skipped = defaultdict(int)
    for oid, provider, image_id, label, box in rows:
        key = (provider, image_id)
        if key not in poses: skipped['no_sfm_pose'] += 1; continue
        if key not in cams:
            pose, mf, g = poses[key]; flags = []; sh = (0, 0); a = shifts.get(pose.get('sequence'))
            if a:
                status, dx, dy, t0, t1 = a; cap = dt.datetime.fromtimestamp(pose['captured_at'] / 1000, dt.timezone.utc) if pose.get('captured_at') else None
                inside = bool(cap and t0 and t1 and dt.datetime.fromisoformat(t0) <= cap <= dt.datetime.fromisoformat(t1))
                if inside and status == 'approved': sh = (dx, dy); flags.append('approved_camera_shift_applied')
                elif inside: flags.append('camera_shift_proposed_not_applied')
            cams[key] = (Camera(provider, image_id, pose, mf, g, sh), flags)
        cam, camflags = cams[key]; b = json.loads(box)
        az, el, rng, sig, cues, flags = observation_geometry(cam, label, b, cal, mono.get(oid))
        if rng:
            x = cam.C[0] + rng * math.sin(math.radians(az)); y = cam.C[1] + rng * math.cos(math.radians(az)); state = 'provisional_single_view'
        else: x = y = None; state = 'ray_only'
        out.append((oid, provider, image_id, label, state, *map(float, cam.C), az, el, rng, sig, x, y, json.dumps(cues), json.dumps(camflags + flags), VERSION, now()))
    with c:
        c.execute('delete from observation_geometry'); c.executemany('insert into observation_geometry values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', out)
    st = defaultdict(int)
    for r in out: st[r[4]] += 1
    print('observation geometry', dict(st), 'skipped', dict(skipped), flush=True)


# ---------------------------------------------------------------- multi-view association and joint solve
def solve(obs, sb, use_range=True, x0=None):
    """Robust Gauss-Newton for one horizontal point. obs: list of (cx, cy, az_rad, range, sigma_log)."""
    C = np.array([[o[0], o[1]] for o in obs]); az = np.array([o[2] for o in obs])
    rg = np.array([o[3] or 0 for o in obs]); sl = np.array([o[4] or 1 for o in obs]); hasr = (rg > 0) & use_range
    if x0 is None:
        p = C + (np.where(rg > 0, rg, 10))[:, None] * np.c_[np.sin(az), np.cos(az)]; X = p.mean(0)
    else: X = np.array(x0, float)
    def resid(X):
        d = X - C; dist = np.hypot(d[:, 0], d[:, 1]); a = np.arctan2(d[:, 0], d[:, 1])
        rb = ((a - az + np.pi) % (2 * np.pi) - np.pi) / sb
        rr = np.where(hasr, (np.log(np.maximum(dist, .1)) - np.log(np.where(hasr, rg, 1))) / sl, 0)
        return np.r_[rb, rr[hasr]], d, dist
    for _ in range(25):
        r, d, dist = resid(X); J = np.zeros((len(r), 2)); n = len(obs)
        J[:n, 0] = d[:, 1] / dist ** 2 / sb; J[:n, 1] = -d[:, 0] / dist ** 2 / sb
        if hasr.any(): J[n:, 0] = d[hasr, 0] / dist[hasr] ** 2 / sl[hasr]; J[n:, 1] = d[hasr, 1] / dist[hasr] ** 2 / sl[hasr]
        w = np.where(np.abs(r) < 2.5, 1, 2.5 / np.abs(r))   # Huber
        H = J.T @ (J * w[:, None]); step = np.linalg.lstsq(H + 1e-9 * np.eye(2), -J.T @ (w * r), rcond=None)[0]
        X = X + step
        if np.hypot(*step) < 1e-4: break
    r, d, dist = resid(X); m = len(r)
    ahead = bool(np.all((d[:, 0] * np.sin(az) + d[:, 1] * np.cos(az)) > 0))
    try: cov = np.linalg.inv(J.T @ J)
    except np.linalg.LinAlgError: cov = np.eye(2) * 1e6
    chi2 = float(r @ r); return X, cov, chi2, m, r, ahead


def associate(c, cal=None):
    setup(c); cal = load_calibration() if cal is None else cal
    rows = c.execute("select observation_id,provider,image_id,label,camera_x,camera_y,azimuth_deg,range_m,range_sigma_log,x,y,flags from observation_geometry where state='provisional_single_view'").fetchall()
    seq = {(p, i): json.loads(pl).get('sequence') for p, i, pl in c.execute("select provider,image_id,payload from sfm_pose where status='ok'")}
    by_class = defaultdict(list)
    for r in rows: by_class[r[3]].append(r)
    assets, evidence = [], []
    for label, items in by_class.items():
        sb = math.radians(cal.get('bearing_sigma_deg', {}).get(label, cal.get('bearing_sigma_deg', {}).get('_all', DEFAULT_BEARING_SIGMA_DEG)))
        o = [(r[4], r[5], math.radians(r[6]), r[7], r[8]) for r in items]; xy = np.array([[r[9], r[10]] for r in items])
        tree = cKDTree(xy); edges = []
        pairs = tree.query_pairs(25.0, output_type='ndarray')
        if len(pairs):
            # cheap gate before any solve: single-view points must agree within combined along-ray spread
            s = np.array([max(.5, (r[7] or 0) * (r[8] or 1)) for r in items]); i_, j_ = pairs[:, 0], pairs[:, 1]
            keep = np.hypot(*(xy[i_] - xy[j_]).T) < 3 * np.hypot(s[i_], s[j_]) + 1.5
            img = np.array([r[2] for r in items], dtype=object); keep &= img[i_] != img[j_]; pairs = pairs[keep]
        for i, j in pairs:
            X, cov, chi2, m, res, ahead = solve([o[i], o[j]], sb, x0=(xy[i] + xy[j]) / 2)
            if ahead and np.max(np.abs(res)) < 3: edges.append((chi2, i, j))
        edges.sort(); parent = list(range(len(items))); members = {k: [k] for k in range(len(items))}
        def find(k):
            while parent[k] != k: parent[k] = parent[parent[k]]; k = parent[k]
            return k
        for _, i, j in edges:
            a, b = find(i), find(j)
            if a == b: continue
            ma, mb = members[a], members[b]
            if {items[k][2] for k in ma} & {items[k][2] for k in mb}: continue   # one image cannot see one object twice
            group = ma + mb; X, cov, chi2, m, res, ahead = solve([o[k] for k in group], sb, x0=xy[group].mean(0))
            if not ahead or np.max(np.abs(res)) > 3.5: continue
            parent[b] = a; members[a] = group; del members[b]
        for root, group in members.items():
            X, cov, chi2, m, res, ahead = solve([o[k] for k in group], sb, x0=xy[group].mean(0)); dof = max(1, m - 2); red = chi2 / dof
            cov = cov * max(1.0, red); seqs = {seq.get((items[k][1], items[k][2])) for k in group}
            rel95 = 2.4477 * math.sqrt(max(np.linalg.eigvalsh(cov)[1], 0))   # precision relative to the SfM frame
            cov = cov + np.eye(2) * CAMERA_FLOOR_M ** 2
            vals, vecs = np.linalg.eigh(cov); a95 = 2.4477 * math.sqrt(max(vals[1], 0)); b95 = 2.4477 * math.sqrt(max(vals[0], 0))
            azs = [o[k][2] for k in group]; spread = max((abs((p - q + math.pi) % (2 * math.pi) - math.pi) for p in azs for q in azs), default=0)
            flags = sorted({f for k in group for f in json.loads(items[k][11]) if 'camera_shift' in f})
            if len(group) == 1: flags.append('single_view_range_dominates')
            elif math.degrees(spread) < 4: flags.append('narrow_baseline_range_dominates')
            state = 'multi_view_estimate' if len(group) > 1 and math.degrees(spread) >= 4 else 'provisional_single_view'
            lon, lat = BACK.transform(*X); aid = 'est-' + hashlib.sha1('|'.join(sorted(items[k][0] for k in group)).encode()).hexdigest()[:14]
            assets.append((aid, label, state, float(X[0]), float(X[1]), lon, lat, a95, json.dumps({'semi_major95_m': a95, 'semi_minor95_m': b95, 'relative95_m': rel95, 'major_axis_azimuth_deg': math.degrees(math.atan2(vecs[0, 1], vecs[1, 1])) % 180}),
                           len(group), len({items[k][2] for k in group}), len(seqs), math.degrees(spread), red, json.dumps(flags), VERSION, now()))
            evidence += [(aid, items[k][0]) for k in group]
    with c:
        c.execute('delete from asset_estimate_evidence'); c.execute('delete from asset_estimates')
        c.executemany('insert into asset_estimates values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', assets); c.executemany('insert into asset_estimate_evidence values(?,?)', evidence)
    st = defaultdict(int)
    for a in assets: st[a[2]] += 1
    print('asset estimates', len(assets), dict(st), 'from', len(rows), 'observations', flush=True)


# ---------------------------------------------------------------- self-calibration (no ground truth used)
def calibrate(c):
    """Pseudo-truth = wide-baseline multi-view objects re-solved from bearings only, so it is independent of
    every range cue. Measures per-class cue log-bias/spread and bearing residual spread."""
    groups = defaultdict(list)
    for aid, oid in c.execute("select e.asset_estimate_id,e.observation_id from asset_estimate_evidence e join asset_estimates a on a.id=e.asset_estimate_id where a.state='multi_view_estimate' and a.n_observations>=3 and a.max_ray_angle_deg>=12"):
        groups[aid].append(oid)
    geo = {r[0]: r for r in c.execute('select observation_id,label,camera_x,camera_y,azimuth_deg,cues from observation_geometry')}
    err = defaultdict(lambda: defaultdict(list)); bres = defaultdict(list); used = 0
    for aid, oids in groups.items():
        g = [geo[o] for o in oids if o in geo]
        if len(g) < 3: continue
        obs = [(r[2], r[3], math.radians(r[4]), None, None) for r in g]
        X, cov, chi2, m, res, ahead = solve(obs, math.radians(DEFAULT_BEARING_SIGMA_DEG), use_range=False)
        if not ahead or np.sqrt(np.max(np.linalg.eigvalsh(cov))) > .6: continue
        used += 1; label = g[0][1]; bres[label] += list(res * DEFAULT_BEARING_SIGMA_DEG)
        for r in g:
            true = math.hypot(X[0] - r[2], X[1] - r[3])
            for k, q in json.loads(r[5]).items(): err[label][k].append(math.log(q.get('raw_range_m', q['range_m']) / true))
    out = {'version': VERSION, 'created_at': now(), 'pseudo_truth_objects': used, 'method': 'bearing-only triangulation of multi-view objects with >=3 rays, >=12 deg spread, sigma<0.6 m', 'cues': {}, 'bearing_sigma_deg': {}}
    for label, cues in err.items():
        out['cues'][label] = {}
        for k, e in cues.items():
            e = np.array(e); med = float(np.median(e)); out['cues'][label][k] = {'n': len(e), 'bias_log': med, 'sigma_log': float(max(.04, 1.4826 * np.median(np.abs(e - med)))), 'range_ratio_median': float(math.exp(med))}
    # Georegistration floor from independent passes: solve each sequence's sightings of one object alone;
    # disagreement beyond the solutions' own covariance is camera-position error (sigma per axis per pass).
    seq = {(p, i): json.loads(pl).get('sequence') for p, i, pl in c.execute("select provider,image_id,payload from sfm_pose where status='ok'")}
    full = {r[0]: r for r in c.execute('select observation_id,provider,image_id,camera_x,camera_y,azimuth_deg,range_m,range_sigma_log from observation_geometry')}
    per_obj = defaultdict(list)
    for aid, oid in c.execute("select e.asset_estimate_id,e.observation_id from asset_estimate_evidence e join asset_estimates a on a.id=e.asset_estimate_id where a.n_sequences>=2"):
        per_obj[aid].append(oid)
    excess = []
    for oids in per_obj.values():
        parts = defaultdict(list)
        for o in oids:
            r = full.get(o)
            if r and r[6]: parts[seq.get((r[1], r[2]))].append((r[3], r[4], math.radians(r[5]), r[6], r[7]))
        sols = [solve(v, math.radians(DEFAULT_BEARING_SIGMA_DEG)) for v in parts.values() if v]
        sols = [s for s in sols if s[5]]
        for a in range(len(sols)):
            for b in range(a + 1, len(sols)):
                d = sols[a][0] - sols[b][0]; excess.append((d @ d - np.trace(sols[a][1] + sols[b][1])) / 4)   # 2 axes x 2 passes
    if len(excess) >= 15:
        # median of a chi-square(2)-like quantity: divide by ln 2 to get the mean-square
        # Diagnostic only: merged drives share georegistration, so this understates absolute error (see CAMERA_FLOOR_M).
        out['cross_pass_disagreement_sigma_m'] = float(math.sqrt(max(0, np.median(excess) / math.log(2)))); out['cross_pass_pairs'] = len(excess)
    allb = np.concatenate([np.array(v) for v in bres.values()]) if bres else np.array([])
    if len(allb) > 20: out['bearing_sigma_deg']['_all'] = float(max(.3, 1.4826 * np.median(np.abs(allb))))
    for label, v in bres.items():
        if len(v) >= 30: out['bearing_sigma_deg'][label] = float(max(.3, 1.4826 * np.median(np.abs(v))))
    CALIBRATION.write_text(json.dumps(out, indent=2), encoding='utf-8'); print(json.dumps(out, indent=1), flush=True); return out


# ---------------------------------------------------------------- independent evaluation against town hydrants
HYDRANT_LAYERS = ['Available_Hydrants', 'Adopted_Hydrants']   # two public views of one Wellesley hydrant layer
HYDRANT_KEEP = ['OBJECTID', 'MapID', 'StreetNumber', 'StreetName']  # adopter name/email/phone are never stored


def fetch_ground_truth():
    feats = []
    for layer in HYDRANT_LAYERS:
        off = 0
        while True:
            r = requests.get(f'https://services6.arcgis.com/f6G5SbcwuEVmR1CW/arcgis/rest/services/{layer}/FeatureServer/0/query',
                             params={'where': '1=1', 'outFields': ','.join(HYDRANT_KEEP), 'outSR': 4326, 'f': 'geojson', 'resultOffset': off, 'resultRecordCount': 1000}, timeout=60)
            r.raise_for_status(); fs = r.json()['features']
            for f in fs: f['properties'] = {**{k: f['properties'].get(k) for k in HYDRANT_KEEP}, 'source_layer': layer}
            feats += fs; off += len(fs)
            if len(fs) < 1000: break
    d = OUT / 'ground_truth'; d.mkdir(exist_ok=True)
    (d / 'wellesley_hydrants.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats, 'source': 'Wellesley ArcGIS Online ' + ' + '.join(HYDRANT_LAYERS),
        'retrieved': now(), 'note': 'Personal adopter fields deliberately not requested.'}), encoding='utf-8')
    print('town hydrants', len(feats), flush=True)


def evaluate(c, gate=15.0):
    gt = json.loads((OUT / 'ground_truth' / 'wellesley_hydrants.geojson').read_text(encoding='utf-8'))
    T = np.array([TO.transform(*f['geometry']['coordinates'][:2]) for f in gt['features']]); tree = cKDTree(T)
    def stats(e):
        e = np.array(e)
        return {'n': int(len(e)), 'median_m': round(float(np.median(e)), 2), 'p75_m': round(float(np.percentile(e, 75)), 2), 'p90_m': round(float(np.percentile(e, 90)), 2),
                'within_2m': round(float(np.mean(e <= 2)), 3), 'within_5m': round(float(np.mean(e <= 5)), 3)} if len(e) else {'n': 0}
    est = c.execute("select id,state,x,y,n_observations,uncertainty95_m from asset_estimates where class='fire hydrant'").fetchall()
    cams = defaultdict(list)
    for aid, cx, cy in c.execute("select e.asset_estimate_id,g.camera_x,g.camera_y from asset_estimate_evidence e join observation_geometry g on g.observation_id=e.observation_id where g.label='fire hydrant'"):
        cams[aid].append((cx, cy))
    res = defaultdict(list); base = []; inside = []; matched_gt = set(); mv = []
    for aid, state, x, y, n, u95 in est:
        d, k = tree.query([x, y])
        if d > gate: continue
        matched_gt.add(int(k)); res[state].append(d); res['all'].append(d)
        if state == 'multi_view_estimate': mv.append((n, d))
        cd = min(math.hypot(cx - T[k][0], cy - T[k][1]) for cx, cy in cams[aid]); base.append(cd); inside.append(d <= u95)
    single = []
    for x, y, cx, cy in c.execute("select x,y,camera_x,camera_y from observation_geometry where label='fire hydrant' and x is not null"):
        d, k = tree.query([x, y])
        if d <= gate: single.append(d)
    bins = {'2 views': [d for n, d in mv if n == 2], '3-5 views': [d for n, d in mv if 3 <= n <= 5], '6+ views': [d for n, d in mv if n >= 6]}
    out = {'version': VERSION, 'evaluated_at': now(), 'ground_truth': 'Wellesley ArcGIS Online Available_Hydrants + Adopted_Hydrants (' + str(len(T)) + ' points; town GIS, not independently surveyed; never used for fitting)',
           'match_rule': 'nearest town hydrant within %.0f m of the estimate (gated; unmatched estimates are excluded, so this measures placement of real hydrants, not detector precision)' % gate,
           'estimated_hydrant_assets': len(est), 'matched_assets': len(res['all']), 'distinct_town_hydrants_matched': len(matched_gt),
           'asset_error': {k: stats(v) for k, v in res.items()}, 'by_view_count': {k: stats(v) for k, v in bins.items()},
           'single_observation_error': stats(single), 'baseline_camera_position_as_location': stats(base),
           'uncertainty95_coverage': round(float(np.mean(inside)), 3) if inside else None}
    (OUT / 'benchmarks').mkdir(exist_ok=True); (OUT / 'benchmarks' / 'localization-hydrants.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(json.dumps(out, indent=1), flush=True); return out


def diagnose(c, gate_deg=6.0):
    """Per-cue range error and bearing error of individual hydrant observations against town hydrants."""
    gt = json.loads((OUT / 'ground_truth' / 'wellesley_hydrants.geojson').read_text(encoding='utf-8'))
    T = np.array([TO.transform(*f['geometry']['coordinates'][:2]) for f in gt['features']]); tree = cKDTree(T)
    berr, cerr = [], defaultdict(list)
    for cx, cy, az, cues in c.execute("select camera_x,camera_y,azimuth_deg,cues from observation_geometry where label='fire hydrant'"):
        idx = tree.query_ball_point([cx, cy], 45)
        best = None
        for k in idx:
            dx, dy = T[k][0] - cx, T[k][1] - cy; a = math.degrees(math.atan2(dx, dy)); e = (a - az + 180) % 360 - 180
            if abs(e) < gate_deg and (best is None or abs(e) < abs(best[0])): best = (e, math.hypot(dx, dy))
        if not best: continue
        berr.append(best[0])
        for k, q in json.loads(cues).items(): cerr[k].append(math.log(q.get('raw_range_m', q['range_m']) / best[1]))
    q = lambda v: {'n': len(v), 'median': round(float(np.median(v)), 3), 'mad': round(float(1.4826 * np.median(np.abs(np.array(v) - np.median(v)))), 3)} if v else {'n': 0}
    out = {'bearing_error_deg': q(berr), 'log_range_error_raw': {k: {**q(v), 'ratio_median': round(math.exp(np.median(v)), 3)} for k, v in cerr.items()}}
    print(json.dumps(out, indent=1)); return out


# ---------------------------------------------------------------- export for the map viewers
def export(c):
    obs = {r[0]: r for r in c.execute('select g.observation_id,g.image_id,g.camera_x,g.camera_y,g.azimuth_deg,g.range_m,g.label,g.flags,g.cues,o.crop,o.box,o.score from observation_geometry g join observations o on o.id=g.observation_id')}
    def sighting(o):
        r = obs[o]; cues = json.loads(r[8]); b = json.loads(r[10])
        return {'observation_id': o, 'image_id': r[1], 'crop': r[9], 'view_file': b.get('view_file'), 'bbox_xyxy': b.get('xyxy'), 'image_width': b.get('width'), 'image_height': b.get('height'),
                'score': round(r[11], 3), 'range_m': round(r[5], 2) if r[5] else None, 'azimuth_deg': round(r[4], 2), 'camera': [round(v, 8) for v in BACK.transform(r[2], r[3])],
                'cues': {k: {'range_m': round(q['range_m'], 2), 'rejected': bool(q.get('rejected'))} for k, q in cues.items()}, 'flags': json.loads(r[7])}
    ev = defaultdict(list)
    for aid, oid in c.execute('select asset_estimate_id,observation_id from asset_estimate_evidence'): ev[aid].append(oid)
    feats, rays = [], []
    for aid, label, state, x, y, lon, lat, u95, ell, n, ni, ns, spread, red, flags, ver, upd in c.execute('select * from asset_estimates'):
        props = {'asset_estimate_id': aid, 'class': label, 'state': state, 'uncertainty95_m': round(u95, 2), 'ellipse': json.loads(ell), 'n_observations': n, 'n_images': ni,
                 'n_sequences': ns, 'max_ray_angle_deg': round(spread, 1), 'reduced_chi2': round(red, 2), 'flags': json.loads(flags), 'method': ver,
                 'sightings': [sighting(o) for o in ev[aid] if o in obs], 'location_type': 'estimated physical asset position; unreviewed'}
        feats.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(lon, 8), round(lat, 8)]}, 'properties': props})
        for o in ev[aid]:
            if o in obs: rays.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [list(BACK.transform(obs[o][2], obs[o][3])), [lon, lat]]}, 'properties': {'asset_estimate_id': aid, 'observation_id': o, 'class': label}})
    (OUT / 'asset-estimates.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}), encoding='utf-8')
    (OUT / 'asset-rays.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': rays}), encoding='utf-8')
    bench = OUT / 'benchmarks' / 'localization-hydrants.json'
    summary = {'updated_at': now(), 'version': VERSION, 'by_class_state': {}, 'calibration': load_calibration(), 'hydrant_benchmark': json.loads(bench.read_text(encoding='utf-8')) if bench.exists() else None}
    for label, state, n in c.execute('select class,state,count(*) from asset_estimates group by 1,2'): summary['by_class_state'].setdefault(label, {})[state] = n
    (OUT / 'asset-estimates-summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    print('exported', len(feats), 'asset estimates and', len(rays), 'rays', flush=True)


def run(c):
    if CALIBRATION.exists(): CALIBRATION.unlink()
    localize(c, {}); associate(c, {}); cal = calibrate(c); localize(c, cal); associate(c, cal); evaluate(c); export(c)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('command', choices=['enrich', 'localize', 'associate', 'calibrate', 'evaluate', 'diagnose', 'export', 'run', 'ground-truth'])
    p.add_argument('--limit', type=int, default=0); a = p.parse_args()
    c = sqlite3.connect(OUT / 'inventory.sqlite', timeout=60); c.execute('pragma busy_timeout=60000'); setup(c)
    {'enrich': lambda: enrich(c, a.limit), 'localize': lambda: localize(c), 'associate': lambda: associate(c), 'calibrate': lambda: calibrate(c),
     'evaluate': lambda: evaluate(c), 'diagnose': lambda: diagnose(c), 'export': lambda: export(c), 'run': lambda: run(c), 'ground-truth': fetch_ground_truth}[a.command]()
