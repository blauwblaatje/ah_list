# Albert Heijn shopping list for Home Assistant

Shows your Albert Heijn shopping list ("mijn lijst" in the AH app) as a Home Assistant
to-do list, **AH lijst** (`todo.ah_lijst`).

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
2. Add, remove and check off items on the AH list
3. Match free text ("2 pakken melk") to AH products, preferring products you bought before
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
