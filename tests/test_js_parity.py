"""The browser code (docs/scrub.js) must give exactly the same result as the Python package."""

import io
import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from PIL import Image

import photoscrub as P
from tests.test_scrub import jpeg, make_exif, picture

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Parity(unittest.TestCase):
    def test_same_output_as_python(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src, out = os.path.join(tmp, "in"), os.path.join(tmp, "out")
        os.makedirs(src)
        os.makedirs(out)
        files = {}
        for i, o in enumerate((1, 3, 6, 8)):
            files[f"j{i}.jpg"] = jpeg(make_exif(orientation=o), comment=b"note")
        files["plain.jpg"] = jpeg()
        b = io.BytesIO()
        picture(200, 120).save(b, "JPEG", progressive=True, exif=make_exif().tobytes())
        files["prog.jpg"] = b.getvalue()
        files["trailer.jpg"] = jpeg(make_exif()) + b"VIDEO" * 30
        b = io.BytesIO()
        picture().save(b, "PNG", pnginfo=None)
        files["a.png"] = b.getvalue()
        for name, kw in (("w1.webp", dict(exif=make_exif(orientation=1).tobytes(), xmp=b"<x/>")),
                         ("w2.webp", dict(exif=make_exif(orientation=6).tobytes())),
                         ("w3.webp", dict(lossless=True)), ("w4.webp", {})):
            b = io.BytesIO()
            picture().save(b, "WEBP", **kw)
            files[name] = b.getvalue()
        rnd = random.Random(3)
        base = jpeg(make_exif())
        for i in range(60):
            d = bytearray(base)
            for _ in range(rnd.randrange(1, 5)):
                d[rnd.randrange(len(d))] = rnd.randrange(256)
            if i % 3 == 0:
                d = d[:rnd.randrange(3, len(d))]
            files[f"fuzz{i:02d}.jpg"] = bytes(d)
        files["note.txt"] = b"hello"
        files["x.heic"] = b"\0\0\0\x18ftypheic" + b"\0" * 20
        for n, d in files.items():
            with open(os.path.join(src, n), "wb") as f:
                f.write(d)
        subprocess.run(["node", os.path.join(HERE, "js_clean.js"), src, out], check=True)
        with open(os.path.join(out, "report.json")) as f:
            reports = json.load(f)
        for name, data in files.items():
            rep = reports[name]
            try:
                py_out, py_rep = P.clean(data)
            except P.UnsupportedImage:
                self.assertIn("error", rep, name)
                continue
            self.assertNotIn("error", rep, name)
            with open(os.path.join(out, name), "rb") as f:
                self.assertEqual(f.read(), py_out, name)
            self.assertEqual(rep["removed"], py_rep.removed, name)
            self.assertEqual(rep["trailer"], py_rep.trailer, name)
            self.assertEqual(rep["gps"], list(py_rep.gps) if py_rep.gps else None, name)
            self.assertEqual(rep["fields"], py_rep.fields, name)
            self.assertEqual(rep["orientation"], py_rep.orientation, name)


if __name__ == "__main__":
    unittest.main()
