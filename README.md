# Neotec Order Costing

Order-wise COGS pegging, brand-wise procurement split, configurable batch
naming and a fully configurable profitability report for ERP v15.

Version 0.2.0 · Frappe/ERP v15 · Neotec Integrated Solution

---

## What problem this solves

The same item bought in several tranches at different prices gets blended by
moving average or mis-assigned by FIFO. Two hundred HP laptops bought at 2,000
and three hundred and fifty at 1,800 both end up costing 1,872.73, so no sales
order shows its true margin.

This app pegs each sales order line to the purchase order line that serves it,
carries that peg through to the batch created on receipt, and selects that
batch at delivery. the ERP platform's own batch valuation then produces the correct
COGS without any override of the stock ledger, so the GL always reconciles.

---

## Install

```bash
bench get-app https://github.com/jamunachi08/neotec_order_costing
bench --site <site> install-app neotec_order_costing
bench --site <site> migrate
bench build --app neotec_order_costing
```

Nothing changes in stock behaviour until **Order Costing Settings → Enable
Order-wise COGS** is switched on.

---

## Settings

Every capability is independently switchable in **Order Costing Settings**.

| Section | Switch | Effect when off |
|---|---|---|
| Master Switch | Enable Order-wise COGS | Stock valuation is exactly the standard ERP |
| Procurement Document Flow | Inward Flow | Auto-detects PR or PI-with-update-stock |
| Automatic Batch Creation | Enable Auto Batch Creation | Batches behave as the standard ERP |
| Brand-wise Split | Enable Split | Material Requests and POs are created normally |
| Invoice Add-ons | Enable Add-on Handling | Unmatched invoice lines cost at default valuation |
| Cost Variance Posting | Post Cost Variance Journal | No journal entries are created |

### Costing modes

- **Pegged Batch Valuation** — recommended. Batch carries the tranche cost, the
  standard valuation engine does the rest.
- **Pegged PO Rate** — reports COGS at the contracted purchase rate. Stock still
  posts at real valuation; enable the variance journal so the ledger stays
  reconcilable.
- **Default Valuation** — moving average or FIFO as configured in Stock Settings.

### Applicability

Leave the table empty to apply the global mode everywhere. Add rows to run
order-wise costing for a specific company, item group, brand or customer group
only. The first matching enabled row wins, so order rows from specific to
general.

---

## Procurement document flow

Some clients raise a Purchase Receipt and then a Purchase Invoice. Others skip
the receipt and post one Purchase Invoice with **Update Stock**, which hits
payables and inventory in a single document. Both are supported by the same
hooks:

- `Auto Detect` accepts whichever the user posts.
- `Purchase Receipt then Purchase Invoice` plus `Enforce Purchase Receipt`
  blocks invoices raised straight off a purchase order.
- `Purchase Invoice with Update Stock` defaults the flag on new invoices.

Batch creation, peg updates and landed cost refresh all run identically in
either flow.

---

## Batch identity

The implementor decides what a batch number means. **Order Costing Settings →
Batch ID Composition** stacks components in order:

| Component | Example output |
|---|---|
| Static Text | `BT` |
| Item Code | `SIMHPLAP` |
| Brand | `HP` |
| Sales Order (last 4) | `0142` |
| Purchase Order (last 4) | `0088` |
| Supplier / Customer / Sales Person | `SUP0007` |
| Posting Date (YYYYMMDD / YYMM / DDMMYY) | `20260801` |
| Serial Counter | `001` |

`Static Text "BT" | Brand | Sales Order (last 4) | Serial Counter (3)` gives
`BT-HP-0142-001`.

Use **Test Batch ID** on the settings form to generate a sample against a real
item and order before going live. Components with no value in the current
context are skipped rather than producing empty separators.

---

## Brand-wise procurement split

One sales order carrying HP, Dell and Lenovo lines produces one Material
Request and one Purchase Order per group. Split basis can be Brand, Supplier,
Brand and Supplier, Item Group, or the item's default supplier.

From a submitted Sales Order: **Create → Material Requests by Brand** or
**Purchase Orders by Brand**. A preview dialog shows every group, its supplier
and quantities, and lets the user deselect groups before anything is written.

`Block Mixed-Brand Purchase Order` turns the convention into a hard rule.

---

## Invoice add-on items

Items added at delivery or invoice time that were never on the sales order —
a RAM upgrade, a larger SSD, an extended warranty — are detected automatically
(no `so_detail` link). They are flagged `Is Add-on`, attributed to a parent
item for reporting, and costed by one of:

- **Own Peg If Available** — finds a received peg for the same item.
- **Default Valuation** — normal moving average or FIFO.
- **Attribute to Parent Sales Order Line** — rolls the cost into the parent.

The report can show them as separate lines or roll them into the parent item.

---

## Order Wise Profitability report

Columns are not fixed. A **Profitability Report Profile** holds an ordered list
of columns picked from any document in the cycle:

Sales Invoice · Sales Invoice Item · Sales Order · Sales Order Item ·
Delivery Note · Delivery Note Item · Purchase Order · Purchase Order Item ·
Purchase Receipt · Purchase Invoice · Order Cost Peg · Batch · Item ·
Customer · Supplier · Computed

Use **Configure Columns** in the report, or **Add Columns** on the profile, to
tick fields from a grouped picker. Untick `Show` to hide a column without
losing it. Drag rows in the grid to reorder columns.

Computed columns available: Revenue, COGS (Ledger), COGS (Pegged), COGS
Variance, Gross Profit, Margin %, Unit Cost, Unit Margin, Markup %.

Group by Sales Order, Customer, Sales Person, Brand, Item Group, Item,
Supplier, Purchase Order or Batch.

Two supporting reports ship alongside: **Procurement Peg Register** for
SO ↔ PO ↔ batch ↔ delivery traceability, and **Batch Cost Traceability** for
per-batch inward and outward valuation.

---

## Creation tab

Order Cost Peg appears in the Connections tab of Sales Order, Purchase Order
and Batch. Submitted Sales Orders gain Create and View buttons for split
procurement documents, cost pegs and the profitability report.

---

## Part numbers and specifications (v0.2.0)

A part number **is** an Item. One the ERP platform Item per manufacturer part number:
`HP-6N4C2EA`, `DELL-LAT5450`. Not a generic item with the part number as a
field — the peg engine, batch valuation and brand split all key on
`item_code`, and the specification you hand the customer must match what you
costed.

### Cross-references

Native platform tables are used, not reinvented:

| Identifier | Stored in | Flows to |
|---|---|---|
| OEM part number | `Item Manufacturer` | Purchase and sales rows, stamped at validate |
| Vendor part number | `Item Supplier` | Purchase Order line, drives supplier resolution |
| Customer's own code | `Item Customer Detail` | `customer_item_code` on SO, DN, SI |

### Specification layer

- **Specification Attribute** — `label_en`, `label_ar`, UOM, datatype,
  `is_key_spec`, `is_numeric_aggregatable`.
- **Specification Template** — scoped to Item Group, Brand, both, or all
  items. Most specific scope wins. `Enforce Mandatory` blocks saving a part
  number that is half-specified.
- **Item Specification** — the bilingual attribute/value rows on the Item,
  with `show_to_customer` and display ordering.

Use **Compare With Another Part** on the Item to diff two part numbers.

### Supersession

`Part Equivalence` records `Alternate`, `Superseded By` and `Supersedes`
relations. When a receipt or invoice carries a part number different from the
purchase order line, the app checks equivalence and then, per
`allow_superseded_substitution`:

- **Prompt** — warns, re-points the cost peg, creates a `Part Substitution Log`
  with a generated specification comparison.
- **Automatic** — same without the prompt.
- **Forbidden** — blocks the receipt.

Where no equivalence exists the receipt is always blocked, in every mode.

### As-built configuration

The quotation promised the factory spec. Add-on lines change it. Mark an
upgrade part with `Modifies Attribute`, `Modification Mode`
(Replace / Add / Append / Remove) and `Modification Value`.

A 16GB module with mode `Add` on an aggregatable `RAM` attribute turns an 8GB
base into 24GB on the delivered spec. An `As Built Configuration` is generated
per delivery line and printed on the delivery note and the invoice annexure.

### Print formats

| Format | Document | Contents |
|---|---|---|
| Quotation with Specifications | Quotation | Part number, MFR P/N, customer P/N, spec block per line |
| Part Number Spec Sheet | Item | Standalone bilingual spec sheet with equivalents |
| Delivery Note with As-Built Configuration | Delivery Note | Delivered spec, batch, serial, upgrade badges |
| Sales Invoice Specification Annexure | Sales Invoice | Short invoice lines, full specs on a separate annexure page |

**ZATCA note.** Keep `Show Key Specs on Invoice Line` off. Long specification
text in the item description flows into the ZATCA XML and risks name-length
constraints. The annexure carries the detail; the invoice line stays short.

---

## Verification

```bash
python3 verify_tree.py

bench --site <site> execute neotec_order_costing.simulation.run \
  --kwargs "{'company': 'Your Company', 'warehouse': 'Stores - YC'}"
```

The simulation builds the two-salesman laptop scenario end to end, delivers
Salesman B before Salesman A to prove FIFO would have mis-costed, and asserts
that A costs 2,000 per HP unit and B costs 1,800 against a blended rate of
1,872.73.

---

## Architectural conventions

- flit / `pyproject.toml` packaging, no Server Scripts, all logic in versioned
  Python controllers.
- Idempotent `after_install` and `after_migrate` custom field creation.
- System Manager permissions on every doctype, role guards on all whitelisted
  endpoints.
- Custom fields namespaced `custom_noc_*` to avoid collision with other apps.
- Stock valuation is never overridden on outward entries for external
  customers. Pegged PO Rate mode journalises the difference instead.

---

## Known limits

- A sales order line partly served from free stock and partly from a pegged
  purchase gets the pegged rate only for the procured quantity; the remainder
  falls back to default valuation and is flagged in the report.
- Landed Cost Vouchers posted after the first delivery adjust the batch
  retroactively. Post them before delivering, or accept the variance.
- Multi-currency purchase orders store the base currency rate on the peg;
  supplier currency reporting reads from the purchase order itself.
