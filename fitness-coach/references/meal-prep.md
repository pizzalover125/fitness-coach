# Meal prep: writing the plan

Read this before writing recipes for `scripts/meals.py plan save`. The script does the bookkeeping:
- meal slots and calorie targets
- what's about to go bad
- allergy and diet checks
- nutrition
- the shopping list
- reminders

You write food the student will actually want to eat.

## What makes a plan good

**Use what's going bad first.**
- Every "Use first" item in `context` should appear in the first cook session.
- A plan that lets chicken go bad in the fridge has failed, however tasty it is.

**Cook once, eat it two different ways.**
- A batch is 2–4 servings, kept no more than 3 days after cooking.
- For each later serving, give a `remix`: a 2-minute twist so day 3 doesn't feel like day 1. For example:
  - Burrito bowl → burrito wrap.
  - Stir-fry → fried rice with an egg.
  - Chili → chili over a baked potato.
  - Pasta → pasta bake with cheese under the broiler.

**Lunch and dinner come from different batches.**
- `context` already splits them into separate sessions, so nobody eats the same thing twice in one day.
- Use different proteins or cuisines for each.

**Build around a base.** One grain or starch, one protein and one vegetable per session, with the flavor coming
from a sauce or spice blend. Good combinations:

| Style | Sauce or spices |
|---|---|
| Mexican | chipotle, cumin and lime |
| Korean | gochujang, soy, sesame and garlic |
| Mediterranean | lemon, garlic, oregano and feta |
| Thai-style | coconut, curry paste and lime |
| Indian-style | garam masala and yogurt |

Never use peanut sauce or any other allergen the student listed. The script blocks it anyway.

**Hit the targets.**
- `context` gives calories and protein for each open meal.
- Size the portions to match. Rice, oil and cheese change calories most; the protein portion changes protein most.
- On training days, put a few more carbs in the meal after the workout.
- If a fixed meal (dinner out, free food) is big, the open meals that day are already smaller. Don't add anything
  back.

**Respect the setup.**
- Only use equipment the student has. Microwave-only means:
  - mug or bowl recipes
  - microwave rice
  - pre-cooked proteins (rotisserie chicken, canned tuna or beans, eggs scrambled in a mug)
  - bagged salads
- A rice cooker can steam vegetables and eggs on top of the rice.
- Stay under their time limit. Count prep and cooking together.
- For beginners, use few steps, one pan, and say what "done" looks like ("no pink inside, 165°F").

**Cheap student staples.** Rice, oats, eggs, canned beans and lentils, frozen vegetables, chicken thighs, ground
turkey, tofu, Greek yogurt, tortillas, pasta, peanut-free nut butters, and bananas.

**Food safety.**
- Raw chicken and ground meat keep 1–2 days in the fridge. Cook them in the first session or freeze them.
- Thaw frozen meat in the fridge the night before. The script reminds the student to.
- Reheat leftovers until steaming hot.
- A serving more than 3 days out should be frozen right after cooking. The script warns about this.

## The JSON format

Write one file, for example `~/.config/fitness-coach/plan.json`, then run
`python3 scripts/meals.py plan save --file ~/.config/fitness-coach/plan.json`.

```json
{
  "recipes": [
    {
      "name": "Chipotle chicken burrito bowls",
      "cook": "2026-10-26",
      "minutes": 30,
      "servings": 2,
      "covers": ["2026-10-26 lunch", "2026-10-27 lunch"],
      "ingredients": [
        {"item": "chicken breast raw", "grams": 450, "qty": "1 lb"},
        {"item": "rice white cooked", "grams": 400, "qty": "2 cups cooked"},
        {"item": "black beans canned", "grams": 240, "qty": "1 can, drained"},
        {"item": "lime", "count": 1, "qty": "1"},
        {"item": "chipotle chili powder", "qty": "2 tsp"}
      ],
      "steps": ["Start 1 cup dry rice in the rice cooker.", "..."],
      "remix": {"2026-10-27 lunch": "Roll it into a tortilla with hot sauce."},
      "storage": "Fridge, up to 3 days."
    }
  ]
}
```

| Field | What it holds |
|---|---|
| `cook` | The date it's cooked. |
| `covers` | The slots it feeds, written `"YYYY-MM-DD meal"` and taken from `context`. |
| `servings` | At least the number of `covers`. |
| `ingredients` | The total for the whole batch, not one serving. |
| `ingredients[].item` | A plain food name, with its state when it matters: "chicken breast raw", "rice white cooked", "black beans canned". |
| `ingredients[].grams` | The weight, which nutrition is counted from. Spices and sauces under 15 g can go without. |
| `ingredients[].count` | For things counted, like eggs or limes. |
| `ingredients[].qty` | What the student reads on the shopping list and in the recipe. |
| `ingredients[].usda` | Optional. Pin the exact USDA food when the automatic match is wrong. Find the id with `python3 scripts/food.py search`. |
| `steps` | Short, one action each. |
| `remix` | Optional. Keyed by slot. |
| `storage` | Optional. |

## After `plan save`

- **`ERROR:` lines** are hard rules: an allergen, the wrong diet, a slot that's already taken care of, a double
  booking, or eating before cooking. Fix the recipe and save again.
- **`matched:` lines** show which USDA food each ingredient was counted as. If one is clearly wrong ("bell pepper
  -> Peppers, jalapeno"), add `"usda": <id>` or rename the item, and save again.
- **`Notes:`** are worth fixing when it's easy:
  - Portions far from the target.
  - Low protein.
  - Something going bad that isn't used.
  - Slots left uncovered.
- Then text the student the plan, in this order:
  1. One line per recipe: name, which meals, calories and protein a serving.
  2. The shopping list grouped by aisle. If it's long, send it as a note or add it to Google Tasks after they say yes.
  3. The offer of reminders.
