/* Photo Privacy Scrubber: the same logic as the Python package, for the browser.
   Removes location, camera serial numbers, dates, comments and thumbnails from JPEG, PNG and
   WebP images without re-compressing them. Nothing is uploaded: it all runs on your device. */
(function (root) {
  "use strict";

  var PNG_SIG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  var PNG_KEEP = ["IHDR", "PLTE", "IDAT", "IEND", "tRNS", "gAMA", "cHRM", "sRGB", "iCCP", "sBIT", "pHYs",
    "bKGD", "hIST", "sPLT", "acTL", "fcTL", "fdAT", "cICP", "mDCV", "cLLI"];
  var TYPE_SIZE = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8 };
  var IFD0_TAGS = { 0x010f: "Camera maker", 0x0110: "Camera model", 0x0131: "Software", 0x0132: "Date/time",
    0x013b: "Artist", 0x8298: "Copyright", 0x010e: "Description", 0x9c9f: "Author (Windows)" };
  var EXIF_TAGS = { 0x9003: "Date taken", 0xa431: "Camera serial number", 0xa434: "Lens model",
    0xa435: "Lens serial number", 0xa430: "Owner name", 0x9286: "User comment", 0xa420: "Unique image ID" };

  function UnsupportedImage(msg) { this.name = "UnsupportedImage"; this.message = msg; }
  UnsupportedImage.prototype = Object.create(Error.prototype);

  function str(b, s, e) { var o = ""; for (var i = s; i < e; i++) o += String.fromCharCode(b[i]); return o; }
  function startsWith(b, off, s) { return off + s.length <= b.length && str(b, off, off + s.length) === s; }
  function concat(parts) {
    var n = 0, i; for (i = 0; i < parts.length; i++) n += parts[i].length;
    var out = new Uint8Array(n), p = 0;
    for (i = 0; i < parts.length; i++) { out.set(parts[i], p); p += parts[i].length; }
    return out;
  }
  function u16be(b, o) { return (b[o] << 8) | b[o + 1]; }
  function u32be(b, o) { return ((b[o] * 16777216) + (b[o + 1] << 16) + (b[o + 2] << 8) + b[o + 3]); }
  function u32le(b, o) { return ((b[o + 3] * 16777216) + (b[o + 2] << 16) + (b[o + 1] << 8) + b[o]); }
  function be32(n) { return new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]); }
  function le32(n) { return new Uint8Array([n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255]); }

  function detect(d) {
    if (d.length >= 3 && d[0] === 0xff && d[1] === 0xd8 && d[2] === 0xff) return "jpeg";
    var ok = d.length >= 8; for (var i = 0; ok && i < 8; i++) if (d[i] !== PNG_SIG[i]) ok = false;
    if (ok) return "png";
    if (startsWith(d, 0, "RIFF") && startsWith(d, 8, "WEBP")) return "webp";
    if (startsWith(d, 4, "ftyp") && ["heic", "heix", "mif1", "avif", "heim", "msf1"].indexOf(str(d, 8, 12)) >= 0) return "heic";
    return null;
  }

  function Report(kind) {
    this.kind = kind; this.removed = []; this.gps = null; this.fields = {}; this.orientation = 1; this.trailer = 0;
  }
  Report.prototype.hasPrivateData = function () {
    return !!(this.gps || Object.keys(this.fields).length || this.removed.length || this.trailer);
  };
  function addOnce(list, v) { if (list.indexOf(v) < 0) list.push(v); }

  // ------------------------------------------------------------------ EXIF
  function readIfd(t, off, le, depth) {
    var out = {};
    if (off < 8 || off + 2 > t.length || depth > 3) return out;
    var rd16 = function (o) { return le ? (t[o] | (t[o + 1] << 8)) : u16be(t, o); };
    var rd32 = function (o) { return le ? u32le(t, o) : u32be(t, o); };
    var n = Math.min(rd16(off), 512);
    for (var i = 0; i < n; i++) {
      var p = off + 2 + 12 * i;
      if (p + 12 > t.length) break;
      var tag = rd16(p), typ = rd16(p + 2), cnt = rd32(p + 4), size = TYPE_SIZE[typ];
      if (!size || cnt > (1 << 20)) continue;
      var total = size * cnt, data;
      if (total <= 4) data = t.subarray(p + 8, p + 8 + total);
      else { var vo = rd32(p + 8); data = t.subarray(vo, vo + total); if (data.length < total) continue; }
      out[tag] = { typ: typ, cnt: cnt, data: data };
    }
    return out;
  }
  function ascii(v) {
    if (!v || v.typ !== 2) return null;
    var end = 0; while (end < v.data.length && v.data[end] !== 0) end++;
    return new TextDecoder("utf-8").decode(v.data.subarray(0, end)).trim();
  }
  function rationals(v, le) {
    var out = []; if (!v || (v.typ !== 5 && v.typ !== 10)) return out;
    var dv = new DataView(v.data.buffer, v.data.byteOffset, v.data.byteLength);
    for (var i = 0; i < v.cnt; i++) {
      var a = v.typ === 5 ? dv.getUint32(i * 8, le) : dv.getInt32(i * 8, le);
      var b = v.typ === 5 ? dv.getUint32(i * 8 + 4, le) : dv.getInt32(i * 8 + 4, le);
      out.push(b ? a / b : 0);
    }
    return out;
  }
  function dms(vals, ref) {
    if (vals.length < 3) return null;
    var deg = vals[0] + vals[1] / 60 + vals[2] / 3600;
    return (ref === "S" || ref === "W") ? -deg : deg;
  }
  function round6(x) { return Math.round(x * 1e6) / 1e6; }

  function parseExif(t) {
    var info = { orientation: 1, fields: {}, gps: null };
    if (t.length < 8 || !((t[0] === 0x49 && t[1] === 0x49) || (t[0] === 0x4d && t[1] === 0x4d))) return info;
    var le = t[0] === 0x49;
    var rd32 = function (b, o) { return le ? u32le(b, o) : u32be(b, o); };
    try {
      var ifd0 = readIfd(t, rd32(t, 4), le, 0), tag;
      for (tag in IFD0_TAGS) if (ifd0[tag] && ifd0[tag].typ === 2) info.fields[IFD0_TAGS[tag]] = ascii(ifd0[tag]);
      if (ifd0[0x0112] && ifd0[0x0112].typ === 3) {
        var d = ifd0[0x0112].data; info.orientation = le ? (d[0] | (d[1] << 8)) : u16be(d, 0);
      }
      if (ifd0[0x8769]) {
        var sub = readIfd(t, rd32(ifd0[0x8769].data, 0), le, 1);
        for (tag in EXIF_TAGS) if (sub[tag] && sub[tag].typ === 2) info.fields[EXIF_TAGS[tag]] = ascii(sub[tag]);
      }
      if (ifd0[0x8825]) {
        var g = readIfd(t, rd32(ifd0[0x8825].data, 0), le, 1);
        if (g[2] && g[4]) {
          var lat = dms(rationals(g[2], le), g[1] ? ascii(g[1]) : "N");
          var lon = dms(rationals(g[4], le), g[3] ? ascii(g[3]) : "E");
          if (lat !== null && lon !== null) info.gps = [round6(lat), round6(lon)];
        }
        if (g[6]) { var alt = rationals(g[6], le); if (alt.length) info.fields["GPS altitude (m)"] = Math.round(alt[0] * 10) / 10; }
      }
    } catch (e) { /* damaged EXIF: report what we have */ }
    var f = {}; Object.keys(info.fields).forEach(function (k) { var v = info.fields[k]; if (v !== null && v !== "") f[k] = v; });
    info.fields = f;
    return info;
  }
  function minimalExif(o) {
    return new Uint8Array([0x4d, 0x4d, 0, 0x2a, 0, 0, 0, 8, 0, 1, 0x01, 0x12, 0, 3, 0, 0, 0, 1, (o >> 8) & 255, o & 255, 0, 0, 0, 0, 0, 0]);
  }
  function mergeInfo(rep, info) {
    if (!rep.gps) rep.gps = info.gps;
    Object.keys(info.fields).forEach(function (k) { rep.fields[k] = info.fields[k]; });
  }

  // ------------------------------------------------------------------ JPEG
  function jpegSegments(d) {
    var segs = [], pos = 2, n = d.length;
    while (pos + 4 <= n) {
      if (d[pos] !== 0xff) throw new UnsupportedImage("damaged JPEG (marker expected)");
      var m = d[pos + 1];
      if (m === 0xff) { pos += 1; continue; }
      if (m === 0xd9) { segs.push({ m: "END", end: pos + 2 }); return segs; }
      if ((m >= 0xd0 && m <= 0xd7) || m === 0x01 || m === 0x00) { segs.push({ m: m, start: pos, end: pos + 2, p: pos + 2 }); pos += 2; continue; }
      var ln = u16be(d, pos + 2);
      if (ln < 2 || pos + 2 + ln > n) throw new UnsupportedImage("damaged JPEG (segment too long)");
      var end = pos + 2 + ln;
      segs.push({ m: m, start: pos, end: end, p: pos + 4 });
      pos = end;
      if (m === 0xda) {
        while (pos + 1 < n) {
          var j = d.indexOf(0xff, pos);
          if (j < 0 || j + 1 >= n) { pos = n; break; }
          var nx = d[j + 1];
          if (nx === 0 || (nx >= 0xd0 && nx <= 0xd7)) { pos = j + 2; continue; }
          pos = j; break;
        }
        segs.push({ m: "DATA", end: pos });
      }
    }
    segs.push({ m: "END", end: n });
    return segs;
  }

  function cleanJpeg(d, o) {
    var rep = new Report("jpeg"), parts = [new Uint8Array([0xff, 0xd8])], orient = 1, endPos = d.length, scanStart = 2;
    var segs = jpegSegments(d);
    for (var i = 0; i < segs.length; i++) {
      var s = segs[i];
      if (s.m === "END") {
        endPos = s.end;
        if (d[endPos - 2] === 0xff && d[endPos - 1] === 0xd9) parts.push(new Uint8Array([0xff, 0xd9]));
        break;
      }
      if (s.m === "DATA") { parts.push(d.subarray(scanStart, s.end)); continue; }
      var m = s.m, drop = null;
      if (m === 0xe1 && startsWith(d, s.p, "Exif\0\0")) {
        var info = parseExif(d.subarray(s.p + 6, s.end)); mergeInfo(rep, info); orient = info.orientation;
        drop = "EXIF (camera, date, location)";
      } else if (m === 0xe1 && (startsWith(d, s.p, "http://ns.adobe.com/xap/1.0/") || startsWith(d, s.p, "http://ns.adobe.com/xmp/extension/"))) {
        drop = "XMP (editing history, author)";
      } else if (m === 0xed) drop = "IPTC / Photoshop data (captions, names)";
      else if (m === 0xfe) drop = "JPEG comment";
      else if (m === 0xe2 && startsWith(d, s.p, "MPF\0")) drop = "multi-picture data";
      else if (m === 0xe2 && startsWith(d, s.p, "ICC_PROFILE")) drop = o.keepIcc ? null : "colour profile";
      else if (m === 0xe0 && startsWith(d, s.p, "JFXX\0")) drop = "embedded thumbnail";
      else if (m === 0xe0 && !startsWith(d, s.p, "JFIF\0")) drop = "application data (APP0)";
      else if (m === 0xee && !startsWith(d, s.p, "Adobe")) drop = "application data (APP14)";
      else if (typeof m === "number" && m >= 0xe1 && m <= 0xef && m !== 0xee) drop = "application data (APP" + (m - 0xe0) + ")";
      if (drop) { addOnce(rep.removed, drop); continue; }
      parts.push(d.subarray(s.start, s.end));
      if (m === 0xda) scanStart = s.end;
    }
    if (endPos < d.length) {
      rep.trailer = d.length - endPos;
      if (o.keepTrailer) { parts.push(d.subarray(endPos)); rep.trailer = 0; }
    }
    rep.orientation = orient;
    var out = concat(parts);
    if (o.keepOrientation && orient !== 0 && orient !== 1) {
      var block = concat([new Uint8Array([0x45, 0x78, 0x69, 0x66, 0, 0]), minimalExif(orient)]);
      var seg = concat([new Uint8Array([0xff, 0xe1, ((block.length + 2) >> 8) & 255, (block.length + 2) & 255]), block]);
      var at = 2;
      if (out[2] === 0xff && out[3] === 0xe0) at = 4 + u16be(out, 4);
      out = concat([out.subarray(0, at), seg, out.subarray(at)]);
    }
    return { data: out, report: rep };
  }

  // ------------------------------------------------------------------ PNG
  function cleanPng(d, o) {
    var rep = new Report("png"), parts = [d.subarray(0, 8)], pos = 8, end = 8;
    while (pos + 12 <= d.length) {
      var n = u32be(d, pos), typ = str(d, pos + 4, pos + 8);
      if (pos + 12 + n > d.length) throw new UnsupportedImage("damaged PNG (chunk too long)");
      var e = pos + 12 + n, payload = d.subarray(pos + 8, pos + 8 + n), name = null;
      end = e;
      if (typ === "eXIf") { var info = parseExif(payload); mergeInfo(rep, info); rep.orientation = info.orientation; name = "EXIF (camera, date, location)"; }
      else if (typ === "tEXt" || typ === "zTXt" || typ === "iTXt") {
        name = "text notes (author, software, prompts)";
        var k = 0; while (k < payload.length && payload[k] !== 0) k++;
        var key = str(payload, 0, Math.min(k, 40));
        if (key && !("PNG text: " + key in rep.fields)) rep.fields["PNG text: " + key] = "present";
      } else if (typ === "tIME") name = "modification time";
      else if (PNG_KEEP.indexOf(typ) < 0) name = "extra data (" + typ + ")";
      else if (typ === "iCCP" && !o.keepIcc) name = "colour profile";
      if (name) addOnce(rep.removed, name); else parts.push(d.subarray(pos, e));
      pos = e;
      if (typ === "IEND") break;
    }
    if (end < d.length) { rep.trailer = d.length - end; if (o.keepTrailer) { parts.push(d.subarray(end)); rep.trailer = 0; } }
    return { data: concat(parts), report: rep };
  }

  // ------------------------------------------------------------------ WebP
  function cleanWebp(d, o) {
    var rep = new Report("webp");
    if (d.length < 12) throw new UnsupportedImage("damaged WebP");
    var riffEnd = Math.min(d.length, 8 + u32le(d, 4)), pos = 12, chunks = [];
    while (pos + 8 <= riffEnd) {
      var typ = str(d, pos, pos + 4), n = u32le(d, pos + 4), e = pos + 8 + n + (n & 1);
      if (e > d.length + 1) throw new UnsupportedImage("damaged WebP (chunk too long)");
      chunks.push({ typ: typ, payload: new Uint8Array(d.subarray(pos + 8, pos + 8 + n)) });
      pos = e;
    }
    var kept = [], orient = 1;
    chunks.forEach(function (c) {
      if (c.typ === "EXIF") {
        var p = startsWith(c.payload, 0, "Exif\0\0") ? c.payload.subarray(6) : c.payload;
        var info = parseExif(p); mergeInfo(rep, info); orient = info.orientation; rep.removed.push("EXIF (camera, date, location)");
      } else if (c.typ === "XMP ") rep.removed.push("XMP (editing history, author)");
      else if (c.typ === "ICCP" && !o.keepIcc) rep.removed.push("colour profile");
      else kept.push(c);
    });
    rep.orientation = orient;
    var keepExif = o.keepOrientation && orient !== 0 && orient !== 1;
    if (keepExif) kept.push({ typ: "EXIF", payload: minimalExif(orient) });
    var body = [];
    kept.forEach(function (c) {
      if (c.typ === "VP8X" && c.payload.length >= 1) {
        c.payload[0] &= ~0x04 & 255;
        if (keepExif) c.payload[0] |= 0x08; else c.payload[0] &= ~0x08 & 255;
        if (!o.keepIcc) c.payload[0] &= ~0x20 & 255;
      }
      body.push(new Uint8Array([c.typ.charCodeAt(0), c.typ.charCodeAt(1), c.typ.charCodeAt(2), c.typ.charCodeAt(3)]));
      body.push(le32(c.payload.length), c.payload);
      if (c.payload.length & 1) body.push(new Uint8Array([0]));
    });
    var b = concat(body);
    var out = concat([new Uint8Array([0x52, 0x49, 0x46, 0x46]), le32(4 + b.length), new Uint8Array([0x57, 0x45, 0x42, 0x50]), b]);
    if (riffEnd < d.length) {
      if (o.keepTrailer) out = concat([out, d.subarray(riffEnd)]); else rep.trailer = d.length - riffEnd;
    }
    return { data: out, report: rep };
  }

  function clean(d, opts) {
    var o = { keepOrientation: true, keepIcc: true, keepTrailer: false };
    if (opts) Object.keys(opts).forEach(function (k) { o[k] = opts[k]; });
    var kind = detect(d);
    if (kind === "jpeg") return cleanJpeg(d, o);
    if (kind === "png") return cleanPng(d, o);
    if (kind === "webp") return cleanWebp(d, o);
    if (kind === "heic") throw new UnsupportedImage("HEIC/AVIF photos are not supported yet: convert to JPEG first (iPhone: Settings > Camera > Formats > Most Compatible)");
    throw new UnsupportedImage("not a JPEG, PNG or WebP image");
  }

  var api = { clean: clean, detect: detect, UnsupportedImage: UnsupportedImage };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PhotoScrub = api;
})(typeof self !== "undefined" ? self : this);
