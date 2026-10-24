"""Build fitness-coach/assets/foods.tsv.gz from USDA FoodData Central downloads.

Not part of the Skill: run it once when the USDA data changes.

    python tools/build_foods.py <sr_legacy_csv_dir> <surveyDownload.json> fitness-coach/assets/foods.tsv.gz

Sources (public domain, https://fdc.nal.usda.gov/download-datasets/):
  SR Legacy CSV  FoodData_Central_sr_legacy_food_csv_2018-04.zip
  FNDDS JSON     FoodData_Central_survey_food_json_2024-10-31.zip
"""

import csv
import gzip
import json
import sys
from pathlib import Path

# USDA nutrient ids -> output columns
NUTRIENTS = {1008: "kcal", 1003: "protein", 1005: "carbs", 1004: "fat", 1079: "fiber", 2000: "sugar", 1093: "sodium"}
COLUMNS = ["id", "src", "name", "kcal", "protein", "carbs", "fat", "fiber", "sugar", "sodium", "portions"]
MAX_PORTIONS = 4


def num(x):
    return f"{float(x):.4g}"


def portion_text(text, grams):
    text = " ".join(text.replace("|", "/").replace("\t", " ").split())
    if not text or grams <= 0 or text.startswith("Guideline"):
        return None
    return f"{text}={grams:g}"


def sr_legacy(folder: Path):
    units = {r["id"]: r["name"] for r in csv.DictReader(open(folder / "measure_unit.csv", encoding="utf-8"))}
    foods = {r["fdc_id"]: {"id": r["fdc_id"], "src": "sr", "name": r["description"]}
             for r in csv.DictReader(open(folder / "food.csv", encoding="utf-8"))}
    for r in csv.DictReader(open(folder / "food_nutrient.csv", encoding="utf-8")):
        col = NUTRIENTS.get(int(r["nutrient_id"]))
        if col and r["fdc_id"] in foods:
            foods[r["fdc_id"]][col] = num(r["amount"])
    portions = {}
    for r in csv.DictReader(open(folder / "food_portion.csv", encoding="utf-8")):
        unit = units.get(r["measure_unit_id"], "")
        unit = "" if unit == "undetermined" else unit
        words = " ".join(w for w in (num(r["amount"] or 1), unit, r["modifier"], r["portion_description"]) if w)
        p = portion_text(words, float(r["gram_weight"] or 0))
        if p:
            portions.setdefault(r["fdc_id"], []).append(p)
    for fid, food in foods.items():
        food["portions"] = "|".join(portions.get(fid, [])[:MAX_PORTIONS])
    return foods.values()


def fndds(path: Path):
    for f in json.load(open(path, encoding="utf-8"))["SurveyFoods"]:
        if not f["foodNutrients"]:
            continue
        food = {"id": str(f["fdcId"]), "src": "fndds", "name": f["description"]}
        for n in f["foodNutrients"]:
            col = NUTRIENTS.get(n["nutrient"]["id"])
            if col and "amount" in n:
                food[col] = num(n["amount"])
        ps = sorted(f["foodPortions"], key=lambda p: p.get("sequenceNumber", 99))
        ps = [portion_text(p["portionDescription"], p["gramWeight"]) for p in ps
              if p["portionDescription"] != "Quantity not specified"]
        food["portions"] = "|".join([p for p in ps if p][:MAX_PORTIONS])
        yield food


def main():
    sr_dir, survey_json, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rows = [f for f in [*fndds(survey_json), *sr_legacy(sr_dir)] if "kcal" in f]
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for f in rows:
            fh.write("\t".join(f.get(c, "") for c in COLUMNS) + "\n")
    print(f"{len(rows)} foods -> {out} ({out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
