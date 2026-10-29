# Albert Heijn shopping list for Home Assistant

Shows your Albert Heijn shopping list ("mijn lijst" in the AH app) as a Home Assistant
to-do list, **AH lijst** (`todo.ah_lijst`), and lets you change it from Home Assistant:

- **Add** an item, e.g. "2 pakken melk" or via Assist. It is matched to an AH product when
  that is clear (see below); otherwise it goes on the list as text, which works fine in the
  store. Adding a product that is already on the list adds to its quantity.
- **Check off** and uncheck items.
- **Change the quantity** of a product by editing the number in front: `2 × AH Halfvolle melk`.
  AH keeps free-text items at quantity 1.
- **Rename** a free-text item. Products can't be renamed; remove them and add a new item.
- **Remove** items.

## Matching items to products

The text is split into a quantity and a name: "2 pakken melk", "melk x2" and "twee pakken
melk" buy two; "500 g gehakt" and "2 teentjes knoflook" buy one. The name is searched at
AH, and a product is only chosen when it clearly fits:

1. you set a mapping for the term (`ah_list.set_mapping`);
2. all products you bought before that contain every word have the same name, in whatever
   size or brand ("melk" → AH Halfvolle melk);
3. a product is named exactly like the term ("rucola" → AH Rucola). If you bought several
   different matching products, only those count.

Otherwise the item stays text. Use `ah_list.search_products` to find a product id and
`ah_list.set_mapping` to fix a term to it; `ah_list.get_mappings` and
`ah_list.remove_mapping` manage the mappings.

Planned: adding items from other to-do lists (the HA shopping list, Mealie, Assist) with
matching to AH products. See [the plan](#roadmap).

## ⚠️ Read this first

- This uses the **unofficial** API of the AH mobile app. Albert Heijn does not support it
  and can change or block it at any time; the integration will then break until it is
  updated.
- It identifies itself to AH as the AH app (its User-Agent and client id), because the API
  accepts nothing else.
- It polls your list every 10 minutes. Please keep it that way: don't lower the interval
  or hammer the API, so that it stays usable for everyone.
- It never orders or pays for anything.

## Installation

Via HACS: add this repository as a custom repository (type *Integration*), install
**Albert Heijn shopping list** and restart Home Assistant.

Manually: copy `custom_components/ah_list` into your `config/custom_components/`.

## Setup

AH has no password login for third parties; you log in on the AH website and paste the
code it hands to the app:

1. Settings → Devices & services → Add integration → **Albert Heijn shopping list**.
2. Open the AH login link shown there in a desktop browser, open the developer tools
   (F12) on the **Console** tab, and log in.
3. The last page will not load, because it redirects to the AH app. The console shows
   `Failed to launch 'appie://login-exit?code=…'`. In Firefox, copy the `appie://`
   address instead.
4. Paste that line into Home Assistant within a few minutes. The whole line is fine.

The login stays valid; when AH revokes it, Home Assistant asks you to log in again.

## Roadmap

1. ✅ Read-only AH list
2. ✅ Add, remove and check off items on the AH list
3. ✅ Match free text ("2 pakken melk") to AH products, preferring products you bought before
4. `ah_list.sync_from_todo` action and an inbox blueprint
5. A list of matches to review, "AH te controleren"

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Tests mock every AH call. `spike/` holds the script used to check the API live and
`spike/FINDINGS.md` what it found.
