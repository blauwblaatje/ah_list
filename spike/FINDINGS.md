# Spike findings (2026-10-29, live against api.ah.nl)

## Auth
- Login: `https://login.ah.nl/login?client_id=appie-ios&redirect_uri=appie://login-exit&response_type=code`.
- Chrome does not show the `appie://` redirect in the Network tab. The Console shows
  `Failed to launch 'appie://login-exit?code=…'`, which holds the URL.
- `POST /mobile-auth/v1/auth/token` with `{"clientId":"appie-ios","code":…}` returns
  `access_token`, `refresh_token`, `expires_in` (snake_case; ~7 days).
- `POST /mobile-auth/v1/auth/token/refresh` with `{"clientId":"appie-ios","refreshToken":…}`
  returns the same shape. Always store the returned refresh token.
- Headers: `User-Agent: Appie/9.28 (…)`, `x-client-name: appie-ios`, `x-client-version: 9.28`,
  `x-application: AHWEBSHOP`, JSON accept/content type, `Authorization: Bearer …`.

## Shopping list (`/mobile-services/shoppinglist/v2/items`)
- `GET` returns `{id, items, activeSorting, dateLastSynced, dateLastSyncedMillis, storeNumber}`.
- `PATCH {"items":[…]}` adds, changes and removes; the response is the whole list.
- Each entry **must** have `"strikeThrough": false`; without it every request gets
  400 "Failed to read request" (python-appie 0.2.2 omits it and is broken).
- Product entry: `productId, quantity, type: SHOPPABLE, originCode: PRD, description, searchTerm, strikeThrough`.
- Free-text entry: `description, quantity, type: SHOPPABLE, originCode: TXT, strikeThrough`.
- `quantity: 0` removes. Matching is by productId (products) or by description (text).
- `listItemId` is 0 for every item: there is no usable item id.
- AH normalises free text: `ah_list test` was stored as `ahlist test`. Remove using the
  description as returned by GET, never the description we sent.
- Stored items read back `strikedthrough` (sic), `position`, `sorting`; products under
  `productDetails.product` (`webshopId`, `title`, …), text under `vagueTermDetails.searchTermValue`.

## Product search
- `GET /mobile-services/product/search/v2?query=…&sortOn=RELEVANCE&size=10&page=0` → `products[]`.
- Useful fields: `webshopId`, `title`, `salesUnitSize`, `priceBeforeBonus`, `currentPrice`
  (bonus price, null otherwise), `isBonus`, `bonusMechanism`, `brand`, `mainCategory`,
  `subCategory`, `orderAvailabilityStatus`, `availableOnline`, and **`isPreviouslyBought`**
  (matcher ranking signal straight from search; may make receipt scraping unnecessary).

## Writes (probe, 2026-10-29, test items only)
- PATCH sets the quantity of a product (1 then 3 gives 3, not 4).
- Free-text items keep quantity 1 whatever is sent: AH ignores quantity on text.
- `strikeThrough: true` checks an item off, `false` unchecks it; products and text alike.
- The PATCH response is the whole list in the same shape as GET, so no GET is needed after
  a write.

## Search quality (18 terms, 2026-10-29)
- Relevance puts bonus multi-packs ("3-pack") first and returns loose hits: "eieren" finds
  "aardbeien", "brood" a surimi salad, "wc papier" envelopes.
- `size=30` is accepted (returned 32). Previously bought products are often beyond the
  first 10 ("melk": positions 8, 10, 11, 22).
- `brand` is a prefix of `title`, including sub-brands ("AH Biologisch", "AH Terra").

## Still to check
- Whether the refresh token rotates (store whatever comes back, either way).
- The response of a bad/expired token (401?).
- What happens when the app and a PATCH change the list at the same moment.
