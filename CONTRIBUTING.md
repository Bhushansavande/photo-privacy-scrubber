# Contributing

1. `pip install Pillow` (tests only) and install Node.js (for the browser parity test).
2. `python -m unittest discover -s tests -t .`
3. Any change to the cleaning rules must be made in **both** `photoscrub/core.py` and `docs/scrub.js`. `tests/test_js_parity.py` fails if they disagree.
4. Add a test with a real file that shows the bug.

Code, comments and messages are in English.
