#!/usr/bin/env python3
"""Clip performance tracker: which hooks/styles actually sell.

Data: logs/perf-log.jsonl (append-only, one row per stats reading), joined to
logs/clip-log.jsonl by sha256 (or by product substring when sha unknown).
clip-log.jsonl is never rewritten.

Usage:
  perf.py add --match "<product substring | sha256 prefix>" --views N [--clicks N] [--orders N]
              [--date YYYY-MM-DD] [--platform shopee|reels|tiktok]
      -> appends one reading (latest reading per clip+platform wins in reports)
  perf.py report [--by hook_id|style|category] [--min-views 0]
      -> table: clips, views, CTR (clicks/views), CVR (orders/clicks)
  perf.py pick-hook --category game|gadget|... [--prefix gph-] [--candidates id1,id2,...]
      -> recommended hook id: excludes the last 5 distinct ids of the SAME FAMILY (game-N, gph-N, ...;
         at least 2 stay eligible), ranks the rest by CTR (Bayesian-smoothed, needs perf data), else LRU.
         A use = a clip-log row OR a storyboard that carried the id (`clipjob.py board --hook-id`, every
         board of every job, cancelled ones too): a template Fix rewrote on the board was still heard.
Exit codes: 0 ok, 2 bad args / no match, 3 ambiguous match.
"""
import argparse, collections, datetime, glob, json, os, re, sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP_LOG = os.environ.get("CLIP_LOG", "/opt/data/clips/logs/clip-log.jsonl")
PERF_LOG = os.environ.get("PERF_LOG", "/opt/data/clips/logs/perf-log.jsonl")
HOOKS_MD = os.path.join(SKILL, "templates", "hooks.md")
JOBS_DIR = os.environ.get("CLIPJOB_DIR", "/opt/data/clips/jobs")
RECENT = 5
LEGACY_HOOK_RE = re.compile(r"\bhook(?:_id)?[ =:]+(?:-> ?)?((?:[a-z]+|custom-[a-z0-9-]+)-\d+)\b")


def rows(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def latest_perf():
    """sha256 -> aggregated latest reading per platform."""
    best = {}
    for r in rows(PERF_LOG):
        key = (r["sha256"], r.get("platform", "shopee"))
        if key not in best or r.get("date", "") >= best[key].get("date", ""):
            best[key] = r
    agg = collections.defaultdict(lambda: {"views": 0, "clicks": 0, "orders": 0})
    for (sha, _), r in best.items():
        for k in ("views", "clicks", "orders"):
            agg[sha][k] += int(r.get(k) or 0)
    return agg


def cmd_add(a):
    clips = rows(CLIP_LOG)
    m = a.match.lower()
    hits = [c for c in clips if c.get("sha256", "").startswith(m) or m in c.get("product", "").lower()]
    # a revised clip has several rows; the newest row is the shipped file
    by_product = collections.OrderedDict()
    for c in hits:
        by_product[c.get("product")] = c
    if not by_product:
        print(f"no clip-log row matches {a.match!r}", file=sys.stderr); return 2
    if len(by_product) > 1:
        names = list(by_product)
        print(f"ambiguous ({len(names)} products), first 10:", *names[:10], sep="\n  ", file=sys.stderr)
        print("narrow --match (more words, or a sha256 prefix)", file=sys.stderr); return 3
    c = list(by_product.values())[0]
    rec = {"date": a.date or datetime.date.today().isoformat(), "sha256": c["sha256"],
           "product": c.get("product"), "hook_id": c.get("hook_id"), "style": c.get("style"),
           "category": c.get("category"), "platform": a.platform,
           "views": a.views, "clicks": a.clicks, "orders": a.orders}
    with open(PERF_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False)); return 0


def ctr_smoothed(clicks, views, prior_ctr=0.02, prior_views=500):
    return (clicks + prior_ctr * prior_views) / (views + prior_views)


def cmd_report(a):
    perf = latest_perf()
    clips = {c["sha256"]: c for c in rows(CLIP_LOG) if c.get("sha256")}
    groups = collections.defaultdict(lambda: {"n": 0, "views": 0, "clicks": 0, "orders": 0})
    for sha, p in perf.items():
        c = clips.get(sha, {})
        g = groups[str(c.get(a.by) or "?")]
        if p["views"] < a.min_views:
            continue
        g["n"] += 1
        for k in ("views", "clicks", "orders"):
            g[k] += p[k]
    if not groups:
        print("no perf data yet — add readings with: perf.py add --match ... --views N --clicks N --orders N")
        return 0
    print(f"{a.by:<28}{'clips':>6}{'views':>9}{'CTR%':>7}{'CVR%':>7}")
    for k, g in sorted(groups.items(), key=lambda kv: -ctr_smoothed(kv[1]["clicks"], kv[1]["views"])):
        ctr = 100 * g["clicks"] / g["views"] if g["views"] else 0
        cvr = 100 * g["orders"] / g["clicks"] if g["clicks"] else 0
        print(f"{k:<28}{g['n']:>6}{g['views']:>9}{ctr:>7.2f}{cvr:>7.2f}")
    return 0


def hook_ids_from_md(category, prefix):
    if not os.path.exists(HOOKS_MD):
        return []
    pat = re.escape(prefix) if prefix else re.escape(category) + "-"
    return sorted(set(re.findall(r"`(" + pat + r"\d+)`", open(HOOKS_MD, encoding="utf-8").read())),
                  key=lambda s: int(re.findall(r"\d+", s)[-1]))


def board_uses(jobs_dir=None):
    """[(iso time, hook id)] for every storyboard sent with `clipjob.py board --hook-id`."""
    out = []
    for p in glob.glob(os.path.join(jobs_dir or JOBS_DIR, "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(j, dict):
            continue
        hooks = (j.get("board") or {}).get("hooks")
        if hooks:
            out += [(h["at"], h["id"]) for h in hooks if h.get("id") and h.get("at")]
            continue
        for e in j.get("events") or []:      # jobs boarded before --hook-id: Hermes' own "board … hook <id>" notes
            m = LEGACY_HOOK_RE.search(e.get("msg") or "")
            if m and e.get("ts") and "board" in e["msg"]:
                out.append((e["ts"], m.group(1)))
    return out


def hook_uses(cat_rows, family):
    """Time-ordered uses of the candidate ids: clip-log rows (date only, file order) + board picks (timestamp).
    Only ids in `family` count: the `game` category holds presenter game-N rows AND gameplay gph-N rows, and the
    last 3 rows of the category were all gph-N, so the presenter rotation never excluded anything (2026-11-26)."""
    uses = [((c.get("date") or "", "", i), c.get("hook_id")) for i, c in enumerate(cat_rows)
            if c.get("hook_id") in family]
    uses += [((at[:10], at, 0), h) for at, h in board_uses() if h in family]
    return uses


def cmd_pick(a):
    cands = a.candidates.split(",") if a.candidates else hook_ids_from_md(a.category, a.prefix)
    if not cands:
        print("no candidate hook ids", file=sys.stderr); return 2
    cat_rows = [c for c in rows(CLIP_LOG) if c.get("category") == a.category]
    uses = sorted(hook_uses(cat_rows, set(cands)))
    seq = [h for _, h in uses]
    recent = []
    for h in reversed(seq):                   # last N distinct ids of this family, newest first
        if h not in recent:
            recent.append(h)
    recent = recent[:min(RECENT, max(1, len(cands) - 2))]
    last_use = {h: i for i, h in enumerate(seq)}
    perf = latest_perf()
    hook_perf = collections.defaultdict(lambda: [0, 0])
    for c in cat_rows:
        p = perf.get(c.get("sha256"))
        if p:
            hook_perf[c.get("hook_id")][0] += p["clicks"]
            hook_perf[c.get("hook_id")][1] += p["views"]
    pool = [h for h in cands if h not in recent] or cands
    has_perf = any(hook_perf[h][1] > 0 for h in pool)

    def key(h):
        lru = last_use.get(h, -1)  # never used = most eligible
        if has_perf:
            # unseen hooks get the prior CTR -> explored, but a proven winner outranks them
            return (-ctr_smoothed(*hook_perf[h]), lru)
        return (lru,)
    pick = sorted(pool, key=key)[0]
    print(json.dumps({"pick": pick, "mode": "perf" if has_perf else "lru", "excluded_recent": recent,
                      "perf": {h: {"clicks": hook_perf[h][0], "views": hook_perf[h][1]} for h in pool if hook_perf[h][1]}},
                     ensure_ascii=False))
    return 0


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    ad = s.add_parser("add"); ad.add_argument("--match", required=True)
    ad.add_argument("--views", type=int, required=True); ad.add_argument("--clicks", type=int, default=0)
    ad.add_argument("--orders", type=int, default=0); ad.add_argument("--date")
    ad.add_argument("--platform", default="shopee")
    rp = s.add_parser("report"); rp.add_argument("--by", default="hook_id"); rp.add_argument("--min-views", type=int, default=0)
    pk = s.add_parser("pick-hook"); pk.add_argument("--category", required=True)
    pk.add_argument("--prefix"); pk.add_argument("--candidates")
    a = p.parse_args()
    return {"add": cmd_add, "report": cmd_report, "pick-hook": cmd_pick}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
