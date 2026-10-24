# Fitness Coach

A [Cubbie](https://cubbie.ai) Skill: a gym and nutrition coach that lives in your iMessage.

- **Track food:** snap a plate, a barcode or a snack, or just text "had 2 eggs and toast". You get calories,
  protein, carbs, fat and fiber, plus today's total against your goals.
- **Plan training:** "3 days a week, gym, new to lifting" becomes a full-body plan built from 876 exercises,
  with form steps and photos on request.
- **Fit it around class:** reads your Google Calendar, finds free slots around your classes, and adds weekly
  workout events once you say yes. No Google? You get a calendar file to tap instead.
- **Keep going:** a text an hour before each session, with last time's numbers. Reply "done" to log it.

```text
You:    3 days a week, gym, I'm new
Cubbie: Here's your plan:
        Mon  Full Body A: Squat, Bench Press, Cable Row
        Wed  Full Body B: RDL, Military Press, Lat Pulldown
        Fri  Full Body C: Leg Press, Incline DB Press, DB Row
        Your calendar is free Mon 6:15 pm, Wed 7 am, Fri 5 pm.
        Add them to Google Calendar, weekly for 4 weeks?
You:    yes
Cubbie: Done. Want a text an hour before each one?
```

## Install

Text this link to Cubbie and reply "yes" when it asks:

```text
https://github.com/pizzalover125/fitness-coach/tree/main/fitness-coach
```

No API keys. Google Calendar is used only if you've already connected Google to Cubbie. Your food and workout
logs stay in your own Cubbie sandbox.

## How it works

| Piece | Source |
| --- | --- |
| Reading food photos | Cubbie's own vision |
| Generic foods and dishes | USDA FoodData Central (SR Legacy + FNDDS 2021–2023), 13,224 foods bundled offline (public domain) |
| Packaged products | Open Food Facts API (barcode and name search), free, no key |
| Barcode photos | [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp); if it isn't installed, Cubbie reads the printed digits |
| Exercises | [free-exercise-db](https://github.com/yuhonas/free-exercise-db), 876 exercises bundled offline (public domain) |
| Plans, free-slot finding, `.ics` file, logs | `fitness-coach/scripts/workouts.py` and `food.py`, standard-library Python |
| Calendar events and reminders | Cubbie's Google Calendar and reminder abilities, after you say yes |

Numbers are estimates, not medical advice.

## Try the scripts locally

```bash
cd fitness-coach
python3 scripts/food.py search "grilled chicken breast"
python3 scripts/food.py --sample barcode 722252100900 --log --date 2026-10-24
python3 scripts/workouts.py --sample plan --days 3 --goal muscle --equipment gym
python3 scripts/workouts.py --sample schedule --week-start 2026-10-26 --prefer evening
python3 scripts/workouts.py --sample today --date 2026-10-26
python3 scripts/workouts.py show "goblet squat"
```

`--sample` keeps its own state, separate from your real logs. To rebuild the bundled data, see `tools/`.

Built for the [Cubbie Hackathon](https://hackathon.cubbie.ai), Track 1.
