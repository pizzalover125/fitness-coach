#!/usr/bin/env python3
"""fitness-coach diet reports: a short nightly report, a weekly one, and detailed versions on request.

Standard library only; reads the food log (food.py) plus the meal-prep and workout plans when they exist.

The day report covers the 24 hours ending at the report time on --date (default 21:00, local), so a
10:30 pm snack counts toward tomorrow's report. Entries logged without a time count as midday.

Commands (dates are the student's local date, YYYY-MM-DD):
  day --date D [--detail]       The day ending at the report time on D
  week --date D [--detail]      The 7 days ending at the report time on D, compared with the week before
  auto --date D                 What the nightly check-in sends: the week report on the weekly day, else the day
  settings [--time 21:00] [--week-day sun]

Exit codes: 0 ok, 2 bad input.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import food  # noqa: E402  (same folder: food log, goals, USDA table)

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SODIUM_LIMIT = 2300  # mg/day, Dietary Guidelines for Americans
MACRO_KCAL = {"protein": 4, "carbs": 4, "fat": 9}


class Problem(food.Problem):
    pass


# ---------- data ----------

def settings(state):
    return {"time": "21:00", "week_day": "sun", **state.get("report", {})}


def entries_between(state, start, end):
    """Food log entries with start < time <= end, each with its datetime."""
    out = []
    day = start.date()
    while day <= end.date():
        for e in state["days"].get(day.isoformat(), []):
            hhmm = e.get("time") or "12:00"
            try:
                when = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
            except ValueError:
                when = datetime.combine(day, datetime.strptime("12:00", "%H:%M").time())
            if start < when <= end:
                out.append({**e, "when": when})
        day += timedelta(days=1)
    return sorted(out, key=lambda e: e["when"])


def total(entries):
    t = {k: 0 for k in food.KEYS}
    for e in entries:
        t = food.add(t, e["total"])
    return t


def window_end(day, cfg):
    return datetime.combine(day, datetime.strptime(cfg["time"], "%H:%M").time())


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def workout_note(day, sample):
    """Planned or logged workout on that day, from workouts.py."""
    data = read_json(food.state_dir(sample) / "workouts.json")
    plan = data.get("plan") or {}
    session = next((s for s in plan.get("schedule") or [] if s["weekday"] == day.weekday()), None)
    done = [h for h in data.get("history", []) if h["date"] == day.isoformat()]
    if done:
        return f"{done[-1]['label']} done"
    if session:
        return f"{session['label']} planned, not logged"
    return None


def tomorrow_line(day, sample):
    nxt = day + timedelta(days=1)
    parts = []
    plan = (read_json(food.state_dir(sample) / "workouts.json").get("plan") or {})
    session = next((s for s in plan.get("schedule") or [] if s["weekday"] == nxt.weekday()), None)
    if session:
        parts.append(f"{session['label']} at {fmt_time(session['start'])}")
    meals = read_json(food.state_dir(sample) / "meals.json")
    for r in (meals.get("plan") or {}).get("recipes", []):
        for c in r["covers"]:
            d_, meal = c.split()
            if d_ == nxt.isoformat():
                cook = r["cook"] == nxt.isoformat() and c == r["covers"][0]
                parts.append(f"{meal}: {'cook ' if cook else ''}{r['name']}")
    for f in meals.get("fixed", []):
        if f["date"] == nxt.isoformat():
            parts.append(f"{f['meal']}: {f['note']}")
    return "Tomorrow: " + " · ".join(parts) if parts else None


def protein_idea(sample, rows=None):
    """The most protein-dense thing in the pantry, with a usual portion, for a 'how to fix it' hint."""
    pantry = read_json(food.state_dir(sample) / "meals.json").get("pantry", [])
    best = None
    for item in pantry:
        ranked = food.rank_foods(item["name"], rows, ingredient=True) if rows is not None else []
        if not ranked or not ranked[0]["protein"]:
            continue
        row = ranked[0]
        portion = next((p for p in row["portions"].split("|") if p), "")
        grams = float(portion.rsplit("=", 1)[1]) if portion else 100
        label = portion.rsplit("=", 1)[0] if portion else "100 g"
        protein = row["protein"] * grams / 100
        if best is None or protein > best[1]:
            best = (f"{item['name']} ({label}, ~{protein:.0f} g protein)", protein)
    return best[0] if best and best[1] >= 8 else None


# ---------- formatting ----------

def fmt_time(hhmm):
    h, m = map(int, hhmm.split(":"))
    suffix = "am" if h < 12 else "pm"
    h = h % 12 or 12
    return f"{h}{'' if m == 0 else f':{m:02d}'} {suffix}"


def n(x):
    return f"{x:,.0f}"


def vs(value, goal, unit=""):
    return f"{n(value)} / {n(goal)}{unit}" if goal else f"{n(value)}{unit}"


def pct(value, goal):
    return value / goal if goal else None


# ---------- insights ----------

def day_insights(t, goals, count, sample, rows):
    """One win and one thing to focus on, at most. Never pushes eating less than the goal."""
    wins, focus = [], []
    kcal, prot, fiber = pct(t["kcal"], goals.get("kcal")), pct(t["protein"], goals.get("protein")), \
        pct(t["fiber"], goals.get("fiber"))
    if count <= 1:
        focus.append(f"Only {count} meal logged. Was that everything? Text me anything you missed.")
    if prot is not None:
        if prot >= 0.95:
            wins.append("protein goal hit ✅")
        elif prot < 0.8:
            idea = protein_idea(sample, rows)
            short = goals["protein"] - t["protein"]
            focus.append(f"{n(short)} g short on protein" + (f"; easy add: {idea}" if idea else ""))
    if kcal is not None and count > 1:
        if 0.9 <= kcal <= 1.1:
            wins.append("calories right on target")
        elif kcal < 0.75:
            focus.append("well under your calories; make sure you're eating enough to recover")
        elif kcal > 1.15:
            focus.append(f"{n(t['kcal'] - goals['kcal'])} kcal over; no stress, tomorrow's a new day")
    if fiber is not None and fiber < 0.6 and count > 1:
        focus.append("fiber is low; beans, oats, berries or veggies help")
    if t["sodium"] > SODIUM_LIMIT * 1.3:
        focus.append(f"sodium {n(t['sodium'])} mg (guideline {n(SODIUM_LIMIT)}); drink extra water")
    return wins[:1], focus[:1]


def protein_streak(state, end_day, cfg):
    goal = state["goals"].get("protein")
    if not goal:
        return 0
    streak, day = 0, end_day
    while streak < 60:
        end = window_end(day, cfg)
        t = total(entries_between(state, end - timedelta(days=1), end))
        if t["protein"] < goal * 0.95:
            return streak
        streak += 1
        day -= timedelta(days=1)
    return streak


# ---------- day ----------

def cmd_day(args):
    state = food.load_state(args.sample)
    cfg = settings(state)
    day = food_date(args.date)
    end = window_end(day, cfg)
    start = end - timedelta(days=1)
    entries = entries_between(state, start, end)
    t, goals = total(entries), state["goals"]
    if args.detail:
        print_day_detail(day, start, end, entries, t, goals, args.sample)
        return
    print(f"Today ({day:%a} {day.month}/{day.day})")
    if not entries:
        print("Nothing logged since yesterday at " + fmt_time(cfg["time"]) + ". Want to add what you ate?")
        return
    print(f"{vs(t['kcal'], goals.get('kcal'), ' kcal')} · {vs(t['protein'], goals.get('protein'), ' g')} protein")
    print(f"C {n(t['carbs'])} g · F {n(t['fat'])} g · fiber {vs(t['fiber'], goals.get('fiber'), ' g')}")
    rows = list(food.load_foods()) if goals.get("protein") and t["protein"] < goals["protein"] * 0.8 else None
    wins, focus = day_insights(t, goals, len(entries), args.sample, rows)
    streak = protein_streak(state, day, cfg)
    if streak >= 2:
        wins = [f"protein goal {streak} days in a row 🔥"]
    if wins:
        print("Win: " + wins[0])
    if focus:
        print("Focus: " + focus[0])
    if not goals:
        print("Set daily goals to see how you're tracking.")
    line = tomorrow_line(day, args.sample)
    if line:
        print(line)
    print('Reply "details" for the full breakdown.')


def print_day_detail(day, start, end, entries, t, goals, sample):
    print(f"{day:%a} {day.month}/{day.day} in detail ({fmt_time(start.strftime('%H:%M'))} {start:%a} "
          f"to {fmt_time(end.strftime('%H:%M'))} {end:%a})")
    if not entries:
        print("Nothing logged in this window.")
        return
    print("Meals:")
    for e in entries:
        when = fmt_time(e["when"].strftime("%H:%M")) if e.get("time") else "time not logged"
        print(f"- {when} {e['meal']}: {n(e['total']['kcal'])} kcal, P {n(e['total']['protein'])} g")
    print("Totals vs goal:")
    for k, unit in [("kcal", " kcal"), ("protein", " g"), ("carbs", " g"), ("fat", " g"), ("fiber", " g")]:
        p = pct(t[k], goals.get(k))
        print(f"- {k if k != 'kcal' else 'calories'}: {vs(t[k], goals.get(k), unit)}" + (f" ({p:.0%})" if p else ""))
    print(f"- sugar: {n(t['sugar'])} g · sodium: {n(t['sodium'])} mg (guideline {n(SODIUM_LIMIT)})")
    macro_kcal = {k: t[k] * v for k, v in MACRO_KCAL.items()}
    s = sum(macro_kcal.values()) or 1
    print("Calories from: " + " · ".join(f"{k} {v / s:.0%}" for k, v in macro_kcal.items()))
    top = sorted(entries, key=lambda e: -e["total"]["kcal"])[:3]
    print("Biggest: " + ", ".join(f"{e['meal']} ({n(e['total']['kcal'])})" for e in top))
    print("Protein by meal: " + ", ".join(f"{e['meal']} {n(e['total']['protein'])} g" for e in entries))
    timed = [e for e in entries if e.get("time")]
    if len(timed) >= 2:
        first, last = timed[0]["when"], timed[-1]["when"]
        print(f"Eating window: {fmt_time(first.strftime('%H:%M'))} {first:%a} to {fmt_time(last.strftime('%H:%M'))} "
              f"{last:%a}")
    note = workout_note(day, sample)
    if note:
        print(f"Workout: {note}")


# ---------- week ----------

def week_stats(state, end_day, cfg):
    days = []
    for i in range(6, -1, -1):
        day = end_day - timedelta(days=i)
        end = window_end(day, cfg)
        entries = entries_between(state, end - timedelta(days=1), end)
        days.append({"day": day, "entries": entries, "total": total(entries)})
    logged = [x for x in days if x["entries"]]
    avg = {k: sum(x["total"][k] for x in logged) / len(logged) for k in food.KEYS} if logged else None
    return days, logged, avg


def cmd_week(args):
    state = food.load_state(args.sample)
    cfg = settings(state)
    end_day = food_date(args.date)
    goals = state["goals"]
    days, logged, avg = week_stats(state, end_day, cfg)
    _, prev_logged, prev_avg = week_stats(state, end_day - timedelta(days=7), cfg)
    start_day = end_day - timedelta(days=6)
    label = f"{start_day.month}/{start_day.day}–{end_day.month}/{end_day.day}"
    if not logged:
        print(f"Week {label}: nothing logged. Want to restart with one meal tomorrow?")
        return
    hit = sum(1 for x in logged if goals.get("protein") and x["total"]["protein"] >= goals["protein"] * 0.95)
    if args.detail:
        print_week_detail(label, days, logged, avg, prev_avg, goals, state, end_day, args.sample)
        return
    print(f"Week {label}: logged {len(logged)}/7 days")
    print(f"Avg {vs(avg['kcal'], goals.get('kcal'), ' kcal')} · {vs(avg['protein'], goals.get('protein'), ' g')} "
          "protein a day")
    if goals.get("protein"):
        print(f"Protein goal hit {hit}/7 days")
    if prev_avg:
        dk, dp = avg["kcal"] - prev_avg["kcal"], avg["protein"] - prev_avg["protein"]
        print(f"vs last week: {dk:+,.0f} kcal, {dp:+,.0f} g protein a day")
    wins, focus = week_insights(days, logged, avg, prev_avg, goals, hit)
    if wins:
        print("Win: " + wins[0])
    if focus:
        print("Focus: " + focus[0])
    print('Reply "week details" for the full breakdown.')


def week_insights(days, logged, avg, prev_avg, goals, hit):
    wins, focus = [], []
    if len(logged) == 7:
        wins.append("logged every day this week")
    if goals.get("protein") and hit >= 5:
        wins.append(f"protein on point {hit} of 7 days")
    if prev_avg and avg["fiber"] > prev_avg["fiber"] * 1.15:
        wins.append(f"fiber up {avg['fiber'] / prev_avg['fiber'] - 1:.0%} from last week")
    weekend = [x["total"]["kcal"] for x in days if x["entries"] and x["day"].weekday() >= 5]
    weekday = [x["total"]["kcal"] for x in days if x["entries"] and x["day"].weekday() < 5]
    if weekend and weekday and sum(weekend) / len(weekend) > sum(weekday) / len(weekday) + 500:
        focus.append(f"weekends run ~{n(sum(weekend) / len(weekend) - sum(weekday) / len(weekday))} kcal higher "
                     "than weekdays; meal prep Friday can help")
    if goals.get("kcal") and avg["kcal"] < goals["kcal"] * 0.75 and len(logged) >= 4:
        focus.append("averaging well under your calories; check you're eating enough (or logging everything)")
    if goals.get("protein") and hit <= 2 and len(logged) >= 4:
        focus.append("protein was short most days; a protein source at every meal is the easiest fix")
    if len(logged) < 4:
        focus.append(f"only {len(logged)} days logged; even a quick photo a day makes this report useful")
    if goals.get("fiber") and avg["fiber"] < goals["fiber"] * 0.6:
        focus.append("fiber is low most days; add beans, oats or veggies to one meal")
    return wins[:1], focus[:1]


def print_week_detail(label, days, logged, avg, prev_avg, goals, state, end_day, sample):
    print(f"Week {label} in detail")
    for x in days:
        t = x["total"]
        if not x["entries"]:
            print(f"- {x['day']:%a}: nothing logged")
            continue
        mark = " ✓" if goals.get("protein") and t["protein"] >= goals["protein"] * 0.95 else ""
        print(f"- {x['day']:%a}: {n(t['kcal'])} kcal, P {n(t['protein'])} g, C {n(t['carbs'])} g, "
              f"F {n(t['fat'])} g, fiber {n(t['fiber'])} g{mark}")
    print("Daily average vs goal:")
    for k, unit in [("kcal", " kcal"), ("protein", " g"), ("carbs", " g"), ("fat", " g"), ("fiber", " g")]:
        line = f"- {k if k != 'kcal' else 'calories'}: {vs(avg[k], goals.get(k), unit)}"
        if prev_avg:
            line += f" (last week {n(prev_avg[k])})"
        print(line)
    print(f"- sodium: {n(avg['sodium'])} mg a day (guideline {n(SODIUM_LIMIT)})")
    best = max(logged, key=lambda x: x["total"]["protein"])
    print(f"Best protein day: {best['day']:%a} ({n(best['total']['protein'])} g)")
    counts = {}
    for x in logged:
        for e in x["entries"]:
            counts[e["meal"]] = counts.get(e["meal"], 0) + 1
    regulars = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    print("Most logged: " + ", ".join(f"{m} (x{c})" for m, c in regulars))
    prepped = sum(1 for x in logged for e in x["entries"] if e["meal"].endswith("(meal prep)"))
    if prepped:
        print(f"Meal-prep meals eaten: {prepped}")
    workouts = read_json(food.state_dir(sample) / "workouts.json")
    planned = len((workouts.get("plan") or {}).get("schedule") or [])
    start = (end_day - timedelta(days=6)).isoformat()
    done = sum(1 for h in workouts.get("history", []) if start <= h["date"] <= end_day.isoformat())
    if planned or done:
        print(f"Workouts: {done}" + (f"/{planned} planned" if planned else ""))


# ---------- auto / settings ----------

def cmd_auto(args):
    state = food.load_state(args.sample)
    cfg = settings(state)
    day = food_date(args.date)
    if WEEKDAYS[day.weekday()] == cfg["week_day"]:
        cmd_week(argparse.Namespace(date=args.date, detail=False, sample=args.sample))
        print()
    cmd_day(argparse.Namespace(date=args.date, detail=False, sample=args.sample))


def cmd_settings(args):
    state = food.load_state(args.sample)
    cfg = state.setdefault("report", {})
    if args.time:
        try:
            datetime.strptime(args.time, "%H:%M")
        except ValueError:
            raise Problem("--time is HH:MM in 24-hour time, e.g. 21:00.")
        cfg["time"] = args.time
    if args.week_day:
        if args.week_day[:3].lower() not in WEEKDAYS:
            raise Problem("--week-day is a day name, e.g. sun.")
        cfg["week_day"] = args.week_day[:3].lower()
    food.save_state(state, args.sample)
    cfg = settings(state)
    print(f"Daily report at {fmt_time(cfg['time'])} covering the 24 hours before it; weekly report on "
          f"{cfg['week_day'].title()}.")


def food_date(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise Problem(f'"{text}" isn\'t a date; use YYYY-MM-DD.')


def main(argv=None):
    ap = argparse.ArgumentParser(description="fitness-coach diet reports")
    ap.add_argument("--sample", action="store_true", help="separate saved state for trying things out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    today_iso = date.today().isoformat()
    for name, func in [("day", cmd_day), ("week", cmd_week)]:
        p = sub.add_parser(name)
        p.add_argument("--date", default=today_iso)
        p.add_argument("--detail", action="store_true")
        p.set_defaults(func=func)
    a = sub.add_parser("auto")
    a.add_argument("--date", default=today_iso)
    a.set_defaults(func=cmd_auto)
    s = sub.add_parser("settings")
    s.add_argument("--time")
    s.add_argument("--week-day")
    s.set_defaults(func=cmd_settings)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except food.Problem as e:
        print(f"ERROR: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
