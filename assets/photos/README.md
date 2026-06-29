# Manager headshots

Square, face-centred avatars used by the offseason site (rookie lottery + draft
order) in `league_management/generate_offseason_pages.py`. Files are named by
**Sleeper handle**: `<handle>.png`.

## Source & regeneration

- `source/composite-headshots.png` — the league composite photo all avatars are cropped from.
- `crop_headshots.py` — rotates the composite upright, runs OpenCV face detection, and
  writes one face-centred `<handle>.png` per manager. Re-run only if you want to re-crop
  or add people:

  ```sh
  uv run --with opencv-python-headless --with numpy --with pillow \
      python assets/photos/crop_headshots.py
  ```

The committed PNGs are the output of this script, so it's idempotent.

## Handle → person mapping

| Handle | Person | Notes |
| --- | --- | --- |
| `zachmassey` | Zachary B. Massey | lottery |
| `DannyN` | Daniel G. Niez | lottery |
| `jpersily` | Jesse B. Persily | lottery |
| `jaw7475` | Jake A. Weinberg | lottery |
| `JoshWasserman` | Joshua M. Wasserman | lottery |
| `ashanes` | Andrew J. Shanes | |
| `zachjd5` | Zachary J. Diamond | |
| `Friedo` | Zachary S. Friedman | |
| `skippo` | Matthew H. Epstein | |
| `Gohrdo` | Joshua C. Gordon **+** Andrew M. Bronstein | two-person team (combined avatar) |
| `spencerrubin7` | Spencer G. Rubin | traded-pick original owner |
| `dbleykhman` | Daniel A. Bleykhman | traded-pick original owner |

To add a manager: drop their face into the composite (or a new source), add a
`handle -> (row, centre-x)` entry in `crop_headshots.py`, and re-run.
