"""Build fitness-coach/assets/exercises.json.gz from free-exercise-db.

Not part of the Skill: run it once when the exercise data changes.

    python tools/build_exercises.py <exercises.json> fitness-coach/assets/exercises.json.gz

Source (public domain, The Unlicense): https://github.com/yuhonas/free-exercise-db, dist/exercises.json
"""

import gzip
import json
import sys
from pathlib import Path

KEEP = ["id", "name", "level", "equipment", "category", "force", "mechanic",
        "primaryMuscles", "secondaryMuscles", "instructions"]


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for ex in json.load(open(src, encoding="utf-8")):
        row = {k: ex.get(k) for k in KEEP}
        row["image"] = ex["images"][0] if ex.get("images") else None
        rows.append(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(rows)} exercises -> {out} ({out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
