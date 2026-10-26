# Collection order (brand mix)

Keeps the product order of every Shopify collection mixed: brands alternate, best-sellers and "incontournable"
products come early, product types and price bands vary. Only the display order changes; no product is edited,
removed or hidden. Nothing private is stored here: credentials are repository secrets.

- `ordering.py`: the ordering rules (pure functions, no Shopify calls).
- `reorder_collections.py`: reads products and collections, orders each collection, writes the order.
- `.github/workflows/merchandising.yml`: runs every hour on `main`, or by hand ("Run workflow").

## How a collection is ordered

- Collections are switched to manual sort. Collections ordered by price on purpose ("à petits prix"), the
  home page, the discount-eligibility collection and archives are left alone (`KEEP_SORTS`, `EXCLUDE`).
- Products the storefront hides (out of stock, draft) go to the end, so what a customer sees is already mixed.
- First run of a collection, or `FULL=1`: built position by position. A candidate is penalised if the same brand,
  product type, product line or price band is among the last places, pulled forward if its brand still has many
  products to place, and rewarded if it is a best-seller (`best-seller`, `incontournable` tags), more so near the top.
  Page 1 (24 products) shows each brand once when the collection has enough brands.
- Later runs (default): products already placed keep their place. A product that is new to a collection, or came
  back in stock, is slotted at the cheapest place (no same brand nearby), never automatically at the top.
  The ids placed in each collection are kept in the app-owned shop metafield `$app:merch.placed`.
- A brand with more than a third of a collection cannot be fully separated; the report shows what is left.

## Run it

Workflow inputs: `dry_run` (default true: report only), `full` (rebuild everything), `only` (collection handles).
The run summary and the `order-report` artifact list, per collection, adjacent same-brand pairs, longest brand
run and number of brands on page 1, before and after.

Locally: `SHOPIFY_STORE=… SHOPIFY_CLIENT_ID=… SHOPIFY_CLIENT_SECRET=… DRY_RUN=1 python3 -I reorder_collections.py`.

`request.env` only exists to start the workflow from the work branch before it is merged; ignore it afterwards.
