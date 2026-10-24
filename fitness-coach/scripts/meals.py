#!/usr/bin/env python3
"""fitness-coach meal prep: pantry, fixed meals, cook sessions, recipe plans, shopping list.

Standard library only; nutrition comes from the USDA table food.py uses.
You (the agent) write the recipes; this script keeps the bookkeeping exact.

Commands (dates are the student's local date, YYYY-MM-DD):
  prefs [--diet vegetarian] [--allergies peanuts,shellfish] [--dislikes cilantro] [--cuisines mexican,korean]
        [--equipment stove,microwave] [--max-minutes 30] [--batch 3] [--budget 40] [--skill beginner] [--reset]
  pantry add "chicken breast 2 lb" "eggs 12" "spinach" [--frozen] [--date D]
  pantry list [--date D] | pantry remove "<item>" | pantry clear
  fixed add --date D --meal dinner --note "dinner with friends" [--kcal 900] [--repeat mon,wed|weekdays --until D]
  fixed list [--from D] | fixed remove --date D --meal dinner
  context --date D [--days 3] [--meals lunch,dinner]   Everything needed to write the plan, in one call
  plan save --file plan.json        Check the recipes, estimate nutrition, build the shopping list, save
  plan show
  recipe <number or name>           Full recipe
  today --date D                    What to cook, eat, pack or thaw that day
  eat --date D --meal dinner        Log that meal's serving to the food log
  cooked <number or name> [--date D]  Take the recipe's ingredients out of the pantry
  shopping
  reminders                         Suggested check-ins: shop, thaw, cook, pack lunch

Exit codes: 0 ok, 2 bad input or not found.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import food  # noqa: E402  (same folder: USDA table, food log)

MEALS = ["breakfast", "lunch", "dinner", "snack"]
SHARE = {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.40, "snack": 0.10}
EATING_OUT_KCAL = {"breakfast": 500, "lunch": 800, "dinner": 1000, "snack": 300}
LEFTOVER_DAYS = 3  # cooked leftovers: 3-4 days in the fridge; we use the safe end
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"g": 1, "gram": 1, "grams": 1, "kg": 1000, "oz": 28.35, "lb": 453.6, "lbs": 453.6, "pound": 453.6,
         "pounds": 453.6}

# Rough fridge life in days from purchase, first match wins. None = keeps (pantry staple or long-life).
SHELF = [
    (("canned", "can of", "dried", "powder", "broth", "stock", "sauce", "oil", "vinegar", "spice", "salt", "sugar",
      "honey", "flour", "pasta", "noodle", "ramen", "oats", "cereal", "peanut butter", "jam", "nuts", "lentil"), None),
    (("green bean",), 6), (("eggplant",), 6), (("ground",), 2),
    (("chicken", "turkey", "poultry"), 2), (("fish", "salmon", "shrimp", "tilapia", "cod"), 2),
    (("steak", "beef", "pork", "lamb", "sausage"), 4), (("tofu", "tempeh"), 5),
    (("spinach", "lettuce", "greens", "arugula", "kale", "cilantro", "basil", "parsley"), 5),
    (("berr", "avocado"), 4), (("banana", "mushroom"), 5), (("milk",), 7), (("yogurt",), 10),
    (("bread", "tortilla", "bagel"), 7),
    (("bell pepper", "zucchini", "broccoli", "cauliflower", "tomato", "cucumber", "corn", "asparagus"), 6),
    (("cheese",), 21), (("egg",), 28), (("carrot", "cabbage", "apple", "orange", "lemon", "lime", "celery"), 21),
    (("onion", "garlic", "potato", "squash", "rice", "beans"), 30),
]
AISLES = [
    ("Produce", ("spinach", "lettuce", "greens", "kale", "onion", "garlic", "pepper", "tomato", "potato", "carrot",
                 "broccoli", "zucchini", "mushroom", "avocado", "banana", "berr", "apple", "lemon", "lime", "cilantro",
                 "ginger", "scallion", "cucumber", "cabbage", "corn", "squash", "celery", "basil", "parsley")),
    ("Meat & protein", ("chicken", "beef", "turkey", "pork", "salmon", "fish", "shrimp", "tofu", "tempeh", "sausage",
                        "steak", "tuna")),
    ("Dairy & eggs", ("milk", "yogurt", "cheese", "butter", "egg", "cream", "feta", "parmesan", "mozzarella")),
    ("Frozen", ("frozen",)),
    ("Bread & grains", ("bread", "tortilla", "rice", "pasta", "noodle", "oats", "quinoa", "bagel", "wrap", "pita")),
    ("Pantry", ("beans", "lentil", "broth", "stock", "sauce", "salsa", "oil", "vinegar", "soy", "honey", "peanut",
                "spice", "cumin", "paprika", "chili", "salt", "flour", "sugar", "can", "hummus", "sesame", "sriracha")),
]
STAPLES = ("salt", "pepper", "oil", "olive oil", "water", "black pepper")
MEAT_FISH = ("chicken", "beef", "pork", "turkey", "lamb", "bacon", "ham", "sausage", "steak", "salmon", "tuna",
             "fish", "shrimp", "anchov", "prosciutto", "pepperoni", "gelatin")
ANIMAL = MEAT_FISH + ("egg", "milk", "cheese", "yogurt", "butter", "cream", "honey", "whey", "feta", "parmesan",
                      "mozzarella", "ghee", "cheddar", "ricotta", "paneer")
ALLERGEN_WORDS = {  # what to look for in ingredient names for common allergies
    "peanut": ("peanut",), "nut": ("almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut", "peanut", "nut"),
    "tree nut": ("almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut"),
    "shellfish": ("shrimp", "crab", "lobster", "scallop", "clam", "mussel", "oyster"),
    "fish": ("salmon", "tuna", "cod", "tilapia", "fish", "anchov"),
    "dairy": ("milk", "cheese", "yogurt", "butter", "cream", "whey", "feta", "parmesan", "mozzarella", "ghee",
              "cheddar", "ricotta", "paneer"),
    "lactose": ("milk", "cheese", "yogurt", "cream", "whey"),
    "egg": ("egg",), "gluten": ("wheat", "flour", "bread", "pasta", "tortilla", "noodle", "bagel", "pita", "soy sauce",
                                "barley", "couscous"),
    "soy": ("soy", "tofu", "tempeh", "edamame", "miso"), "sesame": ("sesame", "tahini"),
}


class Problem(food.Problem):
    pass


# ---------- state ----------

def load_state(sample):
    path = food.state_dir(sample) / "meals.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"prefs": {}, "pantry": [], "fixed": [], "plan": None, "window": None}


def save_state(state, sample):
    folder = food.state_dir(sample)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, folder / "meals.json")


def d(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise Problem(f'"{text}" isn\'t a date; use YYYY-MM-DD.')


def short(day):
    return f"{day:%a} {day.month}/{day.day}"


def norm(text):
    return " ".join(food.words(text))


def contains_any(text, needles):
    low = text.lower()
    return any(n in low for n in needles)


FREE_OF = ("almond milk", "oat milk", "soy milk", "coconut milk", "rice milk", "vegan", "plant-based", "plant based")


def mentions(text, needles, free_of=""):
    """Whole-word match (plurals too), so "eggplant" isn't egg and "graham" isn't ham."""
    low = text.lower()
    if free_of and (f"{free_of}-free" in low or f"{free_of} free" in low):
        return False
    return any(re.search(r"\b" + re.escape(n) + r"(s|es)?\b", low) for n in needles)


# ---------- prefs ----------

def cmd_prefs(args):
    state = load_state(args.sample)
    prefs = {} if args.reset else state["prefs"]
    for key in ["diet", "skill"]:
        if getattr(args, key):
            prefs[key] = getattr(args, key).lower()
    for key in ["allergies", "dislikes", "cuisines", "equipment"]:
        if getattr(args, key) is not None:
            prefs[key] = [x.strip().lower() for x in getattr(args, key).split(",") if x.strip()]
    for key in ["max_minutes", "batch", "budget"]:
        if getattr(args, key) is not None:
            prefs[key] = getattr(args, key)
    state["prefs"] = prefs
    save_state(state, args.sample)
    print(fmt_prefs(prefs))


def fmt_prefs(prefs):
    if not prefs:
        return "No food preferences saved (diet, allergies, equipment, time, batch size)."
    parts = []
    if prefs.get("diet"):
        parts.append(prefs["diet"])
    if prefs.get("allergies"):
        parts.append("ALLERGIES: " + ", ".join(prefs["allergies"]))
    if prefs.get("dislikes"):
        parts.append("dislikes " + ", ".join(prefs["dislikes"]))
    if prefs.get("cuisines"):
        parts.append("likes " + ", ".join(prefs["cuisines"]))
    if prefs.get("equipment"):
        parts.append("equipment: " + ", ".join(prefs["equipment"]))
    if prefs.get("max_minutes"):
        parts.append(f"<= {prefs['max_minutes']} min")
    if prefs.get("batch"):
        parts.append(f"batch up to {prefs['batch']}")
    if prefs.get("budget"):
        parts.append(f"budget ${prefs['budget']}/week")
    if prefs.get("skill"):
        parts.append(f"{prefs['skill']} cook")
    return "Preferences: " + "; ".join(parts)


# ---------- pantry ----------

QTY = r"(\d+(?:\.\d+)?)\s*(kg|g|grams?|oz|lbs?|pounds?|dozen|x)?"


def parse_item(text):
    """ "chicken breast 2 lb", "2 lb chicken breast", "eggs 12", "black beans 2 cans", "spinach" -> pantry item."""
    text = " ".join(text.split()).lower()
    m = re.fullmatch(rf"(.+?)\s+{QTY}(?:\s+(.+))?", text)
    if m:
        name, qty, unit, rest = m.group(1), float(m.group(2)), m.group(3) or "", m.group(4) or ""
    else:
        m = re.fullmatch(rf"{QTY}\s+(.+)", text)
        if not m:
            return {"name": text, "qty_text": text}
        qty, unit, name = float(m.group(1)), m.group(2) or "", m.group(3)
        rest = ""
        if not unit and name.split()[0] in ("cans", "can", "bags", "bag", "boxes", "box", "cups", "cup", "bunch"):
            rest, name = name.split()[0], " ".join(name.split()[1:]) or name
    item = {"name": name.strip(), "qty_text": text}
    if unit in UNITS:
        item["grams"] = round(qty * UNITS[unit])
    elif unit == "dozen":
        item["count"] = qty * 12
    else:
        item["count"] = qty
        if rest:
            item["unit"] = rest
    return item


def shelf_days(name):
    for keys, days in SHELF:
        if any(k in name for k in keys):
            return days
    return None


def use_by(item):
    if item.get("frozen"):
        return None
    days = shelf_days(item["name"])
    return d(item["added"]) + timedelta(days=days) if days is not None else None


def fmt_item(item):
    amount = ""
    if item.get("grams"):
        amount = f" {item['grams']:.0f} g"
    elif item.get("count"):
        amount = f" x{item['count']:g}" + (f" {item['unit']}" if item.get("unit") else "")
    return item["name"] + amount


DESCRIPTORS = {"raw", "fresh", "frozen", "canned", "cooked", "dry", "dried", "plain", "whole", "drained", "chopped",
               "boneless", "skinless", "large", "small", "medium", "organic", "lean", "uncooked", "low", "fat"}


def key_words(name):
    return set(norm(name).split()) - DESCRIPTORS


def find_pantry(pantry, name):
    want = key_words(name)
    best = None
    for item in pantry:
        have = key_words(item["name"])
        if have and (have <= want or want <= have):
            if best is None or len(have & want) > len(key_words(best["name"]) & want):
                best = item
    return best


def cmd_pantry(args):
    state = load_state(args.sample)
    pantry = state["pantry"]
    if args.action == "add":
        if not args.items:
            raise Problem('Give items, e.g. pantry add "chicken breast 2 lb" "eggs 12" "spinach".')
        for text in args.items:
            for part in [p for p in re.split(r"[,;]", text) if p.strip()]:
                item = parse_item(part)
                item["added"] = args.date
                item["frozen"] = args.frozen or "frozen" in item["name"]
                old = find_pantry(pantry, item["name"])
                if old and old["name"] == item["name"]:
                    pantry.remove(old)
                pantry.append(item)
        save_state(state, args.sample)
    elif args.action == "remove":
        for text in args.items:
            item = find_pantry(pantry, text)
            if not item:
                raise Problem(f'"{text}" isn\'t in the pantry.')
            pantry.remove(item)
        save_state(state, args.sample)
    elif args.action == "clear":
        state["pantry"] = pantry = []
        save_state(state, args.sample)
    print_pantry(pantry, d(args.date))


def print_pantry(pantry, today):
    if not pantry:
        print("Pantry is empty.")
        return
    soon = sorted([i for i in pantry if use_by(i) and use_by(i) <= today + timedelta(days=2)], key=use_by)
    frozen = [i for i in pantry if i.get("frozen")]
    rest = [i for i in pantry if i not in soon and i not in frozen]
    if soon:
        print("Use first: " + "; ".join(f"{fmt_item(i)} (by {short(use_by(i))})" for i in soon))
    if rest:
        print("Pantry: " + "; ".join(fmt_item(i) for i in sorted(rest, key=lambda i: use_by(i) or date.max)))
    if frozen:
        print("Frozen (thaw in the fridge the night before): " + "; ".join(fmt_item(i) for i in frozen))


# ---------- fixed meals ----------

def cmd_fixed(args):
    state = load_state(args.sample)
    fixed = state["fixed"]
    if args.action == "add":
        if not (args.date and args.meal and args.note):
            raise Problem("fixed add needs --date, --meal and --note.")
        dates = [d(args.date)]
        if args.repeat:
            until = d(args.until) if args.until else dates[0] + timedelta(days=27)
            days = range(5) if args.repeat == "weekdays" else [WEEKDAYS.index(w.strip()[:3]) for w in args.repeat.split(",")]
            dates = [dates[0] + timedelta(days=i) for i in range((until - dates[0]).days + 1)
                     if (dates[0] + timedelta(days=i)).weekday() in days]
        for day in dates:
            fixed[:] = [f for f in fixed if not (f["date"] == day.isoformat() and f["meal"] == args.meal)]
            fixed.append({"date": day.isoformat(), "meal": args.meal, "note": args.note, "kcal": args.kcal})
        save_state(state, args.sample)
        print(f"Added {len(dates)}: {args.note} ({args.meal}" + (f", {len(dates)} days" if len(dates) > 1 else
                                                               f", {short(dates[0])}") + ").")
    elif args.action == "remove":
        before = len(fixed)
        fixed[:] = [f for f in fixed if not (f["date"] == args.date and (not args.meal or f["meal"] == args.meal))]
        save_state(state, args.sample)
        print(f"Removed {before - len(fixed)}.")
    start = args.date if args.action == "list" else None
    for f in sorted(fixed, key=lambda f: (f["date"], MEALS.index(f["meal"]))):
        if args.action == "list" and start and f["date"] < start:
            continue
        if args.action == "list":
            print(f"{short(d(f['date']))} {f['meal']}: {f['note']}" + (f" (~{f['kcal']} kcal)" if f.get("kcal") else ""))
    if args.action == "list" and not fixed:
        print("No fixed meals.")


# ---------- context ----------

def workout_days(sample):
    path = food.state_dir(sample) / "workouts.json"
    if not path.exists():
        return {}
    plan = json.loads(path.read_text(encoding="utf-8")).get("plan") or {}
    return {s["weekday"]: s for s in plan.get("schedule") or []}


def build_window(state, start, days, meals, sample):
    goals = food.load_state(sample)["goals"]
    fixed = {(f["date"], f["meal"]): f for f in state["fixed"]}
    training = workout_days(sample)
    slots = []
    for i in range(days):
        day = start + timedelta(days=i)
        eaten = set(meals) | {"breakfast", "lunch", "dinner"}
        total = sum(SHARE[m] for m in eaten)
        kcal_left = goals.get("kcal")
        open_meals = []
        for m in MEALS:
            if m not in eaten:
                continue
            f = fixed.get((day.isoformat(), m))
            if f:
                est = f.get("kcal") or EATING_OUT_KCAL[m]
                slots.append({"date": day.isoformat(), "meal": m, "fixed": f["note"], "kcal_est": est,
                              "estimated": not f.get("kcal")})
                if kcal_left:
                    kcal_left -= est
            elif m in meals:
                open_meals.append(m)
            elif kcal_left:
                kcal_left -= goals["kcal"] * SHARE[m] / total  # unplanned meal keeps its usual share
        share_open = sum(SHARE[m] for m in open_meals) or 1
        for m in open_meals:
            slot = {"date": day.isoformat(), "meal": m}
            if kcal_left:
                slot["kcal"] = round(max(kcal_left, 0) * SHARE[m] / share_open, -1)
            if goals.get("protein"):
                slot["protein"] = round(goals["protein"] * SHARE[m] / total)
            slots.append(slot)
        if day.weekday() in training:
            for s in slots:
                if s["date"] == day.isoformat():
                    s["training"] = f"{training[day.weekday()]['label']} at {training[day.weekday()]['start']}"
    slots.sort(key=lambda s: (s["date"], MEALS.index(s["meal"])))
    return slots


def cook_sessions(slots, start, batch):
    fixed_dinners = {s["date"] for s in slots if s["meal"] == "dinner" and s.get("fixed")}
    sessions = []
    for meal in MEALS:
        series = [s for s in slots if s["meal"] == meal and not s.get("fixed")]
        i = 0
        while i < len(series):
            first = d(series[i]["date"])
            if meal in ("breakfast", "lunch") and first > start:
                cook, when = first - timedelta(days=1), "evening"
            elif meal in ("breakfast", "lunch"):
                cook, when = first, "morning"
            else:
                cook, when = first, "evening"
            if when == "evening" and cook.isoformat() in fixed_dinners:
                if cook - timedelta(days=1) >= start and (cook - timedelta(days=1)).isoformat() not in fixed_dinners:
                    cook -= timedelta(days=1)
                else:
                    when = "afternoon, before you go out"
            covers = [series[i]]
            i += 1
            while i < len(series) and len(covers) < batch and d(series[i]["date"]) <= cook + timedelta(days=LEFTOVER_DAYS):
                covers.append(series[i])
                i += 1
            sessions.append({"cook": cook.isoformat(), "when": when, "meal": meal,
                             "covers": [f"{s['date']} {s['meal']}" for s in covers]})
    sessions.sort(key=lambda s: (s["cook"], s["when"] != "morning"))
    return sessions


def cmd_context(args):
    state = load_state(args.sample)
    start = d(args.date)
    meals = [m.strip() for m in args.meals.split(",") if m.strip()]
    if any(m not in MEALS for m in meals):
        raise Problem(f"--meals takes {', '.join(MEALS)}.")
    batch = args.batch or state["prefs"].get("batch") or 3
    slots = build_window(state, start, args.days, meals, args.sample)
    sessions = cook_sessions(slots, start, batch)
    state["window"] = {"start": start.isoformat(), "days": args.days, "meals": meals, "slots": slots,
                       "sessions": sessions}
    save_state(state, args.sample)

    end = start + timedelta(days=args.days - 1)
    print(f"Meal prep {short(start)}" + (f" to {short(end)}" if args.days > 1 else "") + f" ({', '.join(meals)})")
    print(fmt_prefs(state["prefs"]))
    goals = food.load_state(args.sample)["goals"]
    if goals.get("kcal"):
        print(f"Daily goal: {goals['kcal']:.0f} kcal, {goals.get('protein', 0):.0f} g protein")
        today = food.load_state(args.sample)["days"].get(start.isoformat()) or []
        if today:
            t = food.day_total(today)
            print(f"Already eaten {short(start)}: {t['kcal']:.0f} kcal, {t['protein']:.0f} g protein "
                  f"({goals['kcal'] - t['kcal']:.0f} kcal, {goals.get('protein', 0) - t['protein']:.0f} g protein left)")
    else:
        print("No calorie goals set (food.py goals); recipes can't be sized to targets.")
    print_pantry(state["pantry"], start)
    print("\nSlots:")
    for s in slots:
        if s.get("fixed"):
            print(f"{short(d(s['date']))} {s['meal']:<9} FIXED  {s['fixed']} (~{s['kcal_est']:.0f} kcal"
                  + (" est." if s["estimated"] else "") + ")")
            continue
        target = ", ".join(x for x in [f"~{s['kcal']:.0f} kcal" if s.get("kcal") else "",
                                       f"{s['protein']} g protein" if s.get("protein") else ""] if x)
        print(f"{short(d(s['date']))} {s['meal']:<9} open   {target}" + (f"  [training: {s['training']}]"
                                                                        if s.get("training") else ""))
    print(f"\nSuggested cook sessions (batch up to {batch}; leftovers keep {LEFTOVER_DAYS} days in the fridge):")
    for n, ses in enumerate(sessions, 1):
        print(f"{n}. {short(d(ses['cook']))} {ses['when']}: {ses['meal']} for "
              + ", ".join(short(d(c.split()[0])) for c in ses["covers"])
              + f" ({len(ses['covers'])} serving{'s' if len(ses['covers']) > 1 else ''})")
    print("\nWrite the recipes as JSON (references/meal-prep.md), then run: plan save --file <path>")


# ---------- plan ----------

def slot_key(text):
    parts = text.split()
    if len(parts) != 2 or parts[1] not in MEALS:
        raise Problem(f'Slot "{text}" should look like "2026-10-26 dinner".')
    d(parts[0])
    return f"{parts[0]} {parts[1]}"


def aisle(name):
    for label, words in AISLES:
        if contains_any(name, words):
            return label
    return "Other"


def check_diet(recipe, prefs):
    errors, warnings = [], []
    names = [i["item"].lower() for i in recipe["ingredients"]]
    for allergy in prefs.get("allergies", []):
        base = allergy.rstrip("s")
        needles = ALLERGEN_WORDS.get(base, (base,))
        hits = [n for n in names if mentions(n, needles, base)
                and not (base in ("dairy", "lactose") and contains_any(n, FREE_OF))]
        if hits:
            errors.append(f"{recipe['name']}: contains {', '.join(hits)} but the student is allergic to {allergy}.")
    diet = prefs.get("diet", "")
    banned = ANIMAL if "vegan" in diet else MEAT_FISH if "vegetarian" in diet else ()
    if "pescatarian" in diet:
        banned = tuple(x for x in MEAT_FISH if x not in ("salmon", "tuna", "fish", "shrimp", "anchov"))
    hits = [n for n in names if mentions(n, banned) and not contains_any(n, FREE_OF)]
    if hits:
        errors.append(f"{recipe['name']}: {', '.join(hits)} doesn't fit a {diet} diet.")
    for dislike in prefs.get("dislikes", []):
        if any(dislike in n for n in names):
            warnings.append(f"{recipe['name']}: uses {dislike}, which the student dislikes.")
    if prefs.get("max_minutes") and recipe.get("minutes", 0) > prefs["max_minutes"]:
        warnings.append(f"{recipe['name']}: {recipe['minutes']} min is over their {prefs['max_minutes']} min limit.")
    return errors, warnings


def nutrition(recipe, rows):
    total, matched, skipped = {k: 0 for k in food.KEYS}, [], []
    for ing in recipe["ingredients"]:
        grams = ing.get("grams")
        if not grams or contains_any(ing["item"], ("water", "salt")) and grams < 20:
            continue
        row = None
        if ing.get("usda"):
            row = next((r for r in rows if r["id"] == str(ing["usda"])), None)
        if row is None:
            ranked = food.rank_foods(ing["item"], rows, ingredient=True)
            row = ranked[0] if ranked else None
        if row is None:
            skipped.append(ing["item"])
            continue
        total = food.add(total, food.scale(row, grams))
        matched.append(f"{ing['item']} -> {row['name']}")
    servings = max(recipe.get("servings") or len(recipe["covers"]), 1)
    return {k: v / servings for k, v in total.items()}, matched, skipped


def cmd_plan(args):
    state = load_state(args.sample)
    if args.action == "show":
        plan = state.get("plan")
        if not plan:
            raise Problem("No meal plan saved. Run context, write recipes, then plan save.")
        for n, r in enumerate(plan["recipes"], 1):
            print(fmt_recipe_line(n, r))
        if plan.get("warnings"):
            print("Notes: " + " | ".join(plan["warnings"]))
        return
    window = state.get("window")
    if not window:
        raise Problem("Run context first, so the plan has slots to fill.")
    try:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Problem(f"Couldn't read {args.file} ({e}).")
    recipes = raw.get("recipes") if isinstance(raw, dict) else raw
    if not recipes:
        raise Problem('The file needs {"recipes": [...]}; see references/meal-prep.md.')

    rows = list(food.load_foods())
    open_slots = {f"{s['date']} {s['meal']}": s for s in window["slots"] if not s.get("fixed")}
    fixed_slots = {f"{s['date']} {s['meal']}": s["fixed"] for s in window["slots"] if s.get("fixed")}
    errors, warnings, seen = [], [], {}
    for r in recipes:
        for key in ("name", "cook", "covers", "ingredients", "steps"):
            if not r.get(key):
                raise Problem(f'Each recipe needs "{key}" (recipe: {r.get("name", "?")}).')
        r["covers"] = [slot_key(c) for c in r["covers"]]
        r["servings"] = r.get("servings") or len(r["covers"])
        cook = d(r["cook"])
        for c in r["covers"]:
            if c in fixed_slots:
                errors.append(f"{r['name']}: {c} is already taken care of ({fixed_slots[c]}).")
            if c in seen:
                errors.append(f"{c} is covered by both {seen[c]} and {r['name']}.")
            seen[c] = r["name"]
            if d(c.split()[0]) < cook:
                errors.append(f"{r['name']}: {c} is before it's cooked ({r['cook']}).")
            elif d(c.split()[0]) > cook + timedelta(days=LEFTOVER_DAYS):
                warnings.append(f"{r['name']}: {c} is more than {LEFTOVER_DAYS} days after cooking; freeze that "
                                "portion right after cooking and thaw it in the fridge the night before.")
        if r["servings"] < len(r["covers"]):
            errors.append(f"{r['name']}: {r['servings']} servings can't cover {len(r['covers'])} meals.")
        e, w = check_diet(r, state["prefs"])
        errors += e
        warnings += w
        per, matched, skipped = nutrition(r, rows)
        r["per_serving"] = {k: round(v, 1) for k, v in per.items()}
        r["matched"] = matched
        targets = [open_slots[c] for c in r["covers"] if c in open_slots and open_slots[c].get("kcal")]
        if targets:
            want = sum(t["kcal"] for t in targets) / len(targets)
            if abs(per["kcal"] - want) > 0.25 * want:
                warnings.append(f"{r['name']}: ~{per['kcal']:.0f} kcal a serving vs ~{want:.0f} target; adjust portions.")
            want_p = sum(t.get("protein", 0) for t in targets) / len(targets)
            if want_p and per["protein"] < 0.75 * want_p:
                warnings.append(f"{r['name']}: {per['protein']:.0f} g protein a serving vs {want_p:.0f} g target.")
        if skipped:
            warnings.append(f"{r['name']}: no nutrition match for {', '.join(skipped)}.")
    missing = [s for s in open_slots if s not in seen]
    if missing:
        warnings.append("Not covered yet: " + ", ".join(missing) + ".")
    if errors:
        raise Problem("Fix these and save again:\n- " + "\n- ".join(errors))

    # Shopping list: what the recipes need minus what the pantry has.
    need = {}
    for r in recipes:
        for ing in r["ingredients"]:
            key = norm(ing["item"])
            entry = need.setdefault(key, {"item": ing["item"], "grams": 0, "count": 0, "qty": []})
            entry["grams"] += ing.get("grams") or 0
            entry["count"] += ing.get("count") or 0
            if ing.get("qty"):
                entry["qty"].append(ing["qty"])
    shopping, used_from_pantry = [], set()
    for entry in need.values():
        have = find_pantry(state["pantry"], entry["item"])
        if have:
            used_from_pantry.add(have["name"])
            if have.get("grams") and entry["grams"] > have["grams"] + 1:
                shopping.append({**entry, "grams": entry["grams"] - have["grams"], "note": f"have {have['grams']} g"})
            elif have.get("count") and entry["count"] > have["count"]:
                shopping.append({**entry, "count": entry["count"] - have["count"], "note": f"have {have['count']:g}"})
            continue
        if norm(entry["item"]) in STAPLES:
            continue
        shopping.append(entry)
    for s in shopping:
        s["aisle"] = aisle(s["item"])
    start = d(window["start"])
    unused = [i["name"] for i in state["pantry"] if use_by(i) and use_by(i) <= start + timedelta(days=window["days"])
              and i["name"] not in used_from_pantry]
    if unused:
        warnings.append("Goes bad before the plan ends and isn't used: " + ", ".join(unused) + ".")

    state["plan"] = {"recipes": recipes, "shopping": shopping, "warnings": warnings, "window": window}
    save_state(state, args.sample)
    for n, r in enumerate(recipes, 1):
        print(fmt_recipe_line(n, r))
        print("   matched: " + "; ".join(r["matched"]))
    print_shopping(shopping)
    if warnings:
        print("Notes:\n- " + "\n- ".join(warnings))


def fmt_recipe_line(n, r):
    p = r["per_serving"]
    eats = ", ".join(short(d(c.split()[0])) + " " + c.split()[1] for c in r["covers"])
    return (f"{n}. {r['name']}: cook {short(d(r['cook']))}, {r.get('minutes', '?')} min, {r['servings']} servings "
            f"({eats}). Per serving ~{p['kcal']:.0f} kcal, P {p['protein']:.0f}g, C {p['carbs']:.0f}g, "
            f"F {p['fat']:.0f}g, fiber {p['fiber']:.0f}g")


def print_shopping(shopping):
    if not shopping:
        print("Shopping: nothing to buy, the pantry covers it.")
        return
    print("Shopping list:")
    for label in [a for a, _ in AISLES] + ["Other"]:
        items = [s for s in shopping if s["aisle"] == label]
        if items:
            parts = []
            for s in items:
                amount = " / ".join(s["qty"]) if s.get("qty") else (f"{s['grams']:.0f} g" if s["grams"] else
                                                                     f"x{s['count']:g}" if s["count"] else "")
                parts.append(s["item"] + (f" ({amount})" if amount else "") + (f" [{s['note']}]" if s.get("note") else ""))
            print(f"  {label}: " + "; ".join(parts))


def get_recipe(state, key):
    plan = state.get("plan")
    if not plan:
        raise Problem("No meal plan saved yet.")
    recipes = plan["recipes"]
    if key.isdigit() and 1 <= int(key) <= len(recipes):
        return recipes[int(key) - 1]
    hits = [r for r in recipes if key.lower() in r["name"].lower()]
    if not hits:
        raise Problem(f'No recipe "{key}" in the plan.')
    return hits[0]


def cmd_recipe(args):
    r = get_recipe(load_state(args.sample), args.recipe)
    p = r["per_serving"]
    print(f"{r['name']} ({r.get('minutes', '?')} min, {r['servings']} servings)")
    print(f"Per serving: ~{p['kcal']:.0f} kcal, P {p['protein']:.0f}g, C {p['carbs']:.0f}g, F {p['fat']:.0f}g, "
          f"fiber {p['fiber']:.0f}g")
    print("Ingredients:")
    for ing in r["ingredients"]:
        amount = ing.get("qty") or (f"{ing['grams']} g" if ing.get("grams") else f"x{ing['count']:g}" if ing.get("count") else "")
        print(f"  - {ing['item']}" + (f": {amount}" if amount else ""))
    print("Steps:")
    for i, step in enumerate(r["steps"], 1):
        print(f"  {i}. {step}")
    for c, idea in (r.get("remix") or {}).items():
        print(f"Remix for {short(d(c.split()[0]))} {c.split()[1]}: {idea}")
    if r.get("storage"):
        print(f"Storage: {r['storage']}")


def cmd_today(args):
    state = load_state(args.sample)
    plan = state.get("plan")
    if not plan:
        raise Problem("No meal plan saved yet.")
    day = args.date
    tomorrow = (d(day) + timedelta(days=1)).isoformat()
    lines = []
    for f in sorted(state["fixed"], key=lambda f: MEALS.index(f["meal"])):
        if f["date"] == day:
            lines.append(f"{f['meal'].title()}: {f['note']} (nothing to cook)")
    for r in plan["recipes"]:
        for k, c in enumerate(r["covers"], 1):
            date_, meal = c.split()
            if date_ != day:
                continue
            if r["cook"] == day and k == 1:
                lines.append(f"{meal.title()}: cook {r['name']} ({r.get('minutes', '?')} min, makes {r['servings']}); "
                             f"eat 1, pack {r['servings'] - 1} for later")
            else:
                remix = (r.get("remix") or {}).get(c)
                lines.append(f"{meal.title()}: {r['name']}, serving {k} of {r['servings']}"
                             + (f". Remix: {remix.rstrip('.')}" if remix else "") + ". Reheat until steaming hot")
        if r["cook"] == day and r["covers"][0].split()[0] != day:
            lines.append(f"Tonight: cook {r['name']} ({r.get('minutes', '?')} min) for "
                         + ", ".join(short(d(c.split()[0])) + " " + c.split()[1] for c in r["covers"]))
        if r["cook"] == tomorrow:
            frozen = [i["item"] for i in r["ingredients"] if (find_pantry(state["pantry"], i["item"]) or {}).get("frozen")]
            if frozen:
                lines.append(f"Tonight: move {', '.join(frozen)} from the freezer to the fridge for tomorrow's {r['name']}")
    order = {m: i for i, m in enumerate(MEALS)}
    lines.sort(key=lambda l: order.get(l.split(":")[0].lower(), 9))
    print(f"{short(d(day))}:")
    print("\n".join("- " + l for l in lines) if lines else "- Nothing planned.")


def cmd_eat(args):
    state = load_state(args.sample)
    key = f"{args.date} {args.meal}"
    plan = state.get("plan") or {"recipes": []}
    r = next((r for r in plan["recipes"] if key in r["covers"]), None)
    if not r:
        raise Problem(f"No planned recipe for {key}. Log it with food.py instead.")
    p = {k: v * args.servings for k, v in r["per_serving"].items()}
    spec = f"{r['name']};" + ";".join(f"{p[k]:.1f}" for k in food.KEYS)
    food.cmd_log(argparse.Namespace(date=args.date, time=None, meal=f"{r['name']} (meal prep)", food=[],
                                    product=[], custom=[spec], sample=args.sample))


def cmd_cooked(args):
    state = load_state(args.sample)
    r = get_recipe(state, args.recipe)
    used = []
    for ing in r["ingredients"]:
        item = find_pantry(state["pantry"], ing["item"])
        if not item:
            continue
        if item.get("grams") and ing.get("grams"):
            item["grams"] -= ing["grams"]
            gone = item["grams"] <= 0
        elif item.get("count") and ing.get("count"):
            item["count"] -= ing["count"]
            gone = item["count"] <= 0
        else:
            gone = False
        if gone:
            state["pantry"].remove(item)
        used.append(item["name"])
    r["cooked_on"] = args.date
    save_state(state, args.sample)
    print(f"Cooked {r['name']}. Took from the pantry: {', '.join(used) or 'nothing tracked'}.")
    print_pantry(state["pantry"], d(args.date))


def cmd_shopping(args):
    plan = load_state(args.sample).get("plan")
    if not plan:
        raise Problem("No meal plan saved yet.")
    print_shopping(plan["shopping"])


def cmd_reminders(args):
    state = load_state(args.sample)
    plan = state.get("plan")
    if not plan:
        raise Problem("No meal plan saved yet.")
    training = workout_days(args.sample)
    out = []
    first_cook = min(r["cook"] for r in plan["recipes"])
    if plan["shopping"]:
        shop_day = d(first_cook) - timedelta(days=1)
        items = ", ".join(s["item"] for s in plan["shopping"][:6]) + ("..." if len(plan["shopping"]) > 6 else "")
        out.append((shop_day.isoformat(), "17:00", f"Groceries for meal prep: {items} (run shopping for the list)"))
    for r in plan["recipes"]:
        cook = d(r["cook"])
        first_meal = r["covers"][0].split()[1]
        when = "11:00" if first_meal in ("breakfast", "lunch") and r["covers"][0].startswith(r["cook"]) else "18:00"
        session = training.get(cook.weekday())
        if when == "18:00" and session:
            end_h, end_m = map(int, session["end"].split(":"))
            if 15 <= end_h <= 20:
                total = end_h * 60 + end_m + 45
                when = f"{total // 60:02d}:{total % 60:02d}"
        out.append((r["cook"], when, f"Cook {r['name']} ({r.get('minutes', '?')} min, makes {r['servings']})"))
        frozen = [i["item"] for i in r["ingredients"] if (find_pantry(state["pantry"], i["item"]) or {}).get("frozen")]
        if frozen:
            out.append(((cook - timedelta(days=1)).isoformat(), "20:00", f"Thaw {', '.join(frozen)} in the fridge "
                                                                         f"for tomorrow's {r['name']}"))
        for c in r["covers"]:
            date_, meal = c.split()
            if meal == "lunch" and date_ != r["cook"]:
                out.append((date_, "08:00", f"Pack {r['name']} for lunch"))
    for when in sorted(out):
        print(f"{when[0]} {when[1]} | {when[2]}")


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="fitness-coach meal prep")
    ap.add_argument("--sample", action="store_true", help="separate saved state for trying things out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    today_iso = date.today().isoformat()

    p = sub.add_parser("prefs")
    for k in ["diet", "allergies", "dislikes", "cuisines", "equipment", "skill"]:
        p.add_argument(f"--{k}")
    p.add_argument("--max-minutes", type=int)
    p.add_argument("--batch", type=int, help="most servings to cook at once (1 = cook fresh every meal)")
    p.add_argument("--budget", type=float, help="dollars per week")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(func=cmd_prefs)

    pa = sub.add_parser("pantry")
    pa.add_argument("action", choices=["add", "list", "remove", "clear"])
    pa.add_argument("items", nargs="*")
    pa.add_argument("--frozen", action="store_true")
    pa.add_argument("--date", default=today_iso)
    pa.set_defaults(func=cmd_pantry)

    fx = sub.add_parser("fixed")
    fx.add_argument("action", choices=["add", "list", "remove"])
    fx.add_argument("--date")
    fx.add_argument("--meal", choices=MEALS)
    fx.add_argument("--note")
    fx.add_argument("--kcal", type=float)
    fx.add_argument("--repeat", help="weekdays, or mon,wed,fri")
    fx.add_argument("--until")
    fx.set_defaults(func=cmd_fixed)

    c = sub.add_parser("context")
    c.add_argument("--date", default=today_iso)
    c.add_argument("--days", type=int, default=3)
    c.add_argument("--meals", default="lunch,dinner")
    c.add_argument("--batch", type=int)
    c.set_defaults(func=cmd_context)

    pl = sub.add_parser("plan")
    pl.add_argument("action", choices=["save", "show"])
    pl.add_argument("--file")
    pl.set_defaults(func=cmd_plan)

    r = sub.add_parser("recipe")
    r.add_argument("recipe")
    r.set_defaults(func=cmd_recipe)

    t = sub.add_parser("today")
    t.add_argument("--date", default=today_iso)
    t.set_defaults(func=cmd_today)

    e = sub.add_parser("eat")
    e.add_argument("--date", default=today_iso)
    e.add_argument("--meal", choices=MEALS, required=True)
    e.add_argument("--servings", type=float, default=1)
    e.set_defaults(func=cmd_eat)

    ck = sub.add_parser("cooked")
    ck.add_argument("recipe")
    ck.add_argument("--date", default=today_iso)
    ck.set_defaults(func=cmd_cooked)

    sub.add_parser("shopping").set_defaults(func=cmd_shopping)
    sub.add_parser("reminders").set_defaults(func=cmd_reminders)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    if args.cmd == "plan" and args.action == "save" and not args.file:
        print("ERROR: plan save needs --file <recipes.json>.")
        return 2
    try:
        args.func(args)
    except food.Problem as e:
        print(f"ERROR: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
