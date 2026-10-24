#!/usr/bin/env python3
"""fitness-coach workouts: exercise lookup, weekly plans, calendar slots and a workout log.

Standard library only. Exercise data: free-exercise-db (public domain), bundled in assets/.

Commands (dates are the student's local date, YYYY-MM-DD; times are local HH:MM):
  find [--muscle chest] [--equipment gym|dumbbells|bodyweight] [--level beginner] [--query row]
  show "<exercise id or name>"          Steps and a form photo link
  plan --days 3 --goal muscle --equipment gym --level beginner --minutes 60
  schedule --week-start D [--busy busy.json] [--window 07:00-22:00] [--prefer evening]
           [--weekdays mon,wed,fri] [--weeks 4] [--reminder 60]
  today --date D                        The session planned for that day, or the next one
  done --date D [--note "squat 135x5"]  Log a finished workout
  history [--limit 10]

busy.json: [{"start": "2026-10-26T09:00", "end": "2026-10-26T10:15"}, ...] in the student's local time.

Exit codes: 0 ok, 2 bad input or not found.
"""

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
EXERCISES_FILE = SKILL_DIR / "assets" / "exercises.json.gz"
IMAGE_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/{}"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class Problem(Exception):
    pass


# ---------- state ----------

def state_dir(sample):
    base = Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "fitness-coach")
    return base / "sample" if sample else base


def load_state(sample):
    path = state_dir(sample) / "workouts.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"plan": None, "history": []}


def save_state(state, sample):
    folder = state_dir(sample)
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, folder / "workouts.json")


# ---------- exercises ----------

def load_exercises():
    with gzip.open(EXERCISES_FILE, "rt", encoding="utf-8") as fh:
        return {ex["id"]: ex for ex in json.load(fh)}


MUSCLE_GROUPS = {
    "back": {"lats", "middle back", "lower back", "traps"},
    "legs": {"quadriceps", "hamstrings", "glutes", "calves", "adductors", "abductors"},
    "arms": {"biceps", "triceps", "forearms"},
    "abs": {"abdominals"}, "core": {"abdominals", "lower back"},
    "quads": {"quadriceps"}, "glute": {"glutes"}, "shoulder": {"shoulders"}, "delts": {"shoulders"},
    "bicep": {"biceps"}, "tricep": {"triceps"}, "calf": {"calves"}, "hamstring": {"hamstrings"}, "lat": {"lats"},
}
EQUIPMENT_TIERS = {
    "bodyweight": {"body only", None},
    "dumbbells": {"dumbbell", "body only", None},
    "gym": None,  # anything
}


def muscles_for(name):
    name = name.lower().strip()
    return MUSCLE_GROUPS.get(name) or MUSCLE_GROUPS.get(name.rstrip("s")) or {name}


def cmd_find(args):
    exercises = load_exercises().values()
    out = []
    for ex in exercises:
        if args.muscle and not (muscles_for(args.muscle) & set(ex["primaryMuscles"])):
            continue
        tier = EQUIPMENT_TIERS.get(args.equipment, {args.equipment}) if args.equipment else None
        if tier is not None and ex["equipment"] not in tier:
            continue
        if args.level and ex["level"] != args.level:
            continue
        if args.category and ex["category"] != args.category:
            continue
        if not args.category and ex["category"] in ("stretching", "strongman", "olympic weightlifting"):
            continue
        if args.query and not all(w in ex["name"].lower() for w in args.query.lower().split()):
            continue
        out.append(ex)
    if not out:
        raise Problem("No exercises match. Drop a filter (level or equipment) and try again.")
    levels = {"beginner": 0, "intermediate": 1, "expert": 2}
    exact = {"dumbbells": "dumbbell", "bodyweight": "body only"}.get(args.equipment)
    out.sort(key=lambda ex: (exact is not None and ex["equipment"] != exact, levels[ex["level"]],
                             ex["mechanic"] != "compound", len(ex["name"])))
    for ex in out[:args.limit]:
        print(f"{ex['id']} | {ex['name']} | {ex['equipment'] or 'none'} | {ex['level']} | "
              f"{', '.join(ex['primaryMuscles'])}")
    if len(out) > args.limit:
        print(f"({len(out) - args.limit} more; add filters to narrow down)")


def find_exercise(key, exercises):
    if key in exercises:
        return exercises[key]
    want = key.lower().replace("_", " ").strip()
    for ex in exercises.values():
        if ex["name"].lower() == want:
            return ex
    hits = [ex for ex in exercises.values() if all(w in ex["name"].lower() for w in want.split())]
    if hits:
        return min(hits, key=lambda ex: len(ex["name"]))
    raise Problem(f'No exercise called "{key}". Use find to look it up.')


def cmd_show(args):
    ex = find_exercise(args.exercise, load_exercises())
    print(f"{ex['name']} ({ex['level']}, {ex['equipment'] or 'no equipment'})")
    print(f"Works: {', '.join(ex['primaryMuscles'] + ex['secondaryMuscles'])}")
    for i, step in enumerate(ex["instructions"], 1):
        print(f"{i}. {step}")
    if ex["image"]:
        print(f"Photo: {IMAGE_URL.format(ex['image'])}")


# ---------- plans ----------

# Staple exercises by movement, per equipment tier, in order of preference.
POOLS = {
    "gym": {
        "squat": ["Barbell_Squat", "Leg_Press", "Goblet_Squat"],
        "hinge": ["Romanian_Deadlift", "Barbell_Deadlift", "Stiff-Legged_Dumbbell_Deadlift"],
        "hpush": ["Barbell_Bench_Press_-_Medium_Grip", "Dumbbell_Bench_Press"],
        "incline": ["Incline_Dumbbell_Press"],
        "vpush": ["Dumbbell_Shoulder_Press", "Standing_Military_Press"],
        "hpull": ["Seated_Cable_Rows", "One-Arm_Dumbbell_Row", "Bent_Over_Barbell_Row"],
        "vpull": ["Wide-Grip_Lat_Pulldown", "Pullups"],
        "lunge": ["Split_Squat_with_Dumbbells", "Dumbbell_Lunges", "Dumbbell_Step_Ups"],
        "glute": ["Barbell_Hip_Thrust"],
        "quad": ["Leg_Extensions"],
        "ham": ["Lying_Leg_Curls"],
        "calves": ["Standing_Calf_Raises", "Seated_Calf_Raise"],
        "lateral": ["Side_Lateral_Raise"],
        "reardelt": ["Face_Pull", "Reverse_Flyes"],
        "biceps": ["Barbell_Curl", "Hammer_Curls"],
        "triceps": ["Triceps_Pushdown_-_Rope_Attachment", "Dips_-_Triceps_Version"],
        "fly": ["Butterfly", "Dumbbell_Flyes"],
        "core": ["Plank", "Cable_Crunch", "Flat_Bench_Lying_Leg_Raise"],
        "finisher": ["Rope_Jumping", "Mountain_Climbers"],
    },
    "dumbbells": {
        "squat": ["Goblet_Squat"],
        "hinge": ["Stiff-Legged_Dumbbell_Deadlift"],
        "hpush": ["Dumbbell_Bench_Press", "Pushups"],
        "incline": ["Incline_Dumbbell_Press", "Pushups"],
        "vpush": ["Dumbbell_Shoulder_Press", "Arnold_Dumbbell_Press"],
        "hpull": ["One-Arm_Dumbbell_Row", "Bent_Over_Two-Dumbbell_Row"],
        "vpull": ["Bent_Over_Two-Dumbbell_Row", "One-Arm_Dumbbell_Row"],
        "lunge": ["Dumbbell_Lunges", "Split_Squat_with_Dumbbells", "Dumbbell_Step_Ups"],
        "glute": ["Single_Leg_Glute_Bridge"],
        "calves": ["Standing_Dumbbell_Calf_Raise"],
        "lateral": ["Side_Lateral_Raise"],
        "reardelt": ["Reverse_Flyes"],
        "biceps": ["Dumbbell_Bicep_Curl", "Hammer_Curls"],
        "triceps": ["Bench_Dips"],
        "fly": ["Dumbbell_Flyes"],
        "core": ["Plank", "Russian_Twist", "Side_Bridge"],
        "finisher": ["Mountain_Climbers"],
    },
    "bodyweight": {
        "squat": ["Bodyweight_Squat"],
        "hinge": ["Single_Leg_Glute_Bridge"],
        "hpush": ["Pushups", "Incline_Push-Up"],
        "incline": ["Incline_Push-Up"],
        "hpull": ["Inverted_Row"],
        "vpull": ["Chin-Up", "Pullups"],
        "lunge": ["Bodyweight_Walking_Lunge"],
        "glute": ["Single_Leg_Glute_Bridge"],
        "triceps": ["Bench_Dips"],
        "core": ["Plank", "Side_Bridge", "Superman", "Flat_Bench_Lying_Leg_Raise"],
        "finisher": ["Mountain_Climbers"],
    },
}
MAIN_SLOTS = {"squat", "hinge", "hpush", "incline", "vpush", "hpull", "vpull"}
# (slot, variant): variant picks the 2nd/3rd option so repeated days aren't identical.
TEMPLATES = {
    "Full Body A": [("squat", 0), ("hpush", 0), ("hpull", 0), ("hinge", 0), ("lateral", 0), ("core", 0)],
    "Full Body B": [("hinge", 1), ("vpush", 0), ("vpull", 0), ("lunge", 0), ("biceps", 0), ("core", 1)],
    "Full Body C": [("squat", 1), ("incline", 0), ("hpull", 1), ("glute", 0), ("triceps", 0), ("core", 2)],
    "Upper A": [("hpush", 0), ("hpull", 0), ("vpush", 0), ("vpull", 0), ("triceps", 0), ("biceps", 0)],
    "Upper B": [("incline", 0), ("vpull", 1), ("hpull", 1), ("lateral", 0), ("reardelt", 0), ("biceps", 1)],
    "Lower A": [("squat", 0), ("hinge", 0), ("lunge", 0), ("quad", 0), ("calves", 0), ("core", 0)],
    "Lower B": [("hinge", 1), ("squat", 1), ("glute", 0), ("ham", 0), ("calves", 1), ("core", 1)],
    "Push": [("hpush", 0), ("vpush", 0), ("incline", 0), ("lateral", 0), ("triceps", 0), ("fly", 0)],
    "Pull": [("vpull", 0), ("hpull", 0), ("hpull", 1), ("reardelt", 0), ("biceps", 0), ("biceps", 1)],
    "Legs": [("squat", 0), ("hinge", 0), ("lunge", 0), ("ham", 0), ("calves", 0), ("core", 0)],
}
SPLITS = {
    1: [("Full Body A", 0)],
    2: [("Full Body A", 0), ("Full Body B", 0)],
    3: [("Full Body A", 0), ("Full Body B", 0), ("Full Body C", 0)],
    4: [("Upper A", 0), ("Lower A", 0), ("Upper B", 0), ("Lower B", 0)],
    5: [("Upper A", 0), ("Lower A", 0), ("Push", 1), ("Pull", 1), ("Legs", 1)],
    6: [("Push", 0), ("Pull", 0), ("Legs", 0), ("Push", 1), ("Pull", 1), ("Legs", 1)],
}
GOALS = {  # (sets, reps, rest) for main lifts and for accessories
    "strength": {"main": (4, "5", "2-3 min"), "acc": (3, "8", "90 s")},
    "muscle": {"main": (3, "8-10", "90 s"), "acc": (3, "10-15", "60 s")},
    "fat-loss": {"main": (3, "10-12", "60 s"), "acc": (3, "12-15", "45 s"), "finisher": True},
    "general": {"main": (3, "8-12", "90 s"), "acc": (2, "12-15", "60 s"), "finisher": True},
}
TIMED = {"Plank", "Side_Bridge"}


def pick(slot, variant, pool, level, exercises, used):
    candidates = pool.get(slot, [])
    if level == "beginner":
        easy = [c for c in candidates if exercises[c]["level"] == "beginner"]
        candidates = easy or candidates
    ordered = candidates[variant % len(candidates):] + candidates[:variant % len(candidates)] if candidates else []
    return next((c for c in ordered if c not in used), None)


def build_day(template, offset, label, args, exercises):
    pool, goal = POOLS[args.equipment], GOALS[args.goal]
    count = 3 if args.minutes <= 30 else 4 if args.minutes <= 45 else 5 if args.minutes <= 60 else 6
    used, items = set(), []
    for slot, variant in TEMPLATES[template]:
        ex_id = pick(slot, variant + offset, pool, args.level, exercises, used)
        if not ex_id:
            continue
        used.add(ex_id)
        sets, reps, rest = goal["main" if slot in MAIN_SLOTS else "acc"]
        if args.level == "beginner":
            sets = min(sets, 3)
        if ex_id in TIMED:
            reps = "30-45 s"
        items.append({"id": ex_id, "name": exercises[ex_id]["name"], "sets": sets, "reps": reps, "rest": rest})
        if len(items) == count:
            break
    finisher = None
    if goal.get("finisher") and pool.get("finisher"):
        finisher = f"Finisher: 8 rounds of 30 s {exercises[pool['finisher'][0]]['name']}, 30 s rest"
    return {"label": label, "exercises": items, "finisher": finisher}


def fmt_day(day):
    lines = [day["label"]]
    for i, ex in enumerate(day["exercises"], 1):
        lines.append(f"  {i}. {ex['name']}: {ex['sets']} x {ex['reps']}, rest {ex['rest']}")
    if day.get("finisher"):
        lines.append(f"  {day['finisher']}")
    return "\n".join(lines)


def cmd_plan(args):
    if args.days not in SPLITS:
        raise Problem("--days must be 1 to 6. Plan at least one rest day a week.")
    exercises = load_exercises()
    split = SPLITS[args.days]
    templates = [t for t, _ in split]
    days = [build_day(t, off, t + (" 2" if templates[:i].count(t) else ""), args, exercises)
            for i, (t, off) in enumerate(split)]
    state = load_state(args.sample)
    state["plan"] = {"goal": args.goal, "level": args.level, "equipment": args.equipment,
                     "minutes": args.minutes, "days": days, "schedule": []}
    save_state(state, args.sample)
    print(f"{args.days}-day {args.goal} plan, {args.equipment}, {args.level}, ~{args.minutes} min:")
    for day in days:
        print(fmt_day(day))
    if args.equipment == "bodyweight" and any(ex["id"] in ("Chin-Up", "Pullups") for d in days for ex in d["exercises"]):
        print("Note: chin-ups need a bar; swap for Inverted Row under a sturdy table if there's none.")
    print("Next: schedule it (schedule --week-start <date> ...).")


# ---------- schedule ----------

PREFER = {"morning": ("06:00", "11:00"), "afternoon": ("11:00", "17:00"), "evening": ("17:00", "22:00"),
          "any": ("00:00", "23:59")}
DEFAULT_WEEKDAYS = {1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 4, 5], 6: [0, 1, 2, 3, 4, 5]}


def hm(text):
    return datetime.strptime(text, "%H:%M").time()


def load_busy(path):
    if not path:
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return [(datetime.fromisoformat(b["start"][:16]), datetime.fromisoformat(b["end"][:16])) for b in raw]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Problem(f"Couldn't read {path} ({e}). Write it as a JSON list of "
                      '{"start": "YYYY-MM-DDTHH:MM", "end": "YYYY-MM-DDTHH:MM"} in local time.')


def find_slot(day, minutes, busy, window, prefer, buffer):
    lo, hi = (datetime.combine(day, hm(t)) for t in window.split("-"))
    p_lo, p_hi = (datetime.combine(day, hm(t)) for t in PREFER[prefer])
    length, pad = timedelta(minutes=minutes), timedelta(minutes=buffer)
    free, start = [], lo
    while start + length <= hi:
        end = start + length
        if all(end + pad <= b0 or start - pad >= b1 for b0, b1 in busy):
            free.append(start)
        start += timedelta(minutes=15)
    preferred = [s for s in free if p_lo <= s and s + length <= p_hi]
    return (preferred or free or [None])[0]


def ics_escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_ics(sessions, plan, weeks, reminder, sample):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//fitness-coach//Cubbie Skill//EN", "CALSCALE:GREGORIAN"]
    for i, s in enumerate(sessions):
        day = next(d for d in plan["days"] if d["label"] == s["label"])
        start = datetime.fromisoformat(f"{s['date']}T{s['start']}")
        end = start + timedelta(minutes=plan["minutes"])
        lines += ["BEGIN:VEVENT", f"UID:fitness-coach-{s['date']}-{i}@cubbie", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}",
                  f"RRULE:FREQ=WEEKLY;COUNT={weeks}", f"SUMMARY:{ics_escape('Workout: ' + s['label'])}",
                  f"DESCRIPTION:{ics_escape(fmt_day(day))}",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(s['label'] + ' in ' + str(reminder) + ' min')}",
                  f"TRIGGER:-PT{reminder}M", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    path = state_dir(sample) / "workout-plan.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def cmd_schedule(args):
    state = load_state(args.sample)
    plan = state.get("plan")
    if not plan:
        raise Problem("No plan yet. Run plan first.")
    week_start = date.fromisoformat(args.week_start)
    n = len(plan["days"])
    if args.weekdays:
        wanted = [WEEKDAYS.index(w.strip()[:3].lower()) for w in args.weekdays.split(",")]
        if len(wanted) != n:
            raise Problem(f"The plan has {n} days but --weekdays lists {len(wanted)}.")
    else:
        wanted = DEFAULT_WEEKDAYS[n]
    # The 7 dates from week_start, keyed by weekday index.
    dates = {(week_start + timedelta(days=i)).weekday(): week_start + timedelta(days=i) for i in range(7)}
    busy = load_busy(args.busy)
    taken, sessions, missed = set(), [], []
    for day, wd in zip(plan["days"], wanted):
        for shift in ([0] if args.weekdays else [0, 1, -1, 2, -2]):
            cand = (wd + shift) % 7
            if cand in taken:
                continue
            start = find_slot(dates[cand], plan["minutes"], busy, args.window, args.prefer, args.buffer)
            if start:
                taken.add(cand)
                sessions.append({"label": day["label"], "date": dates[cand].isoformat(), "weekday": cand,
                                 "start": f"{start:%H:%M}",
                                 "end": f"{start + timedelta(minutes=plan['minutes']):%H:%M}"})
                break
        else:
            missed.append(day["label"])
    sessions.sort(key=lambda s: s["date"])
    plan["schedule"] = sessions
    plan["reminder"] = args.reminder
    save_state(state, args.sample)
    for s in sessions:
        print(f"{DAY_NAMES[s['weekday']]} {s['date']} {s['start']}-{s['end']}: {s['label']}")
    if missed:
        print(f"No free {plan['minutes']}-min slot for: {', '.join(missed)}. Widen --window or pick other --weekdays.")
    if sessions:
        path = write_ics(sessions, plan, args.weeks, args.reminder, args.sample)
        print(f"Calendar file (weekly for {args.weeks} weeks, alert {args.reminder} min before): {path}")
        print("Event details for each session: run today --date <session date>.")


# ---------- log ----------

def session_on(plan, day):
    return next((s for s in plan.get("schedule") or [] if s["weekday"] == day.weekday()), None)


def cmd_today(args):
    state = load_state(args.sample)
    plan = state.get("plan")
    if not plan:
        raise Problem("No plan yet. Run plan first.")
    day = date.fromisoformat(args.date)
    s = session_on(plan, day)
    if not plan.get("schedule"):
        print("Plan isn't scheduled yet. Days in order:")
        for d in plan["days"]:
            print(fmt_day(d))
        return
    if not s:
        nxt = min(plan["schedule"], key=lambda x: (x["weekday"] - day.weekday()) % 7)
        print(f"Rest day. Next: {DAY_NAMES[nxt['weekday']]} {nxt['start']}, {nxt['label']}.")
        return
    done = [h for h in state["history"] if h["date"] == args.date]
    workout = next(d for d in plan["days"] if d["label"] == s["label"])
    print(f"Today {s['start']}-{s['end']}: " + fmt_day(workout) + (" (already logged as done)" if done else ""))
    last = next((h for h in reversed(state["history"]) if h["label"] == s["label"] and h.get("note")), None)
    if last:
        print(f"Last time ({last['date']}): {last['note']}")


def cmd_done(args):
    state = load_state(args.sample)
    plan = state.get("plan") or {}
    s = session_on(plan, date.fromisoformat(args.date)) if plan else None
    label = args.label or (s["label"] if s else "Workout")
    state["history"].append({"date": args.date, "label": label, "note": args.note})
    save_state(state, args.sample)
    start = date.fromisoformat(args.date)
    start -= timedelta(days=start.weekday())
    this_week = sum(1 for h in state["history"] if start.isoformat() <= h["date"] <= args.date)
    planned = len(plan.get("schedule") or [])
    print(f"Logged {label} on {args.date}." + (f" This week: {this_week}/{planned} sessions." if planned else ""))


def cmd_history(args):
    hist = load_state(args.sample)["history"]
    if not hist:
        print("No workouts logged yet.")
    for h in hist[-args.limit:]:
        print(f"{h['date']}: {h['label']}" + (f" ({h['note']})" if h.get("note") else ""))


# ---------- main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="fitness-coach workouts")
    ap.add_argument("--sample", action="store_true", help="separate saved state for trying things out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    today_iso = date.today().isoformat()

    f = sub.add_parser("find")
    f.add_argument("--muscle")
    f.add_argument("--equipment", help="gym, dumbbells, bodyweight, or an exact type such as kettlebells")
    f.add_argument("--level", choices=["beginner", "intermediate", "expert"])
    f.add_argument("--category", help="strength, cardio, stretching, plyometrics...")
    f.add_argument("--query")
    f.add_argument("--limit", type=int, default=8)
    f.set_defaults(func=cmd_find)

    s = sub.add_parser("show")
    s.add_argument("exercise")
    s.set_defaults(func=cmd_show)

    p = sub.add_parser("plan")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--goal", choices=list(GOALS), default="general")
    p.add_argument("--equipment", choices=list(POOLS), default="gym")
    p.add_argument("--level", choices=["beginner", "intermediate"], default="beginner")
    p.add_argument("--minutes", type=int, default=60)
    p.set_defaults(func=cmd_plan)

    sc = sub.add_parser("schedule")
    sc.add_argument("--week-start", default=today_iso)
    sc.add_argument("--busy", help="JSON file of busy times from the student's calendar")
    sc.add_argument("--window", default="07:00-22:00")
    sc.add_argument("--prefer", choices=list(PREFER), default="any")
    sc.add_argument("--weekdays", help="e.g. mon,wed,fri (one per plan day)")
    sc.add_argument("--buffer", type=int, default=15, help="minutes kept free before and after")
    sc.add_argument("--weeks", type=int, default=4)
    sc.add_argument("--reminder", type=int, default=60, help="minutes before")
    sc.set_defaults(func=cmd_schedule)

    t = sub.add_parser("today")
    t.add_argument("--date", default=today_iso)
    t.set_defaults(func=cmd_today)

    d = sub.add_parser("done")
    d.add_argument("--date", default=today_iso)
    d.add_argument("--label")
    d.add_argument("--note")
    d.set_defaults(func=cmd_done)

    h = sub.add_parser("history")
    h.add_argument("--limit", type=int, default=10)
    h.set_defaults(func=cmd_history)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except Problem as e:
        print(f"ERROR: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
