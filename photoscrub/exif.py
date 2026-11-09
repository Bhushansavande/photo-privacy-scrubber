"""A small, forgiving EXIF reader: just enough to show what a photo reveals about you."""

import struct

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

IFD0_TAGS = {0x010F: "Camera maker", 0x0110: "Camera model", 0x0131: "Software", 0x0132: "Date/time",
             0x013B: "Artist", 0x8298: "Copyright", 0x010E: "Description", 0x9C9F: "Author (Windows)"}
EXIF_TAGS = {0x9003: "Date taken", 0xA431: "Camera serial number", 0xA434: "Lens model",
             0xA435: "Lens serial number", 0xA430: "Owner name", 0x9286: "User comment",
             0xA420: "Unique image ID"}


def _read_ifd(tiff, off, end, depth=0):
    """Return {tag: (type, count, raw_value_bytes_or_offset_data)} for one IFD."""
    out = {}
    if off < 8 or off + 2 > len(tiff) or depth > 3:
        return out
    n = struct.unpack_from(end + "H", tiff, off)[0]
    for i in range(min(n, 512)):
        p = off + 2 + 12 * i
        if p + 12 > len(tiff):
            break
        tag, typ, cnt = struct.unpack_from(end + "HHI", tiff, p)
        size = TYPE_SIZE.get(typ)
        if size is None or cnt > (1 << 20):
            continue
        total = size * cnt
        if total <= 4:
            data = tiff[p + 8:p + 8 + total]
        else:
            vo = struct.unpack_from(end + "I", tiff, p + 8)[0]
            data = tiff[vo:vo + total]
            if len(data) < total:
                continue
        out[tag] = (typ, cnt, data)
    return out


def _ascii(v):
    return v[2].split(b"\0")[0].decode("utf-8", "replace").strip() if v[0] == 2 else None


def _rationals(v, end):
    typ, cnt, data = v
    if typ not in (5, 10):
        return []
    f = end + ("II" if typ == 5 else "ii")
    vals = []
    for i in range(cnt):
        a, b = struct.unpack_from(f, data, i * 8)
        vals.append(a / b if b else 0.0)
    return vals


def _dms(vals, ref):
    if len(vals) < 3:
        return None
    deg = vals[0] + vals[1] / 60 + vals[2] / 3600
    return -deg if ref in ("S", "W") else deg


def parse(exif):
    """exif: bytes starting at the TIFF header ('II*\\0' or 'MM\\0*'). Returns a dict of findings."""
    info = {"orientation": 1, "fields": {}, "gps": None}
    if len(exif) < 8 or exif[:2] not in (b"II", b"MM"):
        return info
    end = "<" if exif[:2] == b"II" else ">"
    try:
        ifd0 = _read_ifd(exif, struct.unpack_from(end + "I", exif, 4)[0], end)
        for tag, name in IFD0_TAGS.items():
            if tag in ifd0 and ifd0[tag][0] == 2:
                info["fields"][name] = _ascii(ifd0[tag])
        if 0x0112 in ifd0 and ifd0[0x0112][0] == 3:
            info["orientation"] = struct.unpack_from(end + "H", ifd0[0x0112][2], 0)[0]
        if 0x8769 in ifd0:
            sub = _read_ifd(exif, struct.unpack_from(end + "I", ifd0[0x8769][2], 0)[0], end, 1)
            for tag, name in EXIF_TAGS.items():
                if tag in sub and sub[tag][0] == 2:
                    info["fields"][name] = _ascii(sub[tag])
        if 0x8825 in ifd0:
            g = _read_ifd(exif, struct.unpack_from(end + "I", ifd0[0x8825][2], 0)[0], end, 1)
            if 2 in g and 4 in g:
                lat = _dms(_rationals(g[2], end), _ascii(g[1]) if 1 in g else "N")
                lon = _dms(_rationals(g[4], end), _ascii(g[3]) if 3 in g else "E")
                if lat is not None and lon is not None:
                    info["gps"] = (round(lat, 6), round(lon, 6))
            if 6 in g:
                alt = _rationals(g[6], end)
                if alt:
                    info["fields"]["GPS altitude (m)"] = round(alt[0], 1)
    except (struct.error, IndexError, ValueError):
        pass
    info["fields"] = {k: v for k, v in info["fields"].items() if v not in (None, "")}
    return info


def minimal_exif(orientation):
    """A tiny EXIF block holding only the orientation, so a cleaned photo is not shown sideways."""
    return (b"MM\0*\0\0\0\x08" + struct.pack(">H", 1) + struct.pack(">HHI", 0x0112, 3, 1)
            + struct.pack(">HH", orientation, 0) + b"\0\0\0\0")
