"""SfM-anchored monocular depth cue (GPU; run with the TDA env).

Depth Anything V2 Small (Apache-2.0, relative inverse depth) runs on each cube face that holds a detection.
Its output has no metric scale, so every face gets its own robust affine fit 1/z = a*D + b against the
Mapillary SfM points visible in that face. Each box then reads an SfM-anchored range from the dense map.
asset_localization.py uses it only where the box itself has no SfM points, so the two cues are not double-counted.
"""
import argparse, json, math, sqlite3, time, datetime as dt
from collections import defaultdict
from pathlib import Path
import numpy as np, torch
from PIL import Image
from sfm_geometry import cam_to_face_z, cam_to_flat

ROOT = Path(__file__).resolve().parent; OUT = ROOT / 'data' / 'wellesley'
MODEL = 'depth-anything/Depth-Anything-V2-Small-hf'


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()


def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS observation_depth(observation_id TEXT PRIMARY KEY,range_m REAL,fit_points INTEGER,fit_mad_log REAL,a REAL,b REAL,model TEXT,created_at TEXT)'); c.commit()


def fit_inverse_depth(D, z):
    """Robust affine fit of inverse depth 1/z = a*D + b (Huber IRLS). Returns a, b, MAD of log-depth residuals."""
    y = 1 / z; A = np.c_[D, np.ones_like(D)]; w = np.ones_like(y)
    for _ in range(15):
        sol = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)[0]; r = A @ sol - y
        s = 1.4826 * np.median(np.abs(r)) + 1e-9; w = np.sqrt(np.where(np.abs(r) < 1.5 * s, 1, 1.5 * s / np.abs(r)))
    a, b = sol; pred = A @ sol
    if a <= 0: return None
    good = pred > 1e-4
    if good.sum() < 10: return None
    lr = np.log(1 / pred[good]) - np.log(z[good]); return float(a), float(b), float(1.4826 * np.median(np.abs(lr - np.median(lr))))


def project(points, box, pose):
    """SfM points (camera frame, metres) -> pixel u, v, z-depth along the view's optical axis."""
    rng = np.linalg.norm(points, axis=1); b = points / rng[:, None]
    if box.get('view', 'flat') == 'flat':
        u, v, ok = cam_to_flat(b, box['width'], box['height'], pose.get('camera_parameters'), pose.get('camera_type')); return u, v, ok, rng * b[:, 2]
    u, v, ok, zf = cam_to_face_z(b, box['width'], box['view']); return u, v, ok, rng * zf


def run(limit, batch):
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    c = sqlite3.connect(OUT / 'inventory.sqlite', timeout=60); c.execute('pragma busy_timeout=60000'); setup(c)
    rows = c.execute('''select o.id,o.image_id,o.box,p.payload,p.mesh_file from observations o join sfm_pose p on p.provider=o.provider and p.image_id=o.image_id
                        left join observation_depth d on d.observation_id=o.id where p.status='ok' and p.mesh_file is not null and d.observation_id is null''').fetchall()
    views = defaultdict(list)
    for oid, image_id, box, payload, mesh in rows:
        b = json.loads(box)
        if b.get('view_file'): views[(image_id, b['view_file'], mesh, payload)].append((oid, b))
    keys = list(views)[:limit] if limit else list(views); print('faces to process', len(keys), 'observations', sum(len(views[k]) for k in keys), flush=True)
    # batches must share an input shape: cube faces are square, flat photos keep their aspect ratio
    shape = lambda key: (views[key][0][1]['width'], views[key][0][1]['height'])
    groups = defaultdict(list)
    for key in keys: groups[shape(key)].append(key)
    chunks = [g[k:k + batch] for g in groups.values() for k in range(0, len(g), batch)]
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = AutoImageProcessor.from_pretrained(MODEL, use_fast=True); model = AutoModelForDepthEstimation.from_pretrained(MODEL).to(dev).eval()
    t0 = time.time(); done = 0
    for n_chunk, chunk in enumerate(chunks):
        ims = []
        for image_id, vf, mesh, payload in chunk:
            try: ims.append(Image.open(ROOT / vf).convert('RGB'))
            except OSError: ims.append(None)
        valid = [i for i, im in enumerate(ims) if im is not None]
        if not valid: continue
        with torch.inference_mode():
            inp = proc(images=[ims[i] for i in valid], return_tensors='pt').to(dev)
            pred = model(pixel_values=inp['pixel_values']).predicted_depth.float()
        out = []
        for slot, i in enumerate(valid):
            image_id, vf, mesh, payload = chunk[i]; im = ims[i]
            D = torch.nn.functional.interpolate(pred[slot][None, None], size=(im.height, im.width), mode='bilinear', align_corners=False)[0, 0].cpu().numpy()
            pose = json.loads(payload); pts = np.load(ROOT / mesh); obs = views[chunk[i]]; box0 = obs[0][1]
            u, v, ok, z = project(pts, box0, pose); inside = ok & (u >= 0) & (u < im.width - 1) & (v >= 0) & (v < im.height - 1) & (z > 1.5) & (z < 150)
            fit = None
            if inside.sum() >= 20: fit = fit_inverse_depth(D[v[inside].astype(int), u[inside].astype(int)], z[inside])
            for oid, b in obs:
                rng = None
                if fit:
                    x0, y0, x1, y1 = b['xyxy']; w, h = x1 - x0, y1 - y0
                    xi = slice(int(max(0, x0 + .25 * w)), int(min(im.width, max(x0 + .25 * w + 1, x1 - .25 * w)))); yi = slice(int(max(0, y0 + .25 * h)), int(min(im.height, max(y0 + .25 * h + 1, y1 - .25 * h))))
                    patch = D[yi, xi]
                    if patch.size:
                        inv = fit[0] * float(np.percentile(patch, 70)) + fit[1]   # 70th pct disparity = object, not background
                        if inv > 1e-4:
                            uc, vc = (x0 + x1) / 2, (y0 + y1) / 2
                            if b.get('view', 'flat') == 'flat':
                                f = (pose.get('camera_parameters') or [.85])[0] * max(b['width'], b['height']); off = math.hypot((uc - b['width'] / 2) / f, (vc - b['height'] / 2) / f)
                            else: off = math.hypot(uc / b['width'] * 2 - 1, vc / b['height'] * 2 - 1)
                            rng = (1 / inv) * math.sqrt(1 + off * off)   # z-depth -> slant range along the box-centre ray
                out.append((oid, rng, int(inside.sum()), fit[2] if fit else None, fit[0] if fit else None, fit[1] if fit else None, MODEL, now()))
        with c: c.executemany('insert or replace into observation_depth values(?,?,?,?,?,?,?,?)', out)
        done += len(chunk)
        if n_chunk % 25 == 0: print('faces', done, '/', len(keys), round(done / (time.time() - t0), 1), 'faces/s', flush=True)
    print('depth cue rows', c.execute('select count(*),sum(range_m is not null) from observation_depth').fetchone(), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0]); p.add_argument('--limit', type=int, default=0); p.add_argument('--batch', type=int, default=8); a = p.parse_args(); run(a.limit, a.batch)
