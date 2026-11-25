#!/usr/bin/env python3
"""Does the product change colour INSIDE a Flow shot? Pixels, 0 vision.

    uv run --with 'opencv-python-headless<5' --with numpy python prodcheck.py SHOT.mp4 --ref ref1.jpg [--ref ref2.jpg]
        [--step 0.5] [--sheet out.jpg]

Each reference is located in frames every --step s (SIFT + RANSAC homography) and the frame is warped back into the
reference's coordinates. The first matched frame is the baseline; later frames are compared with it band by band
(6 horizontal bands of the product, only inside the matched area, after removing the frame's overall colour shift).
A band whose colour moves ΔE ≥ 15 and stays moved for ≥ 1 s is a CHANGE: cal-d-protein-1mo 2026-11-25, the boxes'
navy bottom band went brown / pink at 3 s (held ΔE 34-36) and the vision identity read said MATCH. 42 past shots:
19 matched and stayed stable (held ΔE ≤ 5.7), 23 never matched. `peak` = the highest ΔE a band held for 1 s.

Why not compare with the reference itself: Flow renders every product in its own colour grade, and the reference
crop carries background and shop text, so ref-vs-frame cell differences are 14-30 on clean shots too. A shot compared
with itself has the same grade. It catches a product that MORPHS mid-shot; it cannot see a product that is wrong
from its first matched frame (kiiz 2026-11-25: Flow drew a cartoon on the box from the start) — that stays vision's.

Products that SIFT cannot lock onto (round, glossy, soft, small in frame) report `no-match`: nothing measured,
not a pass. Exit 0 = stable / no-match, 1 = change, 2 = usage error. JSON on stdout. --sheet writes one image:
per reference, the baseline crop then the changed frames' crops (the same rectified view), for a vision read.
"""
import argparse
import json
import os
import sys

BANDS = 6
DE_CHANGE = 15.0          # 2026-11-25 calibration: cal-d holds 34-36; 19 clean matched shots peak <= 5.7
PERSIST_S = 1.0
MIN_INLIERS = 15
BAND_MIN_PX = 300
BAND_NAMES = ["top", "upper", "upper-middle", "lower-middle", "lower", "bottom"]


def _cv():
    import cv2
    import numpy as np
    return cv2, np


def lab(img):
    cv2, np = _cv()
    out = cv2.cvtColor(cv2.GaussianBlur(img, (0, 0), 2), cv2.COLOR_BGR2LAB).astype(np.float32)
    out[..., 0] *= 100 / 255
    out[..., 1:] -= 128
    return out


def load_ref(path, maxside=600):
    cv2, np = _cv()
    im = cv2.imread(path)
    if im is None:
        raise SystemExit(f"cannot read {path}")
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(g < 245)
    if len(xs):
        im = im[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = maxside / max(im.shape[:2])
    if s < 1:
        im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return im


def sample(video, step):
    cv2, _ = _cv()
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out, t = [], 0.0
    while t < n / fps - 0.04:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(t * fps))
        ok, f = cap.read()
        if ok:
            out.append((round(t, 2), f))
        t += step
    cap.release()
    return out


class Matcher:
    def __init__(self, ref):
        cv2, _ = _cv()
        self.cv2 = cv2
        self.ref = ref
        self.sift = cv2.SIFT_create(nfeatures=3000)
        self.bf = cv2.BFMatcher()
        self.rk, self.rd = self.sift.detectAndCompute(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), None)

    def match(self, frame):
        """(warped frame in ref coords, ref-space mask of the matched area) or None."""
        cv2, np = _cv()
        if self.rd is None or len(self.rk) < MIN_INLIERS:
            return None
        fk, fd = self.sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
        if fd is None or len(fk) < MIN_INLIERS:
            return None
        good = [p[0] for p in self.bf.knnMatch(self.rd, fd, k=2) if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < MIN_INLIERS:
            return None
        src = np.float32([self.rk[m.queryIdx].pt for m in good])
        dst = np.float32([fk[m.trainIdx].pt for m in good])
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        if H is None or int(mask.sum()) < MIN_INLIERS:
            return None
        h, w = self.ref.shape[:2]
        quad = cv2.perspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]])[None], H)[0]
        fa = frame.shape[0] * frame.shape[1]
        if not cv2.isContourConvex(quad.astype(np.int32)) or not 0.01 * fa < cv2.contourArea(quad) < 0.5 * fa:
            return None
        warped = cv2.warpPerspective(frame, np.linalg.inv(H), (w, h))
        hull = cv2.convexHull(src[mask.ravel() == 1].astype(np.int32))
        area = np.zeros((h, w), np.uint8)
        cv2.fillConvexPoly(area, hull, 1)
        return warped, area.astype(bool)


def band_means(L, mask):
    import numpy as np
    ys = np.where(mask.any(1))[0]
    if not len(ys):
        return [None] * BANDS
    y0, y1 = ys.min(), ys.max() + 1
    out = []
    for i in range(BANDS):
        a, b = y0 + (y1 - y0) * i // BANDS, y0 + (y1 - y0) * (i + 1) // BANDS
        m = mask[a:b]
        out.append(L[a:b][m].mean(0) if m.sum() >= BAND_MIN_PX else None)
    return out


def band_shift(base, cur):
    """ΔE per band after removing the frame's overall shift (median over bands)."""
    import numpy as np
    idx = [i for i in range(BANDS) if base[i] is not None and cur[i] is not None]
    if len(idx) < 3:
        return {}
    d = np.array([cur[i] - base[i] for i in idx])
    d = d - np.median(d, 0)
    return {i: float(np.sqrt((v ** 2).sum())) for i, v in zip(idx, d)}


def find_changes(series, step, de=DE_CHANGE, persist=PERSIST_S):
    """series: [(t, {band: ΔE})] for matched frames. A band ≥ de for ≥ persist s of consecutive samples."""
    need = max(2, round(persist / step) + 1)
    flags = []
    for b in range(BANDS):
        run = []
        for t, row in [*series, (None, {})]:
            if t is not None and row.get(b, 0) >= de:
                run.append((t, row[b]))
                continue
            if len(run) >= need:
                flags.append({"band": BAND_NAMES[b], "from": run[0][0], "to": run[-1][0],
                              "de": round(max(v for _, v in run), 1)})
            run = []
    return flags


def sustained_peak(series, step, persist=PERSIST_S):
    """The highest ΔE a band holds for `persist` s (min over each window of consecutive samples, max over windows)."""
    need = max(2, round(persist / step) + 1)
    best = 0.0
    for b in range(BANDS):
        vals = [row.get(b, 0.0) for _, row in series]
        for i in range(len(vals) - need + 1):
            best = max(best, min(vals[i:i + need]))
    return round(best, 1)


def analyze(video, refs, step=0.5):
    frames = sample(video, step)
    result = {}
    for rp in refs:
        ref = load_ref(rp)
        m = Matcher(ref)
        base = base_mask = base_t = None
        crops, series = {}, []
        for t, f in frames:
            got = m.match(f)
            if not got:
                continue
            warped, mask = got
            L = lab(warped)
            if base is None:
                base, base_mask, base_t = L, mask, t
                crops[t] = warped
                series.append((t, {}))
                continue
            both = base_mask & mask
            series.append((t, band_shift(band_means(base, both), band_means(L, both))))
            crops[t] = warped
        flags = find_changes(series, step)
        result[os.path.basename(rp)] = {
            "matched": len(series), "of": len(frames), "baseline_t": base_t, "flags": flags,
            "peak": sustained_peak(series, step),
            "_crops": crops, "_ref": ref}
    return result


def verdict(res):
    if any(r["flags"] for r in res.values()):
        return "change"
    return "stable" if any(r["matched"] >= 2 for r in res.values()) else "no-match"


def write_sheet(res, out, h=300):
    cv2, np = _cv()
    rows = []
    for name, r in res.items():
        if not r["flags"]:
            continue
        times = [r["baseline_t"], *sorted({f["from"] for f in r["flags"]} | {f["to"] for f in r["flags"]})]
        tiles = [("REF " + name, r["_ref"]), *[(f"{t:.1f}s" + (" BASE" if t == r["baseline_t"] else ""), r["_crops"][t])
                                               for t in times if t in r["_crops"]]]
        row = []
        for label, im in tiles:
            im = cv2.resize(im, (max(1, int(im.shape[1] * h / im.shape[0])), h))
            im = cv2.copyMakeBorder(im, 28, 0, 0, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            cv2.putText(im, label, (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            row.append(im)
        rows.append(np.hstack(row))
    if not rows:
        return None
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 6, 0, w - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


def public(res):
    return {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in res.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("--ref", action="append", required=True)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--sheet")
    a = ap.parse_args(argv)
    for p in [a.video, *a.ref]:
        if not os.path.exists(p):
            print(json.dumps({"error": f"no such file: {p}"}))
            return 2
    res = analyze(a.video, a.ref, a.step)
    out = {"verdict": verdict(res), "refs": public(res)}
    if a.sheet and out["verdict"] == "change":
        out["sheet"] = write_sheet(res, a.sheet)
    print(json.dumps(out, ensure_ascii=False))
    return 1 if out["verdict"] == "change" else 0


if __name__ == "__main__":
    sys.exit(main())
