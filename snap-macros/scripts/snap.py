#!/usr/bin/env python3
"""snap-macros: food lookup, barcode lookup and a daily macro log.

Standard library only. Barcode *images* also need zxing-cpp and Pillow (see SKILL.md, Setup);
without them, read the digits under the barcode and pass them to `barcode`.

Commands (dates are the student's local date, YYYY-MM-DD):
  search "<food>" [--limit 6]           USDA foods matching the name, per 100 g, with common portions
  product "<brand and name>" [--limit 3]  Packaged products by name (Open Food Facts search)
  barcode <digits> | --image <path> [--log --date D [--amount 2srv|50]]   Packaged product from Open Food Facts
  log --date D --meal "<name>" (--food ID=G | --product CODE=G | --product CODE=Nsrv | --custom "...")...
  undo --date D                         Remove the last entry of that day
  today --date D                        That day's entries and totals vs goals
  week --date D                         The 7 days ending on D
  goals [--kcal N --protein N ...] | goals --calc --sex ... --age ... --weight-lb ... --height-in ...

Exit codes: 0 ok, 2 bad input or not found, 3 barcode decoder not installed, 4 network error.
"""

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
FOODS_FILE = SKILL_DIR / "assets" / "foods.tsv.gz"
SAMPLE_PRODUCT = SKILL_DIR / "assets" / "sample_product.json"
VENV = Path.home() / ".local" / "share" / "venvs" / "snap-macros"
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "product_name,brands,quantity,serving_size,serving_quantity,nutriments"
OFF_SEARCH_URL = "https://search.openfoodfacts.org/search"
USER_AGENT = "snap-macros/1.0 (https://github.com/pizzalover125/snap-macros)"
KEYS = ["kcal", "protein", "carbs", "fat", "fiber", "sugar", "sodium"]
LABELS = {"protein": "P", "carbs": "C", "fat": "F"}


class Problem(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


# ---------- state ----------

def state_dir(sample):
    base = Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "snap-macros")
    return base / "sample" if sample else base


def load_state(sample):
    path = state_dir(sample) / "log.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"goals": {}, "days": {}, "products": {}}


def save_state(state, sample):
    folder = state_dir(sample)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, folder / "log.json")


# ---------- formatting ----------

def fmt_g(x):
    return f"{x:.0f}" if x >= 10 else f"{x:.1f}".rstrip("0").rstrip(".")


def fmt_totals(t):
    line = f"{t['kcal']:.0f} kcal · P {fmt_g(t['protein'])}g · C {fmt_g(t['carbs'])}g · F {fmt_g(t['fat'])}g"
    return line + f" · fiber {fmt_g(t['fiber'])}g · sugar {fmt_g(t['sugar'])}g · sodium {t['sodium']:.0f}mg"


def fmt_vs_goals(t, goals):
    if not goals:
        return f"Day so far: {fmt_totals(t)}\n(no daily goals set)"
    parts = []
    for k in ["kcal", "protein", "carbs", "fat", "fiber"]:
        if k in goals:
            unit = " kcal" if k == "kcal" else "g"
            name = "" if k == "kcal" else f" {k}"
            left = goals[k] - t[k]
            parts.append(f"{t[k]:.0f}/{goals[k]:.0f}{unit}{name} ({'%.0f left' % left if left >= 0 else '%.0f over' % -left})")
    return "Day so far: " + "; ".join(parts)


def add(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in KEYS}


def scale(per100, grams):
    return {k: (per100.get(k) or 0) * grams / 100 for k in KEYS}


# ---------- USDA foods ----------

def stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("oes"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


STOPWORDS = {"and", "or", "with", "without", "in", "of", "nf", "ns", "nfs", "a", "the"}


def words(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())]


def load_foods():
    with gzip.open(FOODS_FILE, "rt", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            row = dict(zip(header, line.rstrip("\n").split("\t")))
            for k in KEYS:
                row[k] = float(row[k]) if row.get(k) else None
            yield row


def food_by_id(fid):
    for row in load_foods():
        if row["id"] == fid:
            return row
    raise Problem(f"No USDA food with id {fid}. Run search first and use an id it prints.")


def cmd_search(args):
    query = words(args.query)
    if not query:
        raise Problem("Give a food name to search for.")
    query_set = set(query)
    scored = []
    for row in load_foods():
        desc = words(row["name"])
        hits = len(query_set & set(desc))
        if not hits:
            continue
        # USDA names lead with the food ("Rice, white, cooked"): reward a matching first word and
        # penalize extra foods in the first segment ("Beans and white rice", "Banana split").
        head = set(words(row["name"].split(",")[0])) - STOPWORDS
        score = (2 * hits + 0.5 * len(query_set & head) + (desc[0] in query_set)
                 - 0.6 * len(head - query_set) - 0.02 * len(desc) + 0.1 * (row["src"] == "fndds"))
        scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        raise Problem(f'No USDA food matches "{args.query}". Try a simpler name, or estimate it from the web.')
    for _, row in scored[:args.limit]:
        per = {k: row[k] or 0 for k in KEYS}
        portions = "; ".join(p.replace("=", " = ") + " g" for p in row["portions"].split("|") if p) or "none listed"
        print(f"{row['id']} | {row['name']}\n  per 100 g: {fmt_totals(per)}\n  portions: {portions}")


# ---------- barcodes ----------

def gtin_valid(code):
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def decode_image(path):
    try:
        import zxingcpp  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        # Setup installs the packages in a venv under HOME; use it from the system python too.
        for site in VENV.glob("lib/python3*/site-packages"):
            sys.path.insert(0, str(site))
        try:
            import zxingcpp  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            raise Problem("Barcode decoder not installed. Read the digits printed under the barcode "
                          "and run: barcode <digits>", code=3)
    import zxingcpp
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    for candidate in (image, image.convert("L"), ImageOps.autocontrast(image.convert("L"))):
        for result in zxingcpp.read_barcodes(candidate):
            text = result.text.strip()
            if text.isdigit():
                return text
    raise Problem("No barcode found in the photo. Ask for a closer, sharper photo of the barcode, "
                  "or read the digits under it and run: barcode <digits>")


def fetch_product(code, sample):
    if sample:
        return json.loads(SAMPLE_PRODUCT.read_text(encoding="utf-8"))
    try:
        return http_json(OFF_URL.format(code=code) + "?" + urllib.parse.urlencode({"fields": OFF_FIELDS}))
    except Problem as e:
        if "HTTP 404" in str(e):
            return {"status": 0}
        raise


def product_from_off(code, data):
    p = data.get("product") or {}
    n = p.get("nutriments") or {}

    def g(key):
        v = n.get(f"{key}_100g")
        return float(v) if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit()) else None

    kcal = g("energy-kcal")
    if kcal is None and g("energy") is not None:
        kcal = g("energy") / 4.184  # kJ
    sodium = g("sodium")
    if sodium is None and g("salt") is not None:
        sodium = g("salt") / 2.5
    per100 = {"kcal": kcal, "protein": g("proteins"), "carbs": g("carbohydrates"), "fat": g("fat"),
              "fiber": g("fiber"), "sugar": g("sugars"), "sodium": sodium * 1000 if sodium is not None else None}
    try:
        serving_g = float(p.get("serving_quantity")) or None
    except (TypeError, ValueError):
        serving_g = None
    brands = p.get("brands") or ""
    brands = ", ".join(brands) if isinstance(brands, list) else brands
    brand, title = brands.split(",")[0].strip(), (p.get("product_name") or "").strip()
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # "Miss Vickies" matches "Miss Vickie's"
    name = title if squash(brand) in squash(title) else " ".join(x for x in [brand, title] if x)
    return {"code": code, "name": name or f"Product {code}", "per100": per100,
            "serving_g": serving_g, "serving_size": p.get("serving_size"), "package": p.get("quantity")}


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Problem(f"Open Food Facts returned HTTP {e.code}. Try again in a minute.", code=4)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise Problem(f"Couldn't reach Open Food Facts ({e}). Try again in a minute.", code=4)


def print_product(prod):
    print(f"{prod['name']} (barcode {prod['code']})")
    if prod["package"]:
        print(f"  package: {prod['package']}")
    print(f"  per 100 g: {fmt_totals({k: v or 0 for k, v in prod['per100'].items()})}")
    if prod["serving_g"]:
        print(f"  per serving ({prod['serving_size'] or fmt_g(prod['serving_g']) + ' g'}): "
              f"{fmt_totals(scale(prod['per100'], prod['serving_g']))}")
        print(f"  log with: --product {prod['code']}=1srv  (or ={fmt_g(prod['serving_g'])} grams)")
    else:
        print(f"  no serving size listed; log with: --product {prod['code']}=<grams>")


def cmd_product(args):
    """Packaged products by brand and name, for when there's no barcode to read."""
    if args.sample:
        hits = [json.loads(SAMPLE_PRODUCT.read_text(encoding="utf-8"))["product"] | {"code": "0722252100900"}]
    else:
        query = urllib.parse.urlencode({"q": args.query, "page_size": 10, "fields": "code," + OFF_FIELDS})
        hits = http_json(f"{OFF_SEARCH_URL}?{query}").get("hits") or []
    state = load_state(args.sample)
    found = []
    for p in hits:
        prod = product_from_off(p.get("code", ""), {"product": p})
        if p.get("code") and prod["per100"]["kcal"] is not None:
            state["products"][prod["code"]] = prod
            found.append(prod)
    if not found:
        raise Problem(f'No packaged product with nutrition data matches "{args.query}". Ask for the barcode digits '
                      "or a photo of the Nutrition Facts label.")
    save_state(state, args.sample)
    for prod in found[:args.limit]:
        print_product(prod)


def cmd_barcode(args):
    code = decode_image(args.image) if args.image else re.sub(r"\D", "", args.code or "")
    if not code:
        raise Problem("Give the barcode digits or --image <path>.")
    if not gtin_valid(code):
        raise Problem(f"{code} isn't a valid barcode number (check digit fails). Ask for the digits again "
                      "or a clearer photo.")
    tried = [code] + (["0" + code] if len(code) == 12 else [])
    data = None
    for c in tried:
        data = fetch_product(c, args.sample)
        if data.get("status") == 1 and data.get("product"):
            code = c
            break
    else:
        raise Problem(f"Barcode {code} isn't in Open Food Facts. Ask the student for a photo of the "
                      "Nutrition Facts label and log it with --custom.")
    prod = product_from_off(code, data)
    if prod["per100"]["kcal"] is None:
        raise Problem(f"Found {prod['name']} ({code}) but it has no nutrition data. Ask for a photo of the "
                      "Nutrition Facts label and log it with --custom.")
    state = load_state(args.sample)
    state["products"][code] = prod
    save_state(state, args.sample)
    print_product(prod)
    missing = [k for k, v in prod["per100"].items() if v is None]
    if missing:
        print(f"  not listed (counted as 0): {', '.join(missing)}")
    if args.log:
        amount = args.amount or ("1srv" if prod["serving_g"] else "")
        if not amount:
            raise Problem(f"{prod['name']} has no serving size. Ask how many grams and rerun with --amount <grams>.")
        print()
        cmd_log(argparse.Namespace(date=args.date, time=args.time, meal=None, food=[], custom=[],
                                   product=[f"{code}={amount}"], sample=args.sample))


# ---------- log ----------

def parse_amount(text):
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(g|srv)?\s*", text)
    if not m:
        raise Problem(f'Amount "{text}" should be grams (150) or servings (1.5srv).')
    return float(m.group(1)), m.group(2) or "g"


def parse_custom(text):
    # "name;kcal;protein;carbs;fat[;fiber;sugar;sodium_mg]" for the whole portion eaten
    parts = [p.strip() for p in text.split(";")]
    if len(parts) < 5:
        raise Problem('--custom needs "name;kcal;protein;carbs;fat" (fiber;sugar;sodium_mg optional), '
                      "for the amount eaten.")
    try:
        nums = [float(p) if p else 0.0 for p in parts[1:8]]
    except ValueError:
        raise Problem(f'--custom numbers must be plain numbers: "{text}"')
    return parts[0], dict(zip(KEYS, nums + [0.0] * (7 - len(nums))))


def find_product(state, code):
    # UPC-A and EAN-13 differ only by a leading zero; match either form.
    want = code.strip().lstrip("0")
    return next((p for c, p in state["products"].items() if c.lstrip("0") == want), None)


def cmd_log(args):
    state = load_state(args.sample)
    items, total = [], {k: 0 for k in KEYS}
    for spec in args.food:
        fid, _, amount = spec.partition("=")
        grams, unit = parse_amount(amount or "100")
        if unit != "g":
            raise Problem("USDA foods are logged in grams: --food ID=GRAMS")
        row = food_by_id(fid.strip())
        n = scale(row, grams)
        items.append({"name": row["name"], "grams": grams, "src": f"usda:{row['id']}", **n})
    for spec in args.product:
        code, _, amount = spec.partition("=")
        prod = find_product(state, code)
        if not prod:
            raise Problem(f"Run barcode {code.strip()} before logging it.")
        qty, unit = parse_amount(amount or "1srv")
        if unit == "srv":
            if not prod["serving_g"]:
                raise Problem(f"{prod['name']} has no serving size; log it in grams.")
            qty *= prod["serving_g"]
        n = scale(prod["per100"], qty)
        items.append({"name": prod["name"], "grams": qty, "src": f"off:{prod['code']}", **n})
    for spec in args.custom:
        name, n = parse_custom(spec)
        items.append({"name": name, "grams": None, "src": "custom", **n})
    if not items:
        raise Problem("Nothing to log: add --food, --product or --custom.")
    for it in items:
        total = add(total, it)
    entry = {"meal": args.meal or items[0]["name"], "time": args.time, "items": items, "total": total}
    day = state["days"].setdefault(args.date, [])
    day.append(entry)
    save_state(state, args.sample)

    print(f"Logged: {entry['meal']}")
    for it in items:
        amount = f" ({fmt_g(it['grams'])} g)" if it["grams"] else ""
        print(f"  - {it['name']}{amount}: {it['kcal']:.0f} kcal, P {fmt_g(it['protein'])}g")
    print(f"Meal: {fmt_totals(total)}")
    print(fmt_vs_goals(day_total(day), state["goals"]))


def day_total(entries):
    t = {k: 0 for k in KEYS}
    for e in entries:
        t = add(t, e["total"])
    return t


def cmd_undo(args):
    state = load_state(args.sample)
    day = state["days"].get(args.date) or []
    if not day:
        raise Problem(f"Nothing logged on {args.date}.")
    removed = day.pop()
    save_state(state, args.sample)
    print(f"Removed: {removed['meal']} ({removed['total']['kcal']:.0f} kcal)")
    print(fmt_vs_goals(day_total(day), state["goals"]))


def cmd_today(args):
    state = load_state(args.sample)
    day = state["days"].get(args.date) or []
    if not day:
        print(f"Nothing logged on {args.date}.")
    for e in day:
        when = f"{e['time']} " if e.get("time") else ""
        print(f"- {when}{e['meal']}: {e['total']['kcal']:.0f} kcal, P {fmt_g(e['total']['protein'])}g")
    t = day_total(day)
    print(f"Total: {fmt_totals(t)}")
    print(fmt_vs_goals(t, state["goals"]))


def cmd_week(args):
    state = load_state(args.sample)
    end = date.fromisoformat(args.date)
    days = [(end - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    logged = [(d, day_total(state["days"][d])) for d in days if state["days"].get(d)]
    if not logged:
        print("Nothing logged in the last 7 days.")
        return
    goals = state["goals"]
    for d, t in logged:
        hit = " ✓protein" if goals.get("protein") and t["protein"] >= goals["protein"] * 0.95 else ""
        print(f"{d}: {t['kcal']:.0f} kcal, P {t['protein']:.0f}g, fiber {t['fiber']:.0f}g{hit}")
    avg = {k: sum(t[k] for _, t in logged) / len(logged) for k in KEYS}
    print(f"Average over {len(logged)} logged day(s): {fmt_totals(avg)}")
    if goals.get("kcal"):
        print(f"Goal: {goals['kcal']:.0f} kcal, P {goals.get('protein', 0):.0f}g")


# ---------- goals ----------

ACTIVITY = {"0": 1.2, "1-2": 1.375, "3-4": 1.55, "5-6": 1.725, "7": 1.9}


def cmd_goals(args):
    state = load_state(args.sample)
    goals = state["goals"]
    if args.calc:
        if not all([args.age, args.weight_lb, args.height_in]):
            raise Problem("--calc needs --age, --weight-lb and --height-in (and --sex, --activity, --goal).")
        kg, cm = args.weight_lb * 0.4536, args.height_in * 2.54
        sex_adj = {"male": 5, "female": -161}.get(args.sex, -78)
        bmr = 10 * kg + 6.25 * cm - 5 * args.age + sex_adj  # Mifflin-St Jeor
        tdee = bmr * ACTIVITY[args.activity]
        if args.goal == "cut":
            kcal = max(tdee - min(500, tdee * 0.15), {"male": 1500, "female": 1200}.get(args.sex, 1350))
            protein = 2.0 * kg
        elif args.goal == "bulk":
            kcal, protein = tdee + min(300, tdee * 0.10), 1.8 * kg
        else:
            kcal, protein = tdee, 1.6 * kg
        fat = kcal * 0.25 / 9
        carbs = max(kcal - protein * 4 - fat * 9, 0) / 4
        goals.update({"kcal": round(kcal, -1), "protein": round(protein), "carbs": round(carbs),
                      "fat": round(fat), "fiber": round(kcal / 1000 * 14)})
        print(f"Estimated maintenance: {tdee:.0f} kcal/day (Mifflin-St Jeor, activity x{ACTIVITY[args.activity]})")
    for k in ["kcal", "protein", "carbs", "fat", "fiber"]:
        v = getattr(args, k)
        if v is not None:
            goals[k] = v
    if args.calc or any(getattr(args, k) is not None for k in ["kcal", "protein", "carbs", "fat", "fiber"]):
        save_state(state, args.sample)
    if not goals:
        print("No goals set.")
        return
    print("Daily goals: " + ", ".join(f"{k} {goals[k]:.0f}{'' if k == 'kcal' else 'g'}" for k in goals))


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="snap-macros food and macro log")
    ap.add_argument("--sample", action="store_true", help="bundled sample data; separate saved state")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=6)
    s.set_defaults(func=cmd_search)

    pr = sub.add_parser("product")
    pr.add_argument("query")
    pr.add_argument("--limit", type=int, default=3)
    pr.set_defaults(func=cmd_product)

    b = sub.add_parser("barcode")
    b.add_argument("code", nargs="?")
    today_iso = date.today().isoformat()
    b.add_argument("--image")
    b.add_argument("--log", action="store_true", help="also log it")
    b.add_argument("--amount", help="with --log: grams (50) or servings (2srv); default 1 serving")
    b.add_argument("--date", default=today_iso)
    b.add_argument("--time")
    b.set_defaults(func=cmd_barcode)

    lg = sub.add_parser("log")
    lg.add_argument("--date", default=today_iso)
    lg.add_argument("--time")
    lg.add_argument("--meal")
    lg.add_argument("--food", action="append", default=[], help="USDA_ID=GRAMS")
    lg.add_argument("--product", action="append", default=[], help="BARCODE=GRAMS or BARCODE=Nsrv")
    lg.add_argument("--custom", action="append", default=[], help="name;kcal;protein;carbs;fat[;fiber;sugar;sodium_mg]")
    lg.set_defaults(func=cmd_log)

    for name, func in [("undo", cmd_undo), ("today", cmd_today), ("week", cmd_week)]:
        p = sub.add_parser(name)
        p.add_argument("--date", default=today_iso)
        p.set_defaults(func=func)

    g = sub.add_parser("goals")
    for k in ["kcal", "protein", "carbs", "fat", "fiber"]:
        g.add_argument(f"--{k}", type=float)
    g.add_argument("--calc", action="store_true")
    g.add_argument("--sex", choices=["male", "female", "other"], default="other")
    g.add_argument("--age", type=float)
    g.add_argument("--weight-lb", type=float)
    g.add_argument("--height-in", type=float)
    g.add_argument("--activity", choices=list(ACTIVITY), default="3-4", help="training days per week")
    g.add_argument("--goal", choices=["cut", "maintain", "bulk"], default="maintain")
    g.set_defaults(func=cmd_goals)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except Problem as e:
        print(f"ERROR: {e}")
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
