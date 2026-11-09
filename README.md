# Photo Privacy Scrubber

**Remove location, camera serial numbers and other hidden data from your photos before you share them.**
Free, open source (MIT), works offline. The picture is **not re-compressed**: pixels stay byte-for-byte identical, only the hidden data around them is removed.

**Try it in your browser (nothing is uploaded): https://bhushansavande.github.io/photo-privacy-scrubber/**

## Why

A photo from your phone usually contains the **GPS position** where it was taken (often your home), the **date and time**, the **phone model**, sometimes a **serial number**, an **embedded thumbnail** of the original, and the **editing history**. Messengers strip some of it, e-mail, forums, marketplaces and cloud links often do not.

## Three ways to use it

| | |
|---|---|
| **Web page** | Open the link above, choose photos, download clean copies (or a zip). Works on phones. Runs 100% on your device; the page has a Content-Security-Policy that blocks all network requests. |
| **Command line** | `pip install git+https://github.com/Bhushansavande/photo-privacy-scrubber.git` then `photoscrub clean photos/ -r -o clean/` |
| **Python library** | `import photoscrub; data, report = photoscrub.clean(open("a.jpg","rb").read())` |

No dependencies (pure Python 3.9+).

## Command line

```
photoscrub inspect photo.jpg            # show what the photo reveals, change nothing
photoscrub clean photo.jpg              # writes photo.clean.jpg next to it
photoscrub clean DCIM/ -r -o clean/     # a whole folder, into another folder
photoscrub clean photo.jpg --in-place   # replace the original (cannot be undone)
```

Example output:

```
IMG_2041.jpg
  LOCATION: 21.0, -75.5  (https://www.openstreetmap.org/?mlat=21.0&mlon=-75.5)
  Camera maker: Acme
  Camera model: PhoneX
  Date/time: 2026:01:02 03:04:05
  Camera serial number: SN123456
  Contains: EXIF (camera, date, location), JPEG comment
  -> clean/IMG_2041.clean.jpg  (224 bytes removed)
```

Originals are never touched unless you pass `--in-place`. Options: `--strip-orientation`, `--strip-icc`, `--keep-trailer`.

## What is removed

| Format | Removed | Kept |
|---|---|---|
| JPEG | EXIF (GPS, date, camera, serials, thumbnail), XMP, IPTC/Photoshop, comments, multi-picture data, other application data, data hidden after the image end | the picture, colour profile (ICC), rotation flag |
| PNG | eXIf, text notes (author, software, AI prompts), modification time, unknown extra chunks | the picture, transparency, palette, gamma, colour profile, animation (APNG) |
| WebP | EXIF, XMP | the picture, transparency, animation, colour profile, rotation flag |

The **rotation flag** is kept as a tiny EXIF block holding only the orientation, so a portrait photo does not suddenly turn sideways. Use `--strip-orientation` to drop it.

## Honest limits

- **HEIC/AVIF** (iPhone default) is not supported yet. Convert to JPEG first (iPhone: Settings > Camera > Formats > Most Compatible). The tool tells you instead of failing silently.
- **Videos** are not handled.
- Metadata is only part of what identifies a photo. Faces, street signs, shop names and reflections stay in the picture. Removing metadata does not make a photo anonymous.
- Other embedded tracking (for example invisible watermarks inside the pixels) is not detected.

## How it is tested

- Cleaned photos are decoded and compared **pixel for pixel** with the originals.
- The browser version (`docs/scrub.js`) and the Python version must produce **byte-identical** output on a set of photos, including 60 randomly corrupted JPEGs (`tests/test_js_parity.py`).
- Corrupted and truncated files never crash the tool.
- A real browser test uploads photos and checks the downloaded zip.

```
python -m unittest discover -s tests -t .      # needs Pillow and node
```

## Contributing

Issues and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Found a case where private data survives? Please open an issue (or see [SECURITY.md](SECURITY.md) if it is sensitive).

## License

MIT
