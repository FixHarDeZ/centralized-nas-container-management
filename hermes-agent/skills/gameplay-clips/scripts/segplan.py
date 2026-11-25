#!/usr/bin/env python3
"""segplan.py — frame-exact seg layout from a windows.py table and YOUR ordered picks.

Run (container, clip workdir; stdlib only):
  python3 <skill>/scripts/segplan.py tr_windows.json --dur 16 \
      --picks "W4@31.9:hero,W1,W2,W3,W4@28.1,W5" [--endcard endcard_crop.json] [--write plan.json]

You choose WHICH windows and in WHAT order (from the labelled sheet: gameplay / cutscene / card / logo);
this script only does the arithmetic Hermes used to do in its head (tinzshop-zelda-sw2 2026-11-23: a
296 s / 21k-char turn to learn 16 s did not fit the flash-free spans; ps5-discdrive: 287 s on a 1.9 s
end card against the CTA rule). It places every pick inside its window's clean span, sums the segs to
--dur in whole frames, keeps the last seg >= --last-min, and prints the last seg's t0 (the input to the
CTA-gap math in natural-vo.md). It never chooses a shot.

Several sources (gta6-codebox-gp2 2026-11-25: hero from the raw clip, windows from two square crops of other
clips; Hermes merged three tables and patched src/audio by hand, reading build_v5's source 4 times):
  segplan.py tr_np20_windows.json winsqa_np20_windows.json winsqa_np19_windows.json --dur 19 \
      --picks "A:W1@10.4:hero,B:W1,B:W2,C:W2" --write plan.json
Tables are A, B, C… in the order given (no prefix = A). A seg whose table's "src" is the plan's "trailer" is
"src": "trailer" as before; any other is "src": <that file> with "audio_src": <that file>. Music: consecutive
segs from one source share ONE continuous bed (audio_in runs on from the previous seg's end), so the music jumps
only where the source changes — unless that bed would run into the source's "speech" spans; then that seg's
audio starts at its picture (printed as a music jump). --music follow = every seg's audio at its picture
(the one-table default, unchanged); --music continuous = the bed rule for one table too.
--audio B=master (or B=<file>): table B's music comes from that source instead of its own file — a square crop
of the trailer clip shares the trailer's timeline, so "B=master" keeps ONE bed across the raw hero and the crop's
windows (Hermes' gta6 hand plan). The bed is keyed by the audio source, not the table. A source file with no
audio stream is refused (exit 4: silent music, the "bed ran out" failure) — point --audio at its master.

Pick syntax: [A:]W<n>[@<t>][:hero|:window][+wide][+win_x=N][+hero_x=N][+max=S]
  W<n>   window number from the table; @t = start there (source s, inside the window), default start
         of the window (or right after the previous pick of the same window). A pick ends at the
         window end or at the next pick that starts later in the same window, whichever comes first.
  :hero  9:16 full-screen shot (default the first pick is NOT assumed hero — say it).
--endcard F  endcard_crop.json: its "seg" becomes the LAST seg at its own fixed length. crop null =
             refused unless --endcard-wide (whole 16:9 frame; build_v5 needs crop or wide).

Exit 0 = layout printed (and written with --write: only "segs" and "dur" change in the plan),
     1 = --dur does not fit: prints the longest reachable DUR (exact + the half second below it),
     2 = the table has no "wash" key = written before white-flash detection (2026-11-23) or copied
         from an older job: re-run windows.py on this source (command printed),
     3 = end card shorter than --last-min: prints the most CTA speech it allows (L - 1.6) and the
         alternative (drop --endcard, end on your longest window); --short-card-ok writes it anyway.
"""
import argparse
import json
import math
import os
import re
import sys

EDGE = 0.01           # s kept clear inside each window edge (the table already pads its dirty spans)
SEG_MIN = 1.0         # s, shortest seg written
WIN_MAX = 6.0         # s, a window seg longer than this reads as a slow static push-in (look-v5)
HERO_MAX = 3.5        # s, the hero shots in the delivered plans ran 2.8-3.6 s
CTA_TAIL = 1.6        # s, vo_end <= DUR - 1.6 (natural-vo.md)

PICK = re.compile(r"^(?:([A-Z]):)?W(\d+)(?:@([\d.]+))?(?::(hero|window))?((?:\+[a-z_]+(?:=-?[\d.]+)?)*)$")


def parse_picks(spec):
    out = []
    for raw in [p.strip() for p in spec.split(",") if p.strip()]:
        m = PICK.match(raw)
        if not m:
            raise SystemExit(f"bad pick {raw!r} (W<n>[@t][:hero|:window][+wide][+win_x=N][+hero_x=N][+max=S])")
        p = {"t": m.group(1) or "A", "w": int(m.group(2)), "at": float(m.group(3)) if m.group(3) else None,
             "mode": m.group(4) or "window", "raw": raw, "extra": {}, "max": None}
        for opt in [o for o in m.group(5).split("+") if o]:
            k, _, v = opt.partition("=")
            if k == "wide":
                p["extra"]["wide"] = True
            elif k in ("win_x", "hero_x"):
                p["extra"][k] = int(float(v))
            elif k == "max":
                p["max"] = float(v)
            else:
                raise SystemExit(f"bad option +{opt} in {raw!r}")
        out.append(p)
    return out


def place(picks, wins, fps):
    """-> picks with in (s) and cap_f (max whole frames) inside their windows. The table's windows are
    already padded off dark / flash / text / speech, so the edge margin is only EDGE s.
    wins: {table letter: {n: window}} (or one table's {n: window})."""
    if wins and not isinstance(next(iter(wins)), str):
        wins = {"A": wins}
    by_w = {}
    for p in picks:
        p.setdefault("t", "A")
        if p["t"] not in wins:
            raise SystemExit(f"{p['raw']}: no table {p['t']} (tables given: {', '.join(sorted(wins))})")
        tw = wins[p["t"]]
        w = tw.get(p["w"])
        if w is None:
            raise SystemExit(f"{p['raw']}: no window W{p['w']} in table {p['t']} (have W{', W'.join(map(str, sorted(tw)))})")
        if p["at"] is not None and not (w["start"] <= p["at"] < w["end"]):
            raise SystemExit(f"{p['raw']}: {p['at']} is outside W{p['w']} {w['start']:.2f}-{w['end']:.2f}")
        p["lo"], p["hi"] = w["start"] + EDGE, w["end"] - EDGE
        p["in"] = max(p["lo"], p["at"]) if p["at"] is not None else None
        by_w.setdefault((p["t"], p["w"]), []).append(p)
    for n, group in by_w.items():
        free = [p for p in group if p["in"] is None]
        if len(free) > 1:
            raise SystemExit(f"{n[0]}:W{n[1]} is picked {len(free)} times without a start: pin all but one with @t")
        for p in free:
            p["in"] = p["lo"]
        for p in group:
            later = [q["in"] for q in group if q is not p and q["in"] > p["in"]]
            end = min([p["hi"], *later])
            p["in"] = round(p["in"], 3)
            p["cap_f"] = max(0, math.floor(round((end - p["in"]) * fps, 6)))
    return picks


def fit(segs, total_f, fps, last_min_f):
    """Allocate frames: each seg starts at its preferred length, then the longest give frames back (or
    the ones with headroom take them) until the sum is total_f. -> frames list or None (cannot reach)."""
    pref = []
    for s in segs:
        if s.get("fixed_f") is not None:
            pref.append(s["fixed_f"])
            continue
        cap = s["cap_f"]
        soft = HERO_MAX if s["mode"] == "hero" else WIN_MAX
        if s.get("max"):
            soft = min(soft, s["max"])
        pref.append(min(cap, round(soft * fps)))
    lo = [s["fixed_f"] if s.get("fixed_f") is not None else min(s["cap_f"], round(SEG_MIN * fps)) for s in segs]
    hi = [s["fixed_f"] if s.get("fixed_f") is not None else s["cap_f"] for s in segs]
    if segs[-1].get("fixed_f") is None:
        lo[-1] = min(hi[-1], max(lo[-1], last_min_f))
    alloc = [max(lo_k, min(p, h)) for p, lo_k, h in zip(pref, lo, hi)]
    if sum(hi) < total_f or sum(lo) > total_f:
        return None
    while sum(alloc) > total_f:
        i = max((k for k in range(len(alloc)) if alloc[k] > lo[k]), key=lambda k: alloc[k] - lo[k])
        alloc[i] -= 1
    while sum(alloc) < total_f:
        # grow the seg with the most headroom left; past its soft length only when nothing else can
        room = [k for k in range(len(alloc)) if alloc[k] < min(hi[k], pref[k])] or \
               [k for k in range(len(alloc)) if alloc[k] < hi[k]]
        i = max(room, key=lambda k: hi[k] - alloc[k])
        alloc[i] += 1
    return alloc


def overlaps(a, b, spans, pad=0.05):
    return any(a < e + pad and s - pad < b for s, e in spans or [])


def bed_start(block, segs, meta):
    """Where one continuous bed for the block (consecutive segs, one audio source) starts on that source: at the
    first seg's picture when the whole block fits there, else at the first speech-free stretch long enough
    (gta6 hand plan: hero at 10.4 + two crop windows = 9.5 s did not fit after 10.4 in a 19.3 s clip; the bed ran
    from 0.1). None = no stretch holds it."""
    i0 = block[0]
    tab, reb = meta[i0]["tab"], meta[i0]["rebase"]
    need = sum(segs[i]["dur"] for i in block)
    total = float(tab.get("dur") or 1e9)
    speech = tab.get("speech") or []
    first = round(segs[i0]["in"] - reb, 3)
    starts = [first, *sorted({round(EDGE * 10, 3)} | {round(b - reb + EDGE * 10, 3) for _, b in speech})]
    for a in starts:
        if a >= 0 and a + reb + need <= total and not overlaps(a + reb, a + reb + need, speech):
            return a
    return None


def assign_audio(segs, meta, music, jumps):
    """audio_src / audio_in per seg. follow = each seg's audio at its picture; continuous = one bed per run of
    consecutive segs with the same audio source."""
    i = 0
    while i < len(segs):
        m = meta[i]
        if m is None:
            i += 1
            continue
        block = [i]
        while music == "continuous" and block[-1] + 1 < len(segs) and meta[block[-1] + 1] \
                and meta[block[-1] + 1]["a"] == m["a"]:
            block.append(block[-1] + 1)
        a0 = bed_start(block, segs, meta) if len(block) > 1 else None
        if len(block) > 1 and a0 is None:
            jumps.append(f"music jump inside segs {block[0]}-{block[-1]}: no speech-free stretch of the source holds "
                         "one bed for all of them; each seg's audio starts at its picture")
        for k in block:
            s, mk = segs[k], meta[k]
            ain = round(a0, 3) if a0 is not None else round(s["in"] - mk["rebase"], 3)
            if a0 is not None:
                a0 += s["dur"]
            if mk["a"] != "master":
                s["audio_src"], s["audio_in"] = mk["a"], ain
            elif s["src"] != "trailer" or mk["rebase"] or ain != s["in"]:
                s["audio_src"], s["audio_in"] = "master", ain
        i = block[-1] + 1


def has_audio(path):
    """True / False from ffprobe; None when it cannot tell (no ffprobe, no file)."""
    import shutil
    import subprocess
    if not shutil.which("ffprobe") or not os.path.exists(path):
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(p.stdout.strip()) if p.returncode == 0 else None


def same_file(a, b):
    return bool(a and b) and os.path.abspath(a) == os.path.abspath(b)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tables", nargs="+", metavar="table")
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--picks", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--last-min", type=float, default=4.0,
                    help="s; last seg >= CTA speech + 1.6 (natural-vo.md); 4.0 fits a <=2.4 s CTA line")
    ap.add_argument("--endcard")
    ap.add_argument("--endcard-wide", action="store_true")
    ap.add_argument("--short-card-ok", action="store_true")
    ap.add_argument("--write")
    ap.add_argument("--music", choices=["follow", "continuous"])
    ap.add_argument("--audio", action="append", default=[], metavar="L=SRC",
                    help="music source of table L: master or a file on the same timeline as that table")
    a = ap.parse_args(argv)

    tabs = {}
    for i, path in enumerate(a.tables):
        with open(path, encoding="utf-8") as fh:
            tabs[chr(65 + i)] = (path, json.load(fh))
    for path, tab in tabs.values():
        rc = old_table(path, tab)
        if rc:
            return rc
    return layout(a, tabs)


def old_table(path, tab):
    if "wash" not in tab:
        src = tab.get("src", "<source>.mp4")
        vtt = tab.get("speech_vtt") or tab.get("vtt")
        cmd = ("uv run --with faster-whisper --with rapidocr-onnxruntime --with numpy --with pillow python "
               "/opt/data/skills/gameplay-clips/scripts/windows.py " + os.path.basename(src)
               + (f" --vtt {os.path.basename(vtt)}" if vtt else "")
               + (f" --rebase {tab['rebase']}" if tab.get("rebase") else ""))
        print(f"TABLE TOO OLD: {path} has no \"wash\" key (made before white-flash detection or copied from "
              f"another job) — its windows can hold white flash frames build_v5 refuses. Re-run on a copy of the "
              f"source in this workdir:\n  {cmd}")
        return 2
    return 0


def layout(a, tabs):
    fps = a.fps
    total_f = round(a.dur * fps)
    if abs(total_f / fps - a.dur) > 1e-6:
        raise SystemExit(f"--dur {a.dur} is not a whole number of frames at {fps} fps")
    wins = {t: {w["n"]: w for w in tab["windows"]} for t, (_, tab) in tabs.items()}
    picks = place(parse_picks(a.picks), wins, fps)
    for p in picks:
        if p["cap_f"] < round(SEG_MIN * fps):
            raise SystemExit(f"{p['raw']}: only {p['cap_f'] / fps:.2f} s clean from {p['in']:.2f} "
                             f"(W{p['w']} ends {wins[p['t']][p['w']]['end']:.2f}) — under {SEG_MIN} s, drop or move it")
    trailer = None
    if a.write and os.path.exists(a.write):
        with open(a.write, encoding="utf-8") as fh:
            tr = json.load(fh).get("trailer")
        if tr:
            trailer = tr if os.path.isabs(tr) else os.path.join(os.path.dirname(os.path.abspath(a.write)), tr)
    is_trailer = {t: (len(tabs) == 1 if trailer is None else same_file(tab.get("src"), trailer))
                  for t, (_, tab) in tabs.items()}
    music = a.music or ("follow" if len(tabs) == 1 else "continuous")
    audio = {}
    for spec in a.audio:
        k, _, v = spec.partition("=")
        if k not in tabs or not v:
            raise SystemExit(f"--audio {spec!r}: want L=master|<file> with L one of {', '.join(sorted(tabs))}")
        audio[k] = v
    for t, (_, tab) in tabs.items():
        src = audio.get(t) or ("master" if is_trailer[t] else tab.get("src"))
        if src != "master" and any(p["t"] == t for p in picks) and has_audio(src) is False:
            print(f"NO AUDIO: {src} (table {t}) has no audio stream — its segs would get silent music. Pass "
                  f"--audio {t}=<that source's master or original clip>")
            return 4

    card = None
    if a.endcard:
        with open(a.endcard, encoding="utf-8") as fh:
            ec = json.load(fh)
        card = dict(ec.get("seg") or {})
        if not card:
            raise SystemExit(f"{a.endcard} has no \"seg\"")
        if not card.get("crop") and not card.get("wide"):
            if not a.endcard_wide:
                why = ec.get("problem") or "no crop"
                print(f"END CARD REFUSED: crop is null ({why}). Add --endcard-wide for the whole 16:9 frame "
                      f"(source >= 1280 px), or end on footage (drop --endcard).")
                return 3
            card["wide"] = True
        if card.get("crop") is None:
            card.pop("crop", None)
        card.update({"mode": "window", "endcard": True, "snap": False})
        card["fixed_f"] = round(float(card["dur"]) * fps)
        card_len = card["fixed_f"] / fps
        if card_len < a.last_min and not a.short_card_ok:
            longest = max(picks, key=lambda p: p["cap_f"])
            print(f"END CARD TOO SHORT: {card_len:.2f} s < --last-min {a.last_min} s. The CTA line must start inside the "
                  f"last seg and end by DUR-{CTA_TAIL}: at most {max(0.0, card_len - CTA_TAIL):.2f} s of CTA speech "
                  f"(~{max(0, int((card_len - CTA_TAIL) * 11))} Thai characters). Either write a CTA that short and re-run "
                  f"with --short-card-ok, or drop --endcard and end on {longest['raw']} "
                  f"({longest['cap_f'] / fps:.2f} s clean) as the last pick.")
            return 3

    segs = [dict(p) for p in picks] + ([card] if card else [])
    last_min_f = round(a.last_min * fps)
    alloc = fit(segs, total_f, fps, last_min_f)
    if alloc is None:
        hi = sum(s["fixed_f"] if s.get("fixed_f") is not None else s["cap_f"] for s in segs)
        lo = sum(s["fixed_f"] if s.get("fixed_f") is not None else min(s["cap_f"], round(SEG_MIN * fps))
                 for s in segs)
        if hi < total_f:
            best = hi / fps
            print(f"DOES NOT FIT: these picks hold at most {best:.3f} s clean ({hi} frames) < --dur {a.dur}. "
                  f"Longest reachable DUR = {best:.3f} s; on the half second: {math.floor(best * 2) / 2:.1f} s. "
                  f"Or add a pick (every pick below is at its window edge).")
        else:
            print(f"DOES NOT FIT: {len(segs)} segs of >= {SEG_MIN} s need {lo / fps:.2f} s > --dur {a.dur}: drop a pick.")
        for s in segs:
            if s.get("fixed_f") is None:
                print(f"  {s['raw']:<16} in {s['in']:7.2f}  clean {s['cap_f'] / fps:5.2f} s")
        return 1

    out, t0, jumps, meta = [], 0.0, [], []
    print("seg   t0      in     dur  mode    pick")
    for i, (s, f) in enumerate(zip(segs, alloc)):
        d = round(f / fps, 4)
        if s.get("endcard"):
            seg = {k: v for k, v in s.items() if k != "fixed_f"}
            seg["dur"] = d
            label = "endcard"
            meta.append(None)
        else:
            _, tab = tabs[s["t"]]
            src = "trailer" if is_trailer[s["t"]] else tab["src"]
            seg = {"src": src, "in": round(s["in"], 3), "dur": d, "mode": s["mode"], "snap": False}
            seg.update(s["extra"])
            meta.append({"a": audio.get(s["t"]) or ("master" if src == "trailer" else tab["src"]), "tab": tab,
                         "rebase": float(tab.get("rebase") or 0.0), "raw": s["raw"]})
            label = s["raw"]
        print(f"{i:<4} {t0:6.2f} {seg['in']:7.2f} {d:6.3f}  {seg['mode']:<7} {label}")
        out.append(seg)
        t0 += f / fps
    assign_audio(out, meta, music, jumps)
    last_t0 = sum(alloc[:-1]) / fps
    print(f"dur {a.dur} = {sum(alloc)} frames; last seg t0 = {last_t0:.3f} s, length {alloc[-1] / fps:.3f} s "
          f"-> CTA speech <= {alloc[-1] / fps - CTA_TAIL:.2f} s (starts >= {last_t0:.2f}, vo_end <= {a.dur - CTA_TAIL:.2f})")
    for j in jumps:
        print(j)
    print(json.dumps(out, ensure_ascii=False))
    if a.write:
        with open(a.write, encoding="utf-8") as fh:
            plan = json.load(fh)
        plan["segs"], plan["dur"] = out, a.dur
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, indent=1)
        print(f"-> {a.write}: segs + dur written; run build_v5.py {os.path.basename(a.write)} --check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
