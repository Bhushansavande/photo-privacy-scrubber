"""Remove hidden personal data (location, camera serial numbers, dates, thumbnails, comments)
from JPEG, PNG and WebP images WITHOUT re-compressing them: the picture itself stays
byte-for-byte identical, only the metadata around it is removed.

Pure Python, no dependencies.
"""

import struct

from . import exif as exifmod

PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT",
            b"pHYs", b"bKGD", b"hIST", b"sPLT", b"acTL", b"fcTL", b"fdAT", b"cICP", b"mDCV", b"cLLI"}


class UnsupportedImage(ValueError):
    pass


def detect(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == PNG_SIG:
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"avif", b"heim", b"msf1"):
        return "heic"
    return None


class Report:
    """What was found and what was removed."""

    def __init__(self, kind):
        self.kind = kind
        self.found = []          # human readable findings
        self.removed = []        # names of removed parts
        self.gps = None
        self.fields = {}
        self.orientation = 1
        self.trailer = 0         # bytes after the end of the image (some phones hide video here)

    @property
    def has_private_data(self):
        return bool(self.gps or self.fields or self.removed or self.trailer)


def _scan_segments(data):
    """Yield (marker, start, end, payload_start) for each JPEG segment up to the end of the image,
    then ('END', pos) with the position just after EOI."""
    pos = 2
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF:
            raise UnsupportedImage("damaged JPEG (marker expected)")
        m = data[pos + 1]
        if m == 0xFF:                       # fill byte
            pos += 1
            continue
        if m == 0xD9:
            yield ("END", pos + 2)
            return
        if 0xD0 <= m <= 0xD7 or m in (0x01, 0x00):
            yield (m, pos, pos + 2, pos + 2)
            pos += 2
            continue
        ln = struct.unpack_from(">H", data, pos + 2)[0]
        if ln < 2 or pos + 2 + ln > n:
            raise UnsupportedImage("damaged JPEG (segment too long)")
        end = pos + 2 + ln
        yield (m, pos, end, pos + 4)
        pos = end
        if m == 0xDA:                       # start of scan: entropy-coded data follows
            while pos + 1 < n:
                j = data.find(b"\xff", pos)
                if j < 0 or j + 1 >= n:
                    pos = n
                    break
                nxt = data[j + 1]
                if nxt == 0 or 0xD0 <= nxt <= 0xD7:
                    pos = j + 2
                    continue
                pos = j
                break
            yield ("DATA", None, pos, None)
    yield ("END", n)


def clean_jpeg(data, keep_orientation=True, keep_icc=True, keep_trailer=False):
    rep = Report("jpeg")
    out = bytearray(b"\xff\xd8")
    orient = 1
    end_pos = len(data)
    scan_start = 2
    for seg in _scan_segments(data):
        if seg[0] == "END":
            end_pos = seg[1]
            if data[end_pos - 2:end_pos] == b"\xff\xd9":
                out += b"\xff\xd9"
            break
        if seg[0] == "DATA":
            out += data[scan_start:seg[2]]
            continue
        m, start, end, pstart = seg
        payload = data[pstart:end]
        drop = None
        if m == 0xE1 and payload.startswith(b"Exif\0\0"):
            info = exifmod.parse(payload[6:])
            rep.gps = rep.gps or info["gps"]
            rep.fields.update(info["fields"])
            orient = info["orientation"]
            drop = "EXIF (camera, date, location)"
        elif m == 0xE1 and (payload.startswith(b"http://ns.adobe.com/xap/1.0/")
                            or payload.startswith(b"http://ns.adobe.com/xmp/extension/")):
            drop = "XMP (editing history, author)"
        elif m == 0xED:
            drop = "IPTC / Photoshop data (captions, names)"
        elif m == 0xFE:
            drop = "JPEG comment"
        elif m == 0xE2 and payload.startswith(b"MPF\0"):
            drop = "multi-picture data"
        elif m == 0xE2 and payload.startswith(b"ICC_PROFILE"):
            drop = None if keep_icc else "colour profile"
        elif m == 0xE0 and payload.startswith(b"JFXX\0"):
            drop = "embedded thumbnail"
        elif m == 0xE0 and not payload.startswith(b"JFIF\0"):
            drop = "application data (APP0)"
        elif m == 0xEE and not payload.startswith(b"Adobe"):
            drop = "application data (APP14)"
        elif 0xE1 <= m <= 0xEF and m != 0xEE:
            drop = "application data (APP%d)" % (m - 0xE0)
        if drop:
            if drop not in rep.removed:
                rep.removed.append(drop)
            continue
        out += data[start:end]
        if m == 0xDA:
            scan_start = end
    if end_pos < len(data):
        rep.trailer = len(data) - end_pos
        if keep_trailer:
            out += data[end_pos:]
            rep.trailer = 0
    rep.orientation = orient
    if keep_orientation and orient not in (0, 1):
        block = b"Exif\0\0" + exifmod.minimal_exif(orient)
        seg = b"\xff\xe1" + struct.pack(">H", len(block) + 2) + block
        # after SOI and an optional JFIF segment
        i = 2
        if out[2:4] == b"\xff\xe0":
            i = 4 + struct.unpack_from(">H", out, 4)[0]
        out[i:i] = seg
    return bytes(out), rep


def _png_chunks(data):
    pos = 8
    while pos + 12 <= len(data):
        n, typ = struct.unpack_from(">I4s", data, pos)
        if pos + 12 + n > len(data):
            raise UnsupportedImage("damaged PNG (chunk too long)")
        yield typ, pos, pos + 12 + n, data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if typ == b"IEND":
            break


def clean_png(data, keep_orientation=True, keep_icc=True, keep_trailer=False):
    rep = Report("png")
    out = bytearray(PNG_SIG)
    end = 8
    for typ, s, e, payload in _png_chunks(data):
        end = e
        if typ == b"eXIf":
            info = exifmod.parse(payload)
            rep.gps = rep.gps or info["gps"]
            rep.fields.update(info["fields"])
            rep.orientation = info["orientation"]
            name = "EXIF (camera, date, location)"
        elif typ in (b"tEXt", b"zTXt", b"iTXt"):
            name = "text notes (author, software, prompts)"
            key = payload.split(b"\0", 1)[0].decode("latin-1", "replace")
            if key:
                rep.fields.setdefault("PNG text: " + key[:40], "present")
        elif typ == b"tIME":
            name = "modification time"
        elif typ not in PNG_KEEP:
            name = "extra data (%s)" % typ.decode("latin-1", "replace")
        elif typ == b"iCCP" and not keep_icc:
            name = "colour profile"
        else:
            out += data[s:e]
            continue
        if name not in rep.removed:
            rep.removed.append(name)
    if end < len(data):
        rep.trailer = len(data) - end
        if keep_trailer:
            out += data[end:]
            rep.trailer = 0
    return bytes(out), rep


def clean_webp(data, keep_orientation=True, keep_icc=True, keep_trailer=False):
    rep = Report("webp")
    if len(data) < 12:
        raise UnsupportedImage("damaged WebP")
    riff_end = min(len(data), 8 + struct.unpack_from("<I", data, 4)[0])
    pos, chunks = 12, []
    while pos + 8 <= riff_end:
        typ, n = struct.unpack_from("<4sI", data, pos)
        e = pos + 8 + n + (n & 1)
        if e > len(data) + 1:
            raise UnsupportedImage("damaged WebP (chunk too long)")
        chunks.append((typ, bytearray(data[pos + 8:pos + 8 + n])))
        pos = e
    kept, orient = [], 1
    for typ, payload in chunks:
        if typ == b"EXIF":
            info = exifmod.parse(bytes(payload[6:] if payload.startswith(b"Exif\0\0") else payload))
            rep.gps = rep.gps or info["gps"]
            rep.fields.update(info["fields"])
            orient = info["orientation"]
            rep.removed.append("EXIF (camera, date, location)")
        elif typ == b"XMP ":
            rep.removed.append("XMP (editing history, author)")
        elif typ == b"ICCP" and not keep_icc:
            rep.removed.append("colour profile")
        else:
            kept.append((typ, payload))
    rep.orientation = orient
    keep_exif = keep_orientation and orient not in (0, 1)
    if keep_exif:
        kept.append((b"EXIF", bytearray(exifmod.minimal_exif(orient))))
    for typ, payload in kept:
        if typ == b"VP8X" and len(payload) >= 1:
            payload[0] &= ~0x04 & 0xFF            # no XMP
            if keep_exif:
                payload[0] |= 0x08
            else:
                payload[0] &= ~0x08 & 0xFF
            if not keep_icc:
                payload[0] &= ~0x20 & 0xFF
    body = bytearray()
    for typ, payload in kept:
        body += typ + struct.pack("<I", len(payload)) + bytes(payload) + (b"\0" if len(payload) & 1 else b"")
    out = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + bytes(body)
    if riff_end < len(data) and keep_trailer:
        out += data[riff_end:]
    elif riff_end < len(data):
        rep.trailer = len(data) - riff_end
    return out, rep


def clean(data, **opts):
    """Returns (clean_bytes, Report). Raises UnsupportedImage for other formats."""
    kind = detect(data)
    if kind == "jpeg":
        return clean_jpeg(data, **opts)
    if kind == "png":
        return clean_png(data, **opts)
    if kind == "webp":
        return clean_webp(data, **opts)
    if kind == "heic":
        raise UnsupportedImage("HEIC/AVIF photos are not supported yet: convert to JPEG first "
                               "(iPhone: Settings > Camera > Formats > Most Compatible)")
    raise UnsupportedImage("not a JPEG, PNG or WebP image")


def inspect(data):
    """What does this image reveal? Same as clean() but returns only the Report."""
    return clean(data)[1]
