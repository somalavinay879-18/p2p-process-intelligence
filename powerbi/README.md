# Power BI version: build guide (browser, no Windows needed)

The same analysis as the Streamlit dashboard, built as a Power BI report on a star-schema model in the
Power BI service (app.powerbi.com) with a university Microsoft account. About 3–4 hours the first time.

| File | What it is |
|---|---|
| `P2P_PowerBI_Model.xlsx` | The model data: one sheet per table (made by `python scripts/export_powerbi.py`) |
| `measures.dax` | All DAX: ~50 measures, 3 calculated tables, a calculation group, an RLS role |
| `theme.json` | Report theme (SAP blue, cards with rounded borders) |

## What makes this "advanced"

- **Star schema**: one fact table (251,734 PO items), four dimensions, a date table, helper tables.
- **DAX patterns**: Pareto / ABC analysis with `ADDCOLUMNS` + `ALLSELECTED`, dynamic vendor segmentation,
  `TOPN` concentration, `RANKX`, context-independent model metrics with `REMOVEFILTERS`.
- **What-if parameter** for the review budget: a gains curve and capture/hit/lift cards that react to a slider.
- **Calculation group** (time intelligence on any measure: previous month, MoM, rolling 3 months, YTD).
- **Dynamic titles and narrative** written in DAX, a **KPI switcher** with a dynamic format string.
- **AI visuals**: Key influencers (what drives payment blocks) and a Decomposition tree (where the value at risk sits).
- **Drill-through** vendor page, a **report-page tooltip**, **bookmarks**, **row-level security** demo.

## Step 1 · Load the data (15 min)

1. Upload `P2P_PowerBI_Model.xlsx` to your **SRH OneDrive**.
2. Open **app.powerbi.com**, sign in with the SRH account, go to **My workspace**.
3. **New item → Semantic model → Get data → Excel workbook**, pick the file from OneDrive, select all
   10 sheets, **Create**. Name the model `P2P Process Intelligence`.
   (If your menu differs: any route that *imports* the workbook into a semantic model works.)
4. Open the model → **Open data model** (top right switch to **Editing**).
5. Check column types: `PODate`, `DimDate[Date]`, `DimDate[MonthStart]` = Date; all `Is…`, `Has…`,
   `InTestSet`, `RiskRank`, `VariantRank` = Whole number; `OrderValue`, `Days…`, `RiskScore` = Decimal.

## Step 2 · Model (20 min)

Relationships (all many-to-one, single direction, from the fact or helper table to the dimension):

| From | To |
|---|---|
| `FactPOItem[PODate]` | `DimDate[Date]` |
| `FactPOItem[VendorID]` | `DimVendor[VendorID]` |
| `FactPOItem[MatchingType]` | `DimMatchingType[MatchingType]` |
| `FactPOItem[SpendArea]` | `DimSpendArea[SpendArea]` |
| `FactPOItem[VariantRank]` | `Variants[VariantRank]` |
| `ProcessFlow[MatchingType]` | `DimMatchingType[MatchingType]` |

Then:
- `DimDate`: **Mark as date table** on `Date` (if the option is there); sort `Month` by `MonthSort`, `Weekday` by `WeekdayNumber`.
- `DimMatchingType[ShortName]`: sort by `SortOrder`. `ProcessFlow[From]` sort by `FromOrder`, `[To]` by `ToOrder`.
- Hide in report view: every key and helper column (`CaseID`, `PONumber`, `RiskRank`, `Is…` flags, `MonthSort`, `SortOrder`, …).
- `ModelResults`, `RiskDrivers`, `DataQuality` stay unrelated (they are small lookup tables).

## Step 3 · DAX (45 min)

Open `measures.dax` and create, in order: the calculated tables (`_Measures`, `Review Share`, `KPI Selector`),
then sections 1–9 as measures in `_Measures` with the display folder and format noted beside each,
then the **Time Calc** calculation group, then the RLS role. Test each section with a card before moving on:

| Check | Expected (no filters) |
|---|---|
| `PO Items` / `Purchase Orders` / `Vendors` | 251,734 / 76,349 / 1,975 |
| `Order Value` | €1,004.9 M |
| `Block Rate` / `Block Delay Days` | 22.2% / +14 days |
| `Violations` / `Value at Risk` | 654 / €1.75 M |
| `Median Days to Payment` / `Median Days Invoice to Payment` | 78 / 42 |
| `Hit Rate` / `Capture Rate` / `Lift` at 10% | 42% / 18% / 1.8× |
| `Top 2% Vendor Spend Share` | 46% |

If a number differs, the cause is almost always a column type (Step 1.5) or a missing relationship.

## Step 4 · Report (1.5–2 h)

Apply the theme first: **View → Themes → Browse for themes → `theme.json`**. Canvas 1280 × 720.
Every page: a navy rectangle on the left (width 220) holding the slicers **Month (DimDate[Month])**,
**Matching type (ShortName)**, **Spend area**; page title as a text box; `Title - Selection` in a card under it.
Sync the slicers across pages (**View → Sync slicers**).

**1 · Executive summary**
- 6 KPI cards: Order Value, Vendors (subtitle `Top 2% Vendor Spend Share`), Median Days to Payment,
  Block Rate (subtitle `Block Delay Days`), Violations, Value at Risk.
- Line and clustered column chart: X `DimDate[Month]`, columns `Selected KPI`, line `Block Rate (mature orders)`;
  title from `Title - Trend` (fx); a **KPI Selector** slicer as buttons above it.
- Bar chart: Order Value by `SpendArea`, data colors by `Block Rate` (gradient).
- Three text cards with `Insight - Time`, `Insight - Blocks`, `Insight - Compliance`.

**2 · Process**
- Matrix "process map": rows `ProcessFlow[From]`, columns `ProcessFlow[To]`, values `Transitions`;
  background conditional format (gradient white → blue); add `Median Days Between Steps` as a second value
  with font color `Slow Step Color` (field value).
- Clustered bar: `DimMatchingType[ShortName]` × the three medians (to goods receipt, to invoice receipt, to payment).
- Table: `Variants[Variant]`, `PO Items`, `Variant Share` (data bars), `Variants[MedianDaysToPay]`; top 15 by PO Items.

**3 · Compliance**
- **Decomposition tree**: analyze `Value at Risk`, explain by ShortName → SpendArea → VendorID.
- Column chart Violations by Month; matrix ShortName × `Violations`, `Violation Rate`, `Value at Risk`, `Block Rate`.
- Table of violating items (filter `IsViolation = 1`): CaseID, PODate, VendorID, OrderValue, IsBlocked, DaysToPayment.

**4 · Suppliers**
- **Scatter**: X `Order Value` (log scale), Y `Block Rate`, size `PO Items`, details `DimVendor[VendorID]`,
  marker color by `Segment Color` (field value); analytics pane: constant lines at the average.
- **Pareto**: line and column chart, X `VendorID` (top 50 by Order Value), columns `Order Value`, line `Cumulative Spend %`.
- Table "Fix first": VendorID, `Order Value`, `Block Rate` (data bars), `Blocked Value`, `Vendor Segment`, `ABC Class`,
  sorted by Blocked Value.

**5 · Vendor detail (drill-through)**
- Page type: drill-through on `DimVendor[VendorID]`, keep all filters. Cards for the vendor, monthly items
  and block rate, spend area donut, a table of its items. Right-click a vendor anywhere → **Drill through**.

**6 · Payment-block risk**
- `Review Share` slider (single value, default 10%).
- Cards: `Items to Review`, `Capture Rate`, `Hit Rate`, `Lift`; text card `Insight - Model`.
- **Gains curve**: line chart, X `'Review Share'[Review Share]`, Y `Capture Rate` and `Random Capture Rate`.
- **Key influencers**: analyze `FactPOItem[IsBlocked]` (= 1) explained by MatchingType, SpendArea, DocumentType,
  VendorSize, `OrderValue`. This is Power BI's own driver analysis next to the model's weights.
- Bar chart `RiskDrivers`: Driver × Weight, color by Direction. Table `ModelResults`.
- Review list: table CaseID, PODate, VendorID, OrderValue, RiskScore (data bar), BlockedWithin120Days;
  visual filter `In Review List = 1`, sort by RiskScore descending.

**7 · Data & method**: `DataQuality` table with an icon on `Passed`, cards `Checks Passed` / `Checks Total`,
`Rows Handled`, and a text box with the pipeline and limitations (copy from the main README).

**Polish**
- **Tooltip page** (Page info → Allow use as tooltip, 320 × 240): Order Value, Block Rate, Median Days to Payment for
  the hovered item; set it as the tooltip of the spend-area and scatter charts.
- **Bookmarks**: "Executive view" (summary visuals only) and "Analyst view" (tables shown); two buttons switch.
- **Page navigator** buttons in the left panel.
- **Time Calc**: on page 1 add a matrix with Month rows, `Time Calc[Period]` columns, `Order Value` values.
- **RLS**: Security → test as role "Packaging buyer"; every page shows only Packaging.

## Step 5 · Share it

- Screenshots of each page (1280 × 720) into `docs/powerbi_*.png` and a short GIF of the slider and drill-through.
- Export the report to PDF (File → Export → PDF) for your portfolio site.
- "Publish to web" is usually disabled for university accounts; screenshots, the PDF and a screen recording are
  the safe way to show it.

## Rebuild the data

```bash
make run                                # pipeline + model
.venv/bin/python scripts/export_powerbi.py
```
