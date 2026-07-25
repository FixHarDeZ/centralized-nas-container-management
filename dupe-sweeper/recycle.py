"""Delete = trust boundary. Every target path is realpath'd and asserted to
live under an allowed scan root BEFORE anything moves. A single violation
rejects the whole request (no partial deletes). This guards against malformed
requests and our own path-assembly bugs alike — basic auth is not a substitute.
"""

import os
import shutil
from datetime import datetime

TRASH_BASENAME = ".dupe-sweeper-trash"


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + os.sep)


def validate(paths, allowed_roots):
    """Realpath each target, assert it is under an allowed root.

    Raises ValueError on the first violation (before any file is touched).
    Returns [(realpath, owning_root), ...].
    """
    roots = [os.path.realpath(r) for r in allowed_roots]
    if not roots:
        raise ValueError("no allowed roots configured")
    out = []
    for p in paths:
        rp = os.path.realpath(p)
        root = next((r for r in roots if _under(rp, r)), None)
        if root is None:
            raise ValueError(f"path outside allowed roots: {p}")
        out.append((rp, root))
    return out


def recycle(paths, allowed_roots, trash_dir):
    """Move each path to trash_dir under a batch-timestamp folder, preserving
    its relative path. Validates ALL targets before moving ANY.

    Trash must be on the same filesystem as the media (config guarantees this)
    so os.rename is an atomic metadata move, not a multi-GB copy.
    """
    if not trash_dir:
        raise ValueError("TRASH_DIR not configured")
    validated = validate(paths, allowed_roots)
    batch = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    results = []
    freed = 0
    for rp, root in validated:
        rel = os.path.relpath(rp, root)
        dest = os.path.join(trash_dir, batch, rel)
        try:
            size = os.path.getsize(rp)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.rename(rp, dest)  # same filesystem → atomic, no copy
            freed += size
            results.append({"path": rp, "ok": True, "size": size})
        except OSError as e:
            results.append({"path": rp, "ok": False, "size": 0, "error": str(e)})
    return {"results": results, "freed": freed, "batch": batch}


def rename(path, new_name, allowed_roots):
    """Rename a file within its own folder. Trust boundary: old AND new path must
    resolve under an allowed root; new_name must be a bare basename (no path
    separators, not . or ..); no silent overwrite.
    """
    validate([path], allowed_roots)  # old path under a root
    if not new_name or new_name in (".", "..") or "/" in new_name or "\\" in new_name:
        raise ValueError("invalid new name")
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise ValueError("source is not a file")
    dest = os.path.join(os.path.dirname(real), new_name)
    validate([dest], allowed_roots)  # new path under a root too (don't trust construction)
    if os.path.exists(dest):
        raise ValueError("a file with that name already exists")
    os.rename(real, dest)
    return dest


def trash_stats(trash_dir):
    """Total size + file count currently in the recycle folder."""
    real = os.path.realpath(trash_dir) if trash_dir else ""
    size = 0
    count = 0
    if real and os.path.isdir(real):
        for dp, _, fns in os.walk(real):
            for fn in fns:
                try:
                    size += os.path.getsize(os.path.join(dp, fn))
                    count += 1
                except OSError:
                    pass
    return {"size": size, "count": count}


def list_trash(trash_dir):
    """List files currently in the recycle folder, grouped-ready by batch.
    Each entry: {name, path, size, mtime, batch}. batch = top-level folder under
    trash_dir (the recycle timestamp); '' for stray files at the root.
    """
    real = os.path.realpath(trash_dir) if trash_dir else ""
    out = []
    if real and os.path.isdir(real):
        for dp, _, fns in os.walk(real):
            for fn in fns:
                fp = os.path.join(dp, fn)
                rel = os.path.relpath(fp, real)
                batch = rel.split(os.sep, 1)[0] if os.sep in rel else ""
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                out.append({"name": fn, "path": fp, "size": st.st_size,
                            "mtime": st.st_mtime, "batch": batch})
    out.sort(key=lambda e: e["mtime"], reverse=True)
    return out


def restore(trash_file, allowed_roots, trash_dir):
    """Move a file from the recycle folder back to its original location.

    recycle() stored it at `<trash_dir>/<batch>/<orig_rel>` where orig_rel is the
    path relative to its owning scan root. Reverse that: dest = <owning_root>/<orig_rel>.
    Trust boundary: src must be inside trash_dir; dest is validated under an allowed
    root; no silent overwrite. ponytail: owning_root = the root trash_dir sits under
    (single-root setup); multi-root restore is out of scope — dest is still gated
    under allowed roots so nothing can escape regardless.
    """
    if not trash_dir:
        raise ValueError("TRASH_DIR not configured")
    roots = [os.path.realpath(r) for r in allowed_roots]
    td = os.path.realpath(trash_dir)
    if os.path.basename(td) != TRASH_BASENAME:
        raise ValueError(f"refusing: TRASH_DIR basename is not {TRASH_BASENAME}")
    src = os.path.realpath(trash_file)
    if not _under(src, td):
        raise ValueError("can only restore files from inside the recycle folder")
    if not os.path.isfile(src):
        raise ValueError("source is not a file")
    rel_full = os.path.relpath(src, td)          # <batch>/<orig_rel>
    parts = rel_full.split(os.sep, 1)
    if len(parts) < 2:
        raise ValueError("cannot determine original path (no batch prefix)")
    orig_rel = parts[1]
    owning_root = next((r for r in roots if td == r or td.startswith(r + os.sep)), None)
    if owning_root is None:
        raise ValueError("recycle folder is not under a scan root")
    dest = os.path.join(owning_root, orig_rel)
    validate([dest], allowed_roots)              # dest under a root (don't trust construction)
    if os.path.exists(dest):
        raise ValueError("a file already exists at the original location")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(src, dest)
    # prune now-empty batch dirs left behind, up to (not including) trash_dir
    d = os.path.dirname(src)
    while d != td and _under(d, td):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)
    return dest


def empty_trash(trash_dir, allowed_roots):
    """PERMANENTLY delete everything inside the recycle folder — the only
    irreversible op in the app. Config is guarded, not just the click:
      - basename must be exactly TRASH_BASENAME (a fat-fingered TRASH_DIR=/media/porn
        refuses because basename is 'porn', not our trash folder)
      - must live under a scan root, and must NOT equal a scan root
    Deletes the folder's CONTENTS, keeps the folder itself.
    """
    if not trash_dir:
        raise ValueError("TRASH_DIR not configured")
    real = os.path.realpath(trash_dir)
    if os.path.basename(real) != TRASH_BASENAME:
        raise ValueError(f"refusing: TRASH_DIR basename is not {TRASH_BASENAME}")
    roots = [os.path.realpath(r) for r in allowed_roots]
    if real in roots:
        raise ValueError("refusing: TRASH_DIR equals a scan root")
    if not any(real.startswith(r + os.sep) for r in roots):
        raise ValueError("refusing: TRASH_DIR is not under a scan root")

    stats = trash_stats(real)
    if os.path.isdir(real):
        for entry in os.listdir(real):
            p = os.path.join(real, entry)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
    return stats
