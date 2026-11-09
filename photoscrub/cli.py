import argparse
import os
import sys
import tempfile

from . import __version__
from .core import UnsupportedImage, clean

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".jpe"}


def _files(paths, recursive):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in EXTS:
                        yield os.path.join(root, n)
                if not recursive:
                    break
        else:
            yield p


def describe(path, rep):
    lines = [path]
    if rep.gps:
        lat, lon = rep.gps
        lines.append(f"  LOCATION: {lat}, {lon}  (https://www.openstreetmap.org/?mlat={lat}&mlon={lon})")
    for k, v in rep.fields.items():
        lines.append(f"  {k}: {v}")
    if rep.trailer:
        lines.append(f"  {rep.trailer:,} bytes hidden after the end of the image (can hold a video or a copy)")
    if rep.removed:
        lines.append("  Contains: " + ", ".join(rep.removed))
    if len(lines) == 1:
        lines.append("  nothing private found")
    return "\n".join(lines)


def _write_atomic(path, data):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".photoscrub-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(prog="photoscrub",
                                 description="Remove location and other hidden data from photos. "
                                             "The picture is not re-compressed.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect", help="show what the photos reveal, change nothing")
    i.add_argument("paths", nargs="+")
    i.add_argument("-r", "--recursive", action="store_true")
    c = sub.add_parser("clean", help="write cleaned copies (originals are never touched unless --in-place)")
    c.add_argument("paths", nargs="+")
    c.add_argument("-o", "--output", help="folder for the cleaned copies (default: next to the original, "
                                          "named NAME.clean.EXT)")
    c.add_argument("--in-place", action="store_true", help="replace the original files (cannot be undone)")
    c.add_argument("-r", "--recursive", action="store_true")
    c.add_argument("--strip-orientation", action="store_true",
                   help="also remove the rotation flag (the photo may then appear sideways)")
    c.add_argument("--strip-icc", action="store_true", help="also remove the colour profile")
    c.add_argument("--keep-trailer", action="store_true", help="keep data stored after the end of the image")
    a = ap.parse_args(argv)

    bad = ok = 0
    opts = {}
    if a.cmd == "clean":
        opts = dict(keep_orientation=not a.strip_orientation, keep_icc=not a.strip_icc,
                    keep_trailer=a.keep_trailer)
        if a.output:
            os.makedirs(a.output, exist_ok=True)
    for path in _files(a.paths, a.recursive):
        try:
            with open(path, "rb") as f:
                data = f.read()
            out, rep = clean(data, **opts)
        except UnsupportedImage as e:
            print(f"{path}\n  skipped: {e}", file=sys.stderr)
            bad += 1
            continue
        except OSError as e:
            print(f"{path}\n  cannot read: {e}", file=sys.stderr)
            bad += 1
            continue
        print(describe(path, rep))
        if a.cmd == "clean":
            if a.in_place:
                dest = path
            else:
                base, ext = os.path.splitext(os.path.basename(path))
                dest = os.path.join(a.output or os.path.dirname(path) or ".", f"{base}.clean{ext}")
                if os.path.abspath(dest) == os.path.abspath(path):
                    print("  refusing to overwrite the original", file=sys.stderr)
                    bad += 1
                    continue
            _write_atomic(dest, out)
            print(f"  -> {dest}  ({len(data) - len(out):,} bytes removed)")
        ok += 1
    print(f"\n{ok} image(s) processed" + (f", {bad} skipped" if bad else ""))
    return 1 if bad and not ok else 0
