"""Camera models shared by CPU localization and the GPU depth worker (numpy only, OpenSfM conventions).

Camera frame: x right, y down, z forward. Panoramas are sampled into 90-degree cube faces by
wellesley_pipeline.views(); these functions are its exact inverse."""
import math
import numpy as np

FACES = {'front': (0, 0), 'right': (90, 0), 'back': (180, 0), 'left': (270, 0), 'up': (0, 90), 'down': (0, -90)}


def face_to_cam(u, v, size, view):
    """Cube-face pixel -> unit bearing (pixel centres sit at (i+.5)/size, as in views())."""
    yaw, pitch = FACES[view]
    x = np.asarray(u, float) / size * 2 - 1; y = -(np.asarray(v, float) / size * 2 - 1); z = np.ones_like(x)
    a = math.radians(pitch); rx = x; ry = y * math.cos(a) + z * math.sin(a); rz = -y * math.sin(a) + z * math.cos(a)
    a = math.radians(yaw); xx = rx * math.cos(a) + rz * math.sin(a); zz = -rx * math.sin(a) + rz * math.cos(a)
    b = np.stack([xx, -ry, zz], -1); return b / np.linalg.norm(b, axis=-1, keepdims=True)


def cam_to_face(b, size, view):
    """Unit bearings -> (u, v, in_front) in a cube face; also usable for z-depth: depth = range * z_face."""
    u, v, ok, _ = cam_to_face_z(b, size, view); return u, v, ok


def cam_to_face_z(b, size, view):
    yaw, pitch = FACES[view]
    xx, ry, zz = b[:, 0], -b[:, 1], b[:, 2]
    a = math.radians(yaw); rx = xx * math.cos(a) - zz * math.sin(a); rz = xx * math.sin(a) + zz * math.cos(a)
    a = math.radians(pitch); y = ry * math.cos(a) - rz * math.sin(a); z = ry * math.sin(a) + rz * math.cos(a)
    ok = z > 1e-6; zs = np.where(ok, z, 1)
    return (rx / zs + 1) / 2 * size, (1 - y / zs) / 2 * size, ok, z


def _distort(r2, k1, k2): return 1 + k1 * r2 + k2 * r2 * r2


def _params(params): return (list(params) + [0, 0, 0])[:3] if params else (0.85, 0, 0)


def flat_to_cam(u, v, w, h, params, kind):
    f, k1, k2 = _params(params)
    m = max(w, h); px = (np.asarray(u, float) - w / 2) / m / f; py = (np.asarray(v, float) - h / 2) / m / f
    if kind == 'fisheye':
        th = np.hypot(px, py); t = th.copy()
        for _ in range(10): t = th / _distort(t * t, k1, k2)
        s = np.where(th > 1e-9, np.tan(t) / np.maximum(th, 1e-9), 1); x, y = px * s, py * s
    else:
        x, y = px.copy(), py.copy()
        for _ in range(10): d = _distort(x * x + y * y, k1, k2); x, y = px / d, py / d
    b = np.stack([x, y, np.ones_like(x)], -1); return b / np.linalg.norm(b, axis=-1, keepdims=True)


def cam_to_flat(b, w, h, params, kind):
    f, k1, k2 = _params(params)
    ok = b[:, 2] > 1e-6; z = np.where(ok, b[:, 2], 1); x, y = b[:, 0] / z, b[:, 1] / z
    if kind == 'fisheye':
        r = np.hypot(x, y); th = np.arctan(r); s = np.where(r > 1e-9, th * _distort(th * th, k1, k2) / np.maximum(r, 1e-9), 1)
    else:
        s = _distort(x * x + y * y, k1, k2)
    m = max(w, h); return x * s * f * m + w / 2, y * s * f * m + h / 2, ok
