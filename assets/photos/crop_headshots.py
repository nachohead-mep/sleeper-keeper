#!/usr/bin/env python3
"""Crop manager headshots from the league composite photo.

Source: ``source/composite-headshots.png`` (a phone photo of a printed yearbook
composite, portrait/rotated). This script rotates it upright, runs OpenCV face
detection to locate each head precisely, and writes one square, face-centred
``<handle>.png`` avatar per manager into this directory. ``Gohrdo`` is a two-person
team, so it gets a side-by-side composite of both faces.

These avatars are used by the offseason site (rookie lottery + draft order) via
``league_management/generate_offseason_pages.py``. The PNGs are committed, so you
only need to re-run this if you want to re-crop (different size, new people, etc.).

Run it (OpenCV is not a project dependency, so pull it in ephemerally):

    uv run --with opencv-python-headless --with numpy --with pillow \
        python assets/photos/crop_headshots.py

handle -> person mapping (row + approximate face-centre x in the upright 2000px-wide
image; detection snaps to the nearest real face, so these only need to be close):

    Lottery entrants (bottom row of the composite):
      zachmassey     Zachary B. Massey      bot  127
      DannyN         Daniel G. Niez         bot  489
      jpersily       Jesse B. Persily       bot  663
      jaw7475        Jake A. Weinberg       bot  1728
      JoshWasserman  Joshua M. Wasserman    bot  1548
    Other current managers:
      ashanes        Andrew J. Shanes       bot  1203
      zachjd5        Zachary J. Diamond     top  1376
      Friedo         Zachary S. Friedman    top  1750
      skippo         Matthew H. Epstein     top  1564
      Gohrdo         Joshua C. Gordon       top  1939   (+ Andrew M. Bronstein, top 1196)
    Traded-pick original owners:
      spencerrubin7  Spencer G. Rubin       bot  1016
      dbleykhman     Daniel A. Bleykhman    top  1037
"""
from __future__ import annotations

import os

import cv2
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "source", "composite-headshots.png")
SIZE = 180  # output avatar is SIZE x SIZE

# handle -> (row, approximate face-centre x in the upright image)
SINGLES = {
    "zachmassey":    ("bot", 127),
    "DannyN":        ("bot", 489),
    "jpersily":      ("bot", 663),
    "jaw7475":       ("bot", 1728),
    "JoshWasserman": ("bot", 1548),
    "ashanes":       ("bot", 1203),
    "zachjd5":       ("top", 1376),
    "Friedo":        ("top", 1750),
    "skippo":        ("top", 1564),
    "spencerrubin7": ("bot", 1016),
    "dbleykhman":    ("top", 1037),
}
# Two-person team: Gordon + Bronstein, side by side.
COMBO = {"Gohrdo": [("top", 1939), ("top", 1196)]}


def _load_upright():
    im = Image.open(SRC).convert("RGB")
    # The composite is stored rotated 90deg (names run vertically); make it upright.
    if im.height > im.width:
        im = im.rotate(-90, expand=True)
    return im


def _detect_faces(pil_img):
    import numpy as np
    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    dets = cascade.detectMultiScale(gray, scaleFactor=1.03, minNeighbors=4,
                                    minSize=(70, 70), maxSize=(160, 160))
    return [tuple(map(int, f)) for f in dets]


def _face_square(src, faces, row, cx):
    """Square crop centred on the detected face nearest (row, cx)."""
    mid = src.height // 2
    in_row = (lambda yc: yc < mid) if row == "top" else (lambda yc: yc >= mid)
    cand = [f for f in faces if in_row(f[1] + f[3] // 2)]
    x, y, w, h = min(cand, key=lambda f: abs((f[0] + f[2] // 2) - cx))
    fcx, fcy = x + w / 2, (y + h / 2) - 0.10 * h  # shift up slightly to include hair
    side = 2.0 * h
    box = (int(max(0, fcx - side / 2)), int(max(0, fcy - side / 2)),
           int(min(src.width, fcx + side / 2)), int(min(src.height, fcy + side / 2)))
    return src.crop(box).resize((SIZE, SIZE))


def main():
    src = _load_upright()
    faces = _detect_faces(src)
    print(f"upright {src.size}, {len(faces)} faces detected")

    for handle, (row, cx) in SINGLES.items():
        _face_square(src, faces, row, cx).save(os.path.join(HERE, f"{handle}.png"))
        print(f"  wrote {handle}.png")

    for handle, members in COMBO.items():
        combo = Image.new("RGB", (SIZE, SIZE))
        for i, (row, cx) in enumerate(members):
            full = _face_square(src, faces, row, cx)
            half = full.crop((SIZE // 4, 0, SIZE // 4 + SIZE // 2, SIZE))  # centre strip
            combo.paste(half, (i * SIZE // 2, 0))
        combo.save(os.path.join(HERE, f"{handle}.png"))
        print(f"  wrote {handle}.png (combined {len(members)} faces)")


if __name__ == "__main__":
    main()
