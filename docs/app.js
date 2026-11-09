(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var results = []; // {name, blob, report}

  function opts() { return { keepOrientation: $("keepRot").checked, keepIcc: $("keepIcc").checked, keepTrailer: $("keepTrailer").checked }; }
  function cleanName(n) { var i = n.lastIndexOf("."); return i < 0 ? n + ".clean" : n.slice(0, i) + ".clean" + n.slice(i); }
  function mime(kind) { return { jpeg: "image/jpeg", png: "image/png", webp: "image/webp" }[kind]; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function save(blob, name) {
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  function render(item, file) {
    var box = el("div", "item"), img = el("img"), body = el("div", "body");
    if (item.blob) img.src = URL.createObjectURL(item.blob);
    img.alt = ""; box.appendChild(img); box.appendChild(body);
    body.appendChild(el("div", "name", file.name));
    if (item.error) { body.appendChild(el("div", "err", item.error)); }
    else {
      var r = item.report;
      if (!r.hasPrivateData()) body.appendChild(el("span", "badge ok", "Nothing private found"));
      else body.appendChild(el("span", "badge ok", "Cleaned: " + Math.max(0, file.size - item.blob.size).toLocaleString() + " bytes removed"));
      var ul = el("ul");
      if (r.gps) {
        var li = el("li"); li.appendChild(el("span", "badge warn", "Location was inside: " + r.gps[0] + ", " + r.gps[1]));
        ul.appendChild(li);
      }
      Object.keys(r.fields).forEach(function (k) { ul.appendChild(el("li", "", k + ": " + r.fields[k])); });
      if (r.trailer) ul.appendChild(el("li", "", r.trailer.toLocaleString() + " bytes hidden after the image were removed"));
      if (r.removed.length) ul.appendChild(el("li", "", "Removed: " + r.removed.join(", ")));
      if (ul.childNodes.length) body.appendChild(ul);
      var row = el("div", "row"), dl = el("button", "primary", "Download clean copy");
      dl.type = "button"; dl.onclick = function () { save(item.blob, item.name); }; row.appendChild(dl);
      if (navigator.canShare) {
        var f = new File([item.blob], item.name, { type: item.blob.type });
        if (navigator.canShare({ files: [f] })) {
          var sh = el("button", "", "Share"); sh.type = "button";
          sh.onclick = function () { navigator.share({ files: [f] }).catch(function () {}); };
          row.appendChild(sh);
        }
      }
      body.appendChild(row);
    }
    $("list").appendChild(box);
  }

  function handle(files) {
    results = []; $("list").textContent = "";
    var pending = Array.prototype.slice.call(files), done = 0;
    pending.forEach(function (file) {
      file.arrayBuffer().then(function (buf) {
        var item = { name: cleanName(file.name) };
        try {
          var r = PhotoScrub.clean(new Uint8Array(buf), opts());
          item.report = Object.assign(r.report, { hasPrivateData: r.report.hasPrivateData });
          item.blob = new Blob([r.data], { type: mime(r.report.kind) });
          results.push(item);
        } catch (e) { item.error = e.message || String(e); }
        render(item, file);
      }).catch(function () {
        render({ name: file.name, error: "Could not read this file" }, file);
      }).then(function () {
        done++;
        if (done === pending.length) {
          $("bar").hidden = !results.length;
          var located = results.filter(function (r) { return r.report.gps; }).length;
          $("summary").textContent = results.length + " cleaned" + (located ? ", " + located + " had a location" : "");
        }
      });
    });
  }

  // minimal ZIP writer (stored, no compression)
  var crcTable = (function () { var t = [], c, n, k; for (n = 0; n < 256; n++) { c = n; for (k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(b) { var c = 0xffffffff; for (var i = 0; i < b.length; i++) c = crcTable[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
  function zip(files) {
    var parts = [], central = [], offset = 0, enc = new TextEncoder();
    function w16(v) { return new Uint8Array([v & 255, (v >> 8) & 255]); }
    function w32(v) { return new Uint8Array([v & 255, (v >>> 8) & 255, (v >>> 16) & 255, (v >>> 24) & 255]); }
    function cat(a) { var n = 0, i; a.forEach(function (x) { n += x.length; }); var o = new Uint8Array(n), p = 0; a.forEach(function (x) { o.set(x, p); p += x.length; }); return o; }
    files.forEach(function (f) {
      var name = enc.encode(f.name), crc = crc32(f.data);
      var local = cat([w32(0x04034b50), w16(20), w16(0x0800), w16(0), w16(0), w16(0x21), w32(crc), w32(f.data.length), w32(f.data.length), w16(name.length), w16(0), name, f.data]);
      central.push(cat([w32(0x02014b50), w16(20), w16(20), w16(0x0800), w16(0), w16(0), w16(0x21), w32(crc), w32(f.data.length), w32(f.data.length), w16(name.length), w16(0), w16(0), w16(0), w16(0), w32(0), w32(offset), name]));
      parts.push(local); offset += local.length;
    });
    var cd = cat(central);
    return new Blob([cat(parts), cd, cat([w32(0x06054b50), w16(0), w16(0), w16(files.length), w16(files.length), w32(cd.length), w32(offset), w16(0)])], { type: "application/zip" });
  }
  function uniqueNames(items) {
    var seen = {};
    return items.map(function (it) {
      var n = it.name, i = 1; while (seen[n]) { var d = it.name.lastIndexOf("."); n = it.name.slice(0, d) + "-" + (i++) + it.name.slice(d); }
      seen[n] = 1; return { name: n, item: it };
    });
  }
  $("all").onclick = function () {
    var named = uniqueNames(results), out = [], left = named.length;
    named.forEach(function (n) {
      n.item.blob.arrayBuffer().then(function (b) {
        out.push({ name: n.name, data: new Uint8Array(b) });
        if (--left === 0) save(zip(out), "clean-photos.zip");
      });
    });
  };

  $("file").addEventListener("change", function (e) { if (e.target.files.length) handle(e.target.files); });
  ["dragover", "dragenter"].forEach(function (t) { $("drop").addEventListener(t, function (e) { e.preventDefault(); $("drop").classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (t) { $("drop").addEventListener(t, function (e) { e.preventDefault(); $("drop").classList.remove("over"); }); });
  $("drop").addEventListener("drop", function (e) { if (e.dataTransfer.files.length) handle(e.dataTransfer.files); });
})();
