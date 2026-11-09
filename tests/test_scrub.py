import io
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from PIL import Image

import photoscrub as P
from photoscrub import cli


def make_exif(orientation=1, gps=True):
    ex = Image.Exif()
    ex[0x010F] = "Acme"
    ex[0x0110] = "PhoneX"
    ex[0x0132] = "2026:01:02 03:04:05"
    ex[0x0112] = orientation
    ex.get_ifd(0x8769)[0xA431] = "SN123456"
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = "N", (21.0, 0.0, 0.0), "W", (75.0, 30.0, 0.0)
    return ex


def picture(w=96, h=64, seed=1):
    r = random.Random(seed)
    im = Image.new("RGB", (w, h))
    im.putdata([(r.randrange(256), (x * 3) % 256, 90) for x in range(w * h)])
    return im


def jpeg(exif=None, **kw):
    b = io.BytesIO()
    if exif:
        kw["exif"] = exif.tobytes()
    picture().save(b, "JPEG", **kw)
    return b.getvalue()


def pixels(data):
    return Image.open(io.BytesIO(data)).convert("RGB").tobytes()


class Jpeg(unittest.TestCase):
    def test_removes_exif_and_reports_location(self):
        d = jpeg(make_exif(), comment=b"secret")
        out, rep = P.clean(d)
        self.assertEqual(rep.gps, (21.0, -75.5))
        self.assertEqual(rep.fields["Camera model"], "PhoneX")
        self.assertEqual(rep.fields["Camera serial number"], "SN123456")
        self.assertIn("JPEG comment", rep.removed)
        self.assertNotIn(b"PhoneX", out)
        self.assertNotIn(b"secret", out)
        self.assertNotIn(b"SN123456", out)
        self.assertEqual(len(P.inspect(out).fields), 0)
        self.assertIsNone(P.inspect(out).gps)

    def test_picture_is_unchanged(self):
        d = jpeg(make_exif(), quality=77)
        out, _ = P.clean(d)
        self.assertEqual(pixels(out), pixels(d))

    def test_orientation_kept_by_default_and_removable(self):
        d = jpeg(make_exif(orientation=6))
        out, _ = P.clean(d)
        ex = Image.open(io.BytesIO(out)).getexif()
        self.assertEqual(ex.get(0x0112), 6)
        self.assertIsNone(ex.get(0x010F))
        self.assertEqual(len(ex), 1)
        out2, _ = P.clean(d, keep_orientation=False)
        self.assertEqual(len(Image.open(io.BytesIO(out2)).getexif()), 0)

    def test_progressive_jpeg(self):
        b = io.BytesIO()
        picture(200, 150).save(b, "JPEG", progressive=True, exif=make_exif().tobytes())
        out, rep = P.clean(b.getvalue())
        self.assertEqual(pixels(out), pixels(b.getvalue()))
        self.assertTrue(rep.gps)

    def test_xmp_iptc_and_trailer(self):
        d = jpeg()
        xmp = b"http://ns.adobe.com/xap/1.0/\0<x:xmpmeta>author Jane</x:xmpmeta>"
        iptc = b"Photoshop 3.0\0" + b"8BIM caption John"
        segs = (b"\xff\xe1" + struct.pack(">H", len(xmp) + 2) + xmp
                + b"\xff\xed" + struct.pack(">H", len(iptc) + 2) + iptc)
        d2 = d[:2] + segs + d[2:] + b"MOTIONVIDEO" * 50
        out, rep = P.clean(d2)
        self.assertNotIn(b"Jane", out)
        self.assertNotIn(b"John", out)
        self.assertNotIn(b"MOTIONVIDEO", out)
        self.assertEqual(rep.trailer, 550)
        self.assertEqual(pixels(out), pixels(d))
        out2, _ = P.clean(d2, keep_trailer=True)
        self.assertIn(b"MOTIONVIDEO", out2)

    def test_icc_profile_kept(self):
        b = io.BytesIO()
        picture().save(b, "JPEG", icc_profile=b"\0" * 20 + b"fake-profile-data" * 5)
        out, _ = P.clean(b.getvalue())
        self.assertIn(b"ICC_PROFILE", out)
        out2, rep = P.clean(b.getvalue(), keep_icc=False)
        self.assertNotIn(b"ICC_PROFILE", out2)

    def test_clean_is_idempotent(self):
        out, _ = P.clean(jpeg(make_exif(orientation=3)))
        out2, rep = P.clean(out)
        self.assertEqual(out, out2)
        self.assertFalse(rep.gps)

    def test_garbage_never_crashes(self):
        base = jpeg(make_exif())
        rnd = random.Random(7)
        for _ in range(400):
            d = bytearray(base)
            for _ in range(rnd.randrange(1, 6)):
                d[rnd.randrange(len(d))] = rnd.randrange(256)
            if rnd.random() < 0.4:
                d = d[:rnd.randrange(3, len(d))]
            try:
                P.clean(bytes(d))
            except P.UnsupportedImage:
                pass


class Png(unittest.TestCase):
    def png(self, extra):
        b = io.BytesIO()
        picture().save(b, "PNG")
        d = b.getvalue()
        i = d.index(b"IDAT") - 4

        def chunk(t, p):
            return struct.pack(">I", len(p)) + t + p + struct.pack(">I", zlib.crc32(t + p) & 0xFFFFFFFF)
        return d[:i] + b"".join(chunk(t, p) for t, p in extra) + d[i:]

    def test_text_exif_time_removed(self):
        ex = make_exif().tobytes()[6:]
        d = self.png([(b"tEXt", b"Author\0Jane Doe"), (b"tIME", b"\x07\xea\x01\x02\x03\x04\x05"),
                      (b"eXIf", ex), (b"prVt", b"private stuff")])
        out, rep = P.clean(d)
        for needle in (b"Jane", b"private stuff", b"PhoneX"):
            self.assertNotIn(needle, out)
        self.assertEqual(rep.gps, (21.0, -75.5))
        self.assertEqual(pixels(out), pixels(d))
        Image.open(io.BytesIO(out)).load()

    def test_transparency_and_palette_kept(self):
        b = io.BytesIO()
        Image.new("RGBA", (10, 10), (1, 2, 3, 128)).save(b, "PNG")
        out, _ = P.clean(b.getvalue())
        self.assertEqual(Image.open(io.BytesIO(out)).convert("RGBA").tobytes(),
                         Image.open(io.BytesIO(b.getvalue())).convert("RGBA").tobytes())


class Webp(unittest.TestCase):
    def test_exif_and_xmp_removed(self):
        b = io.BytesIO()
        picture().save(b, "WEBP", exif=make_exif(orientation=1).tobytes(), xmp=b"<x>author Jane</x>", lossless=True)
        d = b.getvalue()
        out, rep = P.clean(d)
        self.assertNotIn(b"Jane", out)
        self.assertNotIn(b"PhoneX", out)
        self.assertEqual(rep.gps, (21.0, -75.5))
        self.assertEqual(pixels(out), pixels(d))
        self.assertEqual(len(Image.open(io.BytesIO(out)).getexif()), 0)

    def test_orientation_kept(self):
        b = io.BytesIO()
        picture().save(b, "WEBP", exif=make_exif(orientation=8).tobytes())
        out, _ = P.clean(b.getvalue())
        self.assertEqual(Image.open(io.BytesIO(out)).getexif().get(0x0112), 8)

    def test_plain_webp_unchanged_picture(self):
        b = io.BytesIO()
        picture().save(b, "WEBP")
        out, rep = P.clean(b.getvalue())
        self.assertEqual(pixels(out), pixels(b.getvalue()))
        self.assertFalse(rep.has_private_data)


class Other(unittest.TestCase):
    def test_heic_message(self):
        with self.assertRaises(P.UnsupportedImage) as cm:
            P.clean(b"\0\0\0\x18ftypheic" + b"\0" * 20)
        self.assertIn("convert to JPEG", str(cm.exception))

    def test_not_an_image(self):
        with self.assertRaises(P.UnsupportedImage):
            P.clean(b"hello world")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "a.jpg")
        with open(self.src, "wb") as f:
            f.write(jpeg(make_exif()))

    @staticmethod
    def read(path):
        with open(path, "rb") as f:
            return f.read()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "photoscrub", *args], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_inspect_changes_nothing_and_shows_location(self):
        before = self.read(self.src)
        r = self.run_cli("inspect", self.src)
        self.assertEqual(r.returncode, 0)
        self.assertIn("LOCATION: 21.0, -75.5", r.stdout)
        self.assertEqual(self.read(self.src), before)

    def test_clean_writes_copy_next_to_original(self):
        before = self.read(self.src)
        r = self.run_cli("clean", self.src)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(self.src), before)
        out = os.path.join(self.tmp, "a.clean.jpg")
        self.assertTrue(os.path.exists(out))
        self.assertIsNone(P.inspect(self.read(out)).gps)

    def test_clean_to_folder_and_in_place(self):
        outdir = os.path.join(self.tmp, "out")
        self.run_cli("clean", self.src, "-o", outdir)
        self.assertTrue(os.path.exists(os.path.join(outdir, "a.clean.jpg")))
        self.run_cli("clean", self.src, "--in-place")
        self.assertIsNone(P.inspect(self.read(self.src)).gps)

    def test_folder_recursive_and_skips_other_files(self):
        sub = os.path.join(self.tmp, "sub")
        os.makedirs(sub)
        shutil.copy(self.src, os.path.join(sub, "b.jpg"))
        with open(os.path.join(sub, "note.txt"), "w") as f:
            f.write("x")
        r = self.run_cli("inspect", self.tmp, "-r")
        self.assertIn("2 image(s) processed", r.stdout)


if __name__ == "__main__":
    unittest.main()
