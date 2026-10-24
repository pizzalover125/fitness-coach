---
name: snap-macros
description: Logs meals from a food photo, a barcode or a quick text and replies with calories, protein, carbs, fat, fiber and sugar, keeping a running daily total against the student's goals. Use whenever the student sends a photo of food, a plate, a dining hall tray, a snack, a barcode or a nutrition label, asks how many calories or how much protein is in something, says what they ate ("had 2 eggs and toast"), asks what they have left today, or mentions macros, cutting, bulking or hitting protein for the gym, even if they never say "calories".
---

# Snap Macros

The moment: walking out of the dining hall after a lift, the student snaps their tray and wants to know whether
they hit their protein. They send a photo; a few seconds later they have the numbers and today's total.

Nutrition comes from two free sources, with no sign-in:
- **USDA FoodData Central**: 13,000 foods and dishes, bundled offline in `assets/foods.tsv.gz`.
- **Open Food Facts**: packaged products looked up by barcode over HTTPS.

The numbers are estimates. Say so once, early on, and never present them as exact.

## Setup (optional, for barcode photos)

```bash
python3 -m venv ~/.local/share/venvs/snap-macros && ~/.local/share/venvs/snap-macros/bin/pip install zxing-cpp==3.1.1 pillow==12.3.0
```

Everything else uses only the standard library. If Setup fails, the Skill still works: read the digits printed
under the barcode instead of decoding the image.

## Running the script

Run every command from this Skill's folder as `python3 scripts/snap.py ...`. Always pass the student's **local**
date as `--date YYYY-MM-DD` (and `--time HH:MM` when logging). The sandbox clock may be in another time zone.

The script prints a short result. Lines starting with `ERROR:` are written for you. The exit codes are:

| Exit | Meaning |
|---|---|
| 0 | OK |
| 2 | Bad input or not found |
| 3 | Barcode decoder not installed |
| 4 | Network error |

## 1. A photo of a meal

1. **Look at the photo carefully.** List every food you see, how it was cooked, and its weight in grams.
   - Judge size from what's around it: a dinner plate is about 26 cm across, a fork about 19 cm, a soda can
     12 fl oz, and a palm-sized piece of meat about 100 g.
   - Count pieces you can count (3 eggs, 2 slices).
   - Include what adds hidden calories: cooking oil on glossy food, butter, dressing, sauce, cheese, and the drink.
2. **If there's a barcode or a Nutrition Facts label** in the photo, go to section 2 instead.
3. **If it's from a chain restaurant** whose official nutrition is published (Chipotle, Starbucks,
   Chick-fil-A...), or from a dining hall that posts nutrition:
   1. Search the web for the official numbers.
   2. Log them with `--custom` (see the custom line format in section 2).
4. **Otherwise, look up each food:**
   1. Run `python3 scripts/snap.py search "<food and cooking method>"`. For example, "chicken breast grilled",
      "white rice cooked", "broccoli steamed".
   2. Pick the closest match. Prefer one with the same cooking method, and with skin, sauce or oil as you saw it.
   3. Use the portions it lists to turn counts into grams (`1 large egg = 50 g`).
   4. If nothing fits, search again with a simpler name.
5. **Log the meal as one entry, right away. Don't ask questions first.**

   ```bash
   python3 scripts/snap.py log --date 2026-10-24 --time 12:30 --meal "Chicken rice bowl" --food 2705968=150 --food 2708422=200
   ```

6. **Reply** (see Replies). Name your two or three biggest guesses so the student can correct them.

Ask before logging only when you can't tell what the food is at all. When a detail changes the numbers a lot
(regular or diet soda, whole or skim milk), log your best guess and name the assumption.

## 2. A barcode or a label

1. **Barcode photo:** run `python3 scripts/snap.py barcode --image <path to the photo>`.
   - If it exits with 3 (no decoder), or you can't get the photo as a file, read the digits printed under the
     barcode and run `python3 scripts/snap.py barcode <digits>`.
   - If it says the check digit fails, the digits were misread. Look again, or ask for a closer photo.
2. **Found:** it prints the product, its per-serving numbers, and the exact `--product` argument to log with.
   - Log 1 serving unless the student said how much: `python3 scripts/snap.py log --date ... --product <code>=1srv`.
   - For other amounts, use `<code>=2srv` for 2 servings or `<code>=50` for 50 g.
3. **Not found, or no nutrition data:**
   1. Ask for a photo of the Nutrition Facts label.
   2. Read calories, protein, total carbs, fat, fiber, sugars and sodium per serving.
   3. Multiply by the servings eaten.
   4. Log it with a custom line, where the numbers are for the amount eaten (sodium in mg):
      `--custom "<name>;<kcal>;<protein>;<carbs>;<fat>;<fiber>;<sugar>;<sodium>"`
4. **A label photo on its own** (no barcode): do the same as step 3.

Open Food Facts is crowdsourced. If a number looks impossible (a protein bar with 0 protein), say it looks off,
and offer to log from the label instead.

## 3. Text or voice ("had 2 eggs, toast and a latte")

Do the same as section 1 without the photo. Use the amounts the student gave, or typical portions from `search`.
If they ask about a food without saying they ate it ("how much protein in 200 g of chicken?"), run `search`,
answer, and offer "Log it?". Don't log until they say so.

## 4. Corrections

When the student corrects an entry ("it was 2 eggs", "no oil", "half the rice", "that wasn't mine"):

1. Run `python3 scripts/snap.py undo --date <date>`.
2. Log the corrected meal again. Skip this if they said not to log it.
3. Reply with the new numbers.

Don't argue with the student's correction.

## 5. Goals, check-ins and recaps

- **Goals.** When the log output says `(no daily goals set)`, offer once, after the first meal: "Want daily
  targets? Tell me cut, maintain or bulk, plus your age, height, weight and training days a week."
  - Then run `python3 scripts/snap.py goals --calc --goal bulk --sex male --age 20 --weight-lb 170 --height-in 70 --activity 3-4`.
    The `--activity` values are 0, 1-2, 3-4, 5-6 or 7 training days. `--sex` is male, female or other.
  - Students who know their numbers can set them directly: `python3 scripts/snap.py goals --kcal 2400 --protein 160`.
  - Running `goals` with no options shows the current goals.
- **Today / this week.** For "what's left today?" or "how was my week?", run
  `python3 scripts/snap.py today --date <date>` or `python3 scripts/snap.py week --date <date>`.
- **Evening recap.** After goals are set, offer once: "Want a quick recap at 9 pm with what's left? yes / other
  time / no". Create a daily check-in only after the student says yes. Write the check-in so it stands on its own:
  "Snap Macros evening recap: from the snap-macros Skill folder run `python3 scripts/snap.py today --date <today's
  date>`. In two short lines, text the student the calories and protein left. Add one food idea that fits.
  Skip the text if nothing was logged today."

## Replies

- Keep it to a few short lines of plain text, with no Markdown symbols.
- Lead with the meal's calories, then the macros on one line, then today's total vs the goal.
- Round: calories to the nearest 5 or 10, grams to whole numbers. Use "~" for photo estimates.
- End with one line naming your biggest guess and how to fix it.

```text
Chicken rice bowl ~ 460 kcal
P 48g · C 42g · F 9g · fiber 2g

Today: 460 / 3,050 kcal · 48 / 139g protein

Guessed 150 g chicken + 1 cup rice. Off? Reply "less rice" or "undo".
```

Barcode reply:

```text
Clif Bar, chocolate chip: 250 kcal
P 10g · C 43g · F 6g · fiber 5g

Logged 1 bar. Had 2? Reply "2 bars".
```

## Care

- These are estimates for students who want to track food, not medical advice.
- Never comment on the student's body, and never shame a food choice.
- Never suggest eating below the goal that `goals --calc` sets. It already has a floor.
- If the student talks about eating very little, skipping meals to make up for food, purging, or feeling bad about
  eating:
  - Stop pushing numbers.
  - Respond kindly.
  - Suggest talking to someone at campus health or counseling.

## When something fails

- **Network error (exit 4):** try once more. Then send: "Couldn't reach the barcode database. Tell me what it is,
  or send a photo of the nutrition label."
- **No USDA match after two searches:** estimate from the web or your own knowledge. Log it with `--custom`, and
  say "(rough estimate)".
- **Photo too dark or blurry to tell what it is:** "Can't make that one out. What is it?"
- Never invent a barcode, a product, or label numbers you didn't read.
