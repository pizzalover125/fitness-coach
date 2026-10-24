---
name: snap-macros
description: Logs what the student eats from a food photo, a barcode or a short text and replies with calories, protein, carbs, fat and fiber plus today's running total. Use whenever the student sends a photo of food, a snack, a package, a barcode or a nutrition label, says what they ate, asks how many calories or how much protein something has, asks what they have left today, or talks about macros, cutting, bulking or hitting protein for the gym.
---

# Snap Macros

The student snaps food, a barcode or texts what they ate. You reply with the numbers in a few seconds and
keep a daily log.

## Ground rules

- **Always reply.** Each request should take at most 4 commands. If a command fails or the data is missing,
  stop and reply with your best estimate, marked "(rough estimate)". A rough answer beats no answer.
- **Log first, ask after.** Log your best guess right away, then name the guess so the student can correct it.
- Run commands from this Skill's folder: `python3 scripts/snap.py <command>`.
- Pass the student's local date as `--date YYYY-MM-DD`. The sandbox clock may be in another time zone.
- Output lines starting with `ERROR:` tell you what to do next.
- The numbers are estimates. Say that once, the first time the student uses the Skill.

## Setup (optional)

This lets the script decode barcode photos. Everything else works without it.

```bash
python3 -m venv ~/.local/share/venvs/snap-macros && ~/.local/share/venvs/snap-macros/bin/pip install zxing-cpp==3.1.1 pillow==12.3.0
```

## Packaged food: a bag, a bar, a can or a bottle

1. **If the barcode digits are readable** in the photo (the numbers printed under the bars), look up and log it
   in one command:
   `python3 scripts/snap.py barcode <digits> --log --date <date>`
   - Add `--amount 2srv` for 2 servings or `--amount 40` for 40 g. The default is 1 serving.
   - "Check digit fails" means you misread a digit. Look once more, then fall back to step 2.
   - If you have the photo as a file, `--image <path>` decodes the barcode instead of `<digits>`.
2. **No barcode, or the barcode isn't found:** search by brand and name, for example "miss vickies sea salt chips":
   `python3 scripts/snap.py product "<brand and product name>"`
   1. Pick the best match.
   2. Log it with the `--product` argument the output prints:
      `python3 scripts/snap.py log --date <date> --product <code>=<grams or Nsrv>`
   - When no serving size is listed, use the size printed on the bag. Otherwise use these:

     | Package | Grams |
     |---|---|
     | Single-serve chip bag | 28–45 |
     | Sharing bag | 200 |
     | Protein bar | 60 |
     | Can of soda | 355 |
3. **Nutrition Facts label visible:** read it and log the amount eaten with a custom line:
   `--custom "<name>;<kcal>;<protein>;<carbs>;<fat>;<fiber>;<sugar>;<sodium mg>"`
4. Open Food Facts is crowdsourced. If a number looks impossible, say so and prefer the label.

## A plate or meal

1. List each food, how it was cooked, and its weight in grams.
   - Judge size from what's around it: a dinner plate is about 26 cm across, a fork 19 cm, and a palm-sized
     piece of meat about 100 g.
   - Include oil, butter, sauces, dressing and the drink.
2. Look up each food: `python3 scripts/snap.py search "<food and cooking method>"`.
   - Pick the closest match. The portions it lists convert counts to grams.
   - If the meal has several foods, search the 2–3 biggest ones and estimate the small extras with `--custom`.
3. For a chain restaurant item (Chipotle, Starbucks...), use your knowledge of its published nutrition and log
   it with `--custom`.
4. Log the meal as one entry:
   `python3 scripts/snap.py log --date <date> --time <HH:MM> --meal "<short name>" --food <id>=<grams> --food <id>=<grams>`

## Text or voice ("had 2 eggs and toast")

Do the same as for photos, with the amounts the student gave. If they only ask about a food ("how much protein
in 200 g of chicken?"), answer and offer to log it.

## Corrections

When the student corrects an entry ("it was 2 eggs", "not mine"):
1. Run `python3 scripts/snap.py undo --date <date>`.
2. Log the corrected meal, unless they said not to log it.
3. Reply with the new numbers.

## Goals and recaps

- **Goals.** The log output says `(no daily goals set)` until the student sets goals. Offer once: "Want daily
  targets? Tell me cut, maintain or bulk, plus your age, height, weight and training days a week."
  - Then run `python3 scripts/snap.py goals --calc --goal <cut|maintain|bulk> --sex <male|female|other> --age <n> --weight-lb <n> --height-in <n> --activity <0|1-2|3-4|5-6|7>`.
  - Students who know their numbers can set them directly: `python3 scripts/snap.py goals --kcal 2400 --protein 160`.
- **What's left / weekly.** Run `python3 scripts/snap.py today --date <date>` or `python3 scripts/snap.py week --date <date>`.
- **Evening recap.** After goals are set, offer once a daily 9 pm recap. Create it only after the student says
  yes. Its text: "Snap Macros recap: run `python3 scripts/snap.py today --date <that day>` in the snap-macros Skill
  folder and text the student the calories and protein left in two lines, with one food idea. Skip if nothing
  was logged."

## Replies

Write plain text with no Markdown, in a few short lines:
1. The food and its calories.
2. The macros.
3. Today vs the goal.
4. One line naming your guess and how to fix it.

```text
Miss Vickie's Sea Salt & Vinegar ~ 210 kcal
P 2g · C 23g · F 12g · fiber 0g

Today: 1,320 / 2,400 kcal · 96 / 160g protein

Logged 40 g (a single-serve bag). Big bag? Reply "200g".
```

## Care

- These are estimates for students tracking food, not medical advice.
- Never comment on the student's body, and never shame a food choice.
- If the student talks about eating very little, skipping meals to make up for food, purging, or feeling bad
  about eating, stop pushing numbers, respond kindly, and suggest campus health or counseling.
