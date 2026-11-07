"""P2P Process Intelligence - dashboard.

Reads the tables in data/app/ (from `make run`), or data/app_demo/ (from `make demo`)
when the real log has not been processed. Every view except the process graph and the
model scores is computed from the item table, so the sidebar filters apply everywhere.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="P2P Process Intelligence", page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")

NAVY, BLUE, SKY, ORANGE, RED, GREEN, GREY, INK = (
    "#0b1f3a", "#0a6ed1", "#91c8f6", "#e9730c", "#c0392b", "#188918", "#8396a8", "#1d2d3e")
SHORT = {"Create Purchase Requisition Item": "Requisition", "Create Purchase Order Item": "PO created",
         "Record Goods Receipt": "Goods receipt", "Record Invoice Receipt": "Invoice receipt",
         "Vendor creates invoice": "Vendor invoice", "Clear Invoice": "Payment (clear invoice)",
         "Remove Payment Block": "Payment block removed", "Set Payment Block": "Payment block set",
         "Record Service Entry Sheet": "Service entry sheet", "Receive Order Confirmation": "Order confirmation"}
CENSOR_FROM = pd.Timestamp("2018-11-01")   # orders after this have not had time to be blocked or paid

# ---------------------------------------------------------------- style
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input {font-family: 'IBM Plex Sans', sans-serif;}
  .block-container {padding-top: 2.6rem; max-width: 1480px;}
  header[data-testid="stHeader"] {background: transparent;}
  h2, h3 {letter-spacing: -0.01em; color: #0b1f3a;}
  .hero {background: linear-gradient(120deg, #0b1f3a 0%, #12355b 55%, #0a6ed1 130%); color: #fff;
         border-radius: 14px; padding: 26px 30px 22px; margin-bottom: 18px; position: relative; overflow: hidden;}
  .hero:after {content: ""; position: absolute; right: -60px; top: -60px; width: 260px; height: 260px;
               border-radius: 50%; background: rgba(145,200,246,.12);}
  .hero h1 {color: #fff; font-size: 2rem; font-weight: 700; margin: 0 0 4px; padding: 0;}
  .hero p {color: #c9d8ea; margin: 0 0 14px; font-size: 1.02rem;}
  .chip {display: inline-block; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.22);
         color: #e8f0fa; border-radius: 999px; padding: 3px 11px; margin: 0 6px 4px 0; font-size: .8rem;}
  .kpi {background: #fff; border: 1px solid #e3eaf2; border-radius: 12px; padding: 14px 16px 12px;
        box-shadow: 0 1px 2px rgba(11,31,58,.05); height: 100%;}
  .kpi .lbl {color: #5b6b7f; font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; font-weight: 600;}
  .kpi .val {font-family: 'IBM Plex Mono', monospace; font-size: 1.65rem; color: #0b1f3a; margin: 4px 0 2px;}
  .kpi .ctx {color: #5b6b7f; font-size: .82rem;}
  .kpi.warn {border-top: 4px solid #e9730c;} .kpi.bad {border-top: 4px solid #c0392b;}
  .kpi.info {border-top: 4px solid #0a6ed1;} .kpi.ok {border-top: 4px solid #188918;}
  .insight {background: #fff; border: 1px solid #e3eaf2; border-radius: 12px; padding: 16px 18px; height: 100%;}
  .insight .tag {font-size: .72rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;}
  .insight .big {font-family: 'IBM Plex Mono', monospace; font-size: 1.5rem; color: #0b1f3a; margin: 6px 0;}
  .insight .txt {color: #3d4f63; font-size: .9rem; line-height: 1.45;}
  .note {background: #eef4fb; border-left: 4px solid #0a6ed1; padding: 10px 14px; border-radius: 6px;
         color: #1d2d3e; font-size: .92rem; margin: 4px 0 12px;}
  .muted {color: #5b6b7f; font-size: .86rem;}
  section[data-testid="stSidebar"] {background: #0b1f3a;}
  section[data-testid="stSidebar"] * {color: #e8f0fa;}
  section[data-testid="stSidebar"] [data-baseweb="select"] * , section[data-testid="stSidebar"] input {color: #1d2d3e !important;}
  section[data-testid="stSidebar"] [data-baseweb="tag"] {background: #0a6ed1 !important;}
  section[data-testid="stSidebar"] [data-baseweb="tag"] * {color: #fff !important;}
  section[data-testid="stSidebar"] .stDownloadButton button {background: #0a6ed1; border: none;}
  .stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #dfe6ee;}
  .stTabs [data-baseweb="tab"] {padding: 10px 16px; font-weight: 500;}
  div[data-testid="stVerticalBlockBorderWrapper"] {background: #fff; border-radius: 12px;}
</style>""", unsafe_allow_html=True)


@alt.theme.register("p2p", enable=True)
def _theme():
    return {"config": {
        "font": "IBM Plex Sans, Helvetica Neue, Arial, sans-serif", "background": "transparent", "view": {"stroke": None},
        "axis": {"labelColor": "#5b6b7f", "titleColor": "#5b6b7f", "gridColor": "#edf1f5", "domainColor": "#cfd8e3",
                 "tickColor": "#cfd8e3", "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": 500},
        "legend": {"labelColor": "#3d4f63", "titleColor": "#5b6b7f", "labelFontSize": 11, "orient": "bottom"},
        "title": {"color": NAVY, "fontSize": 13, "anchor": "start", "fontWeight": 600}}}


# ---------------------------------------------------------------- data
@st.cache_data
def load(folder: str) -> dict[str, pd.DataFrame]:
    t = {p.stem: pd.read_parquet(p) for p in Path(folder).glob("*.parquet")}
    t["items"]["po_date"] = pd.to_datetime(t["items"]["po_date"])
    t["items"]["month"] = t["items"]["po_date"].dt.to_period("M").dt.to_timestamp()
    return t


data_dir = ROOT / "data" / "app"
demo = not (data_dir / "items.parquet").exists()
if demo:
    data_dir = ROOT / "data" / "app_demo"
if not (data_dir / "items.parquet").exists():
    st.error("No data yet. Run `make run` (real log) or `make demo` (synthetic log) first.")
    st.stop()
T = load(str(data_dir))
ALL = T["items"]
report = lambda name: json.loads((ROOT / "reports" / name).read_text()) if (ROOT / "reports" / name).exists() else None


def eur(x: float) -> str:
    x = float(x or 0)
    if x == 0:
        return "€0"
    return f"€{x / 1e9:,.2f} B" if abs(x) >= 1e9 else f"€{x / 1e6:,.1f} M" if abs(x) >= 1e6 else f"€{x / 1e3:,.0f} K"


def kpi(col, label, value, ctx, kind="info"):
    col.markdown(f"<div class='kpi {kind}'><div class='lbl'>{label}</div><div class='val'>{value}</div>"
                 f"<div class='ctx'>{ctx}</div></div>", unsafe_allow_html=True)


def insight(col, tag, color, big, txt):
    col.markdown(f"<div class='insight'><div class='tag' style='color:{color}'>{tag}</div>"
                 f"<div class='big'>{big}</div><div class='txt'>{txt}</div></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar filters
with st.sidebar:
    st.markdown("### 📦 P2P Process Intelligence")
    st.caption("Filters apply to every view except the process graph totals and the model scores.")
    months = sorted(ALL["month"].unique())
    labels = [pd.Timestamp(m).strftime("%b %Y") for m in months]
    lo, hi = st.select_slider("PO created", options=labels, value=(labels[0], labels[-1]))
    cats = st.multiselect("Matching type", sorted(ALL["item_category"].unique()), placeholder="All matching types")
    areas = st.multiselect("Spend area", sorted(ALL["spend_area"].unique()), placeholder="All spend areas")
    vendor_q = st.text_input("Vendor contains", placeholder="e.g. vendorID_0120")

m_lo, m_hi = months[labels.index(lo)], months[labels.index(hi)]
I = ALL[(ALL["month"] >= m_lo) & (ALL["month"] <= m_hi)]
if cats:
    I = I[I["item_category"].isin(cats)]
if areas:
    I = I[I["spend_area"].isin(areas)]
if vendor_q:
    I = I[I["vendor"].str.contains(vendor_q.strip(), case=False, regex=False)]
if I.empty:
    st.warning("No PO items match these filters.")
    st.stop()

with st.sidebar:
    st.markdown(f"**{len(I):,}** of {len(ALL):,} PO items selected")
    if len(I) < 50:
        st.caption("⚠️ Very small selection: rates and medians are not reliable.")
    st.download_button("⬇ Download selected items (CSV)", I.drop(columns="month").to_csv(index=False).encode(),
                       "p2p_items.csv", "text/csv", width="stretch")
    st.markdown("---")
    st.caption("Data: BPI Challenge 2019 (4TU.ResearchData, CC BY 4.0). SAP purchase-to-pay log of a "
               "multinational coatings company. Code: github.com/somalavinay879-18/p2p-process-intelligence")

# ---------------------------------------------------------------- header
ov = T["overview"].iloc[0]
st.markdown(f"""<div class='hero'><h1>P2P Process Intelligence</h1>
<p>Where time and money leak in purchasing: process mining on a real SAP purchase-to-pay event log.</p>
<span class='chip'>BPI Challenge 2019</span><span class='chip'>{int(ov['events']):,} events</span>
<span class='chip'>{int(ov['purchase_orders']):,} purchase orders</span><span class='chip'>{int(ov['vendors']):,} vendors</span>
<span class='chip'>DuckDB · SQL process mining · scikit-learn</span></div>""", unsafe_allow_html=True)
if demo:
    st.warning("Showing the small synthetic demo log. Run `make run` on the real BPI Challenge 2019 log for real results.")

blk, unblk = I.loc[I["blocked"], "cycle_days"].median(), I.loc[~I["blocked"], "cycle_days"].median()
viol = I[I["violation"]]
k = st.columns(6)
kpi(k[0], "Order value", eur(I["net_worth_eur"].sum()), f"{len(I):,} PO items", "info")
vsp = I.groupby("vendor")["net_worth_eur"].sum().sort_values(ascending=False)
conc = (f"top 2% hold {vsp.head(max(1, int(len(vsp) * .02))).sum() / vsp.sum():.0%} of spend"
        if vsp.sum() > 0 else "no order value recorded")
kpi(k[1], "Vendors", f"{len(vsp):,}", conc, "info")
kpi(k[2], "PO → payment", f"{I['cycle_days'].median():.0f} days", "median, paid items", "warn")
kpi(k[3], "Payment blocks", f"{I['blocked'].mean():.1%}",
    f"blocked items: +{blk - unblk:.0f} days to pay" if pd.notna(blk) and pd.notna(unblk) else "of items", "warn")
kpi(k[4], "Rule violations", f"{len(viol):,}", f"{len(viol) / len(I):.2%} of items", "bad")
kpi(k[5], "Value at risk", eur(viol["net_worth_eur"].sum()), "items paid against their matching rule", "bad")
st.write("")

tabs = st.tabs(["📊 Summary", "🔀 Process", "⚖️ Compliance", "🏭 Vendors", "🎯 Risk prediction", "🧪 Data & method"])

# ================================================================ summary
with tabs[0]:
    c = st.columns(4)
    ir, gr = I["ir_to_clear_days"].median(), I["po_to_gr_days"].median()
    if pd.notna(ir) and pd.notna(gr):
        where = (f"from invoice receipt to payment, vs {gr:.0f} days from order to goods receipt. "
                 + ("The wait is in finance, not in delivery." if ir > gr else "Delivery is the slower part here."))
    elif pd.notna(ir):
        where = "from invoice receipt to payment (no goods receipts in this selection)."
    else:
        where = "No paid invoices in this selection yet."
    insight(c[0], "Where time goes", BLUE, f"{ir:.0f} days" if pd.notna(ir) else "–", where)
    insight(c[1], "Cost of blocks", ORANGE, eur(I.loc[I['blocked'], 'net_worth_eur'].sum()),
            (f"of order value was held by a payment block. Blocked items pay a median "
             f"{blk:.0f} days after the order, unblocked {unblk:.0f}." if pd.notna(blk) and pd.notna(unblk)
             else "of order value was held by a payment block." if I["blocked"].any()
             else "No payment blocks in this selection."))
    top_cat = viol["item_category"].value_counts()
    insight(c[2], "Broken rules", RED, f"{len(viol):,} items",
            (f"{top_cat.iloc[0] / len(viol):.0%} are '{top_cat.index[0]}': paid before the goods arrived."
             if len(viol) else "No matching-rule violations in this selection."))
    model = report("model_payment_block.json")
    if model:
        lrm, base = model["models"]["logistic_regression"], model["block_rate_test"]
        insight(c[3], "Early warning · whole log", GREEN, f"{lrm['precision_top10']:.0%} hit rate",
                f"when buyers review the 10% riskiest new PO items, against {base:.0%} at random. "
                "Most of the signal is the vendor's own history.")
    st.write("")

    m = I.groupby("month").agg(items=("case_id", "size"), spend=("net_worth_eur", "sum"),
                               block=("blocked", "mean"), viol=("violation", "mean")).reset_index()
    l, r = st.columns([3, 2])
    with l:
        with st.container(border=True):
            st.markdown("**Order value and payment-block rate by month of PO creation**")
            layers = []
            if m["month"].max() >= CENSOR_FROM:
                layers.append(alt.Chart(pd.DataFrame({"a": [max(CENSOR_FROM, m["month"].min())],
                                                      "b": [m["month"].max() + pd.offsets.MonthEnd()]})
                                        ).mark_rect(color="#f2f4f7", opacity=.9).encode(x="a:T", x2="b:T"))
            bars = alt.Chart(m).mark_bar(color=SKY, cornerRadiusTopLeft=3, cornerRadiusTopRight=3, width={"band": .75}).encode(
                x=alt.X("yearmonth(month):T", title=None, axis=alt.Axis(format="%b %y")),
                y=alt.Y("spend:Q", title="order value (€)", axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("yearmonth(month):T", title="month"), alt.Tooltip("items:Q", format=","),
                         alt.Tooltip("spend:Q", format=",.0f", title="order value €"),
                         alt.Tooltip("block:Q", format=".1%", title="payment-block rate")])
            line = alt.Chart(m).mark_line(color=ORANGE, strokeWidth=3, point=alt.OverlayMarkDef(color=ORANGE, size=40)).encode(
                x="yearmonth(month):T", y=alt.Y("block:Q", title="payment-block rate", axis=alt.Axis(format="%", titleColor=ORANGE)))
            st.altair_chart(alt.layer(*layers, bars, line).resolve_scale(y="independent").properties(height=300), width="stretch")
            if layers:
                st.caption("Grey area: orders created near the end of the log have not had time to be blocked or "
                           "paid, so the drop there is not an improvement.")
    with r:
        with st.container(border=True):
            st.markdown("**Spend areas: value and block rate**")
            sa = (I.groupby("spend_area").agg(spend=("net_worth_eur", "sum"), items=("case_id", "size"),
                                               block=("blocked", "mean")).nlargest(10, "spend").reset_index())
            st.altair_chart(alt.Chart(sa).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("spend_area:N", sort="-x", title=None, axis=alt.Axis(labelLimit=170, labelOverlap=False)),
                x=alt.X("spend:Q", title="order value (€)", axis=alt.Axis(format="~s")),
                color=alt.Color("block:Q", title="payment-block rate", scale=alt.Scale(scheme="oranges"),
                                legend=alt.Legend(format=".0%", orient="top", gradientLength=160, titleOrient="left")),
                tooltip=["spend_area", alt.Tooltip("items:Q", format=","), alt.Tooltip("spend:Q", format=",.0f"),
                         alt.Tooltip("block:Q", format=".1%", title="payment-block rate")]
            ).properties(height=330), width="stretch")

# ================================================================ process
with tabs[1]:
    st.markdown("<div class='note'>Each arrow means <b>activity A was directly followed by B</b> in the same PO item. "
                "Thicker = more often; <span style='color:#c0392b'><b>red</b></span> = slow (median over 14 days). "
                "The graph counts all events of the chosen matching type.</div>", unsafe_allow_html=True)
    dc = T.get("dfg_category")
    pc1, pc2 = st.columns([2, 3])
    pick = pc1.selectbox("Matching type", ["All"] + sorted(ALL["item_category"].unique()))
    if dc is not None:
        d = dc if pick == "All" else dc[dc["item_category"] == pick]
        d = (d.assign(w=d["median_days"] * d["frequency"]).groupby(["source", "target"], as_index=False)
             .agg(frequency=("frequency", "sum"), w=("w", "sum")))
        d["median_days"] = d["w"] / d["frequency"]   # frequency-weighted across categories (approximation for "All")
    else:
        d = T["dfg"]
    d = d.sort_values("frequency", ascending=False)
    keep = pc2.slider("Transitions shown", 5, int(min(40, len(d))), int(min(14, len(d))))
    top = d.head(keep)
    mx = top["frequency"].max()
    node_freq = pd.concat([top.groupby("source")["frequency"].sum(), top.groupby("target")["frequency"].sum()]
                          ).groupby(level=0).max()
    lines = ['digraph { rankdir=TB; bgcolor="transparent"; nodesep=0.45; ranksep=0.4;',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=14, penwidth=1.3, margin="0.2,0.08"];',
             'edge [fontname="Helvetica", fontsize=11, arrowsize=0.8];']
    for n, f in node_freq.items():
        shade = int(235 - 120 * f / node_freq.max())
        fill = f"#{shade - 40:02x}{shade:02x}{255:02x}" if shade - 40 > 0 else "#0a6ed1"
        font = "white" if shade < 165 else "#0b1f3a"
        lines.append(f'"{n}" [fillcolor="{fill}", color="#0a6ed1", fontcolor="{font}", label="{SHORT.get(n, n)}\\n{int(f):,}"];')
    for e in top.itertuples():
        colr = RED if e.median_days > 14 else "#5b6b7f"
        lines.append(f'"{e.source}" -> "{e.target}" [label="{e.frequency:,}  ·  {e.median_days:.1f} d", '
                     f'penwidth={0.8 + 5 * e.frequency / mx:.1f}, color="{colr}", fontcolor="{colr}"];')
    with st.container(border=True):
        st.graphviz_chart("\n".join(lines) + "}", width="stretch")

    l, r = st.columns([1, 1])
    with l:
        with st.container(border=True):
            st.markdown("**Median timeline per matching type** (days after the PO is created)")
            tl = []
            for cat, g in I.groupby("item_category"):
                for step, col in [("Goods receipt", "po_to_gr_days"), ("Invoice receipt", "po_to_ir_days"),
                                  ("Payment", "cycle_days")]:
                    v = g[col].median()
                    if pd.notna(v):
                        tl.append({"category": cat, "step": step, "days": v, "items": int(g[col].notna().sum())})
            tl = pd.DataFrame(tl)
            if not tl.empty:
                span = tl.groupby("category")["days"].max().reset_index().assign(start=0.0)
                base = alt.Chart(span).mark_rule(color="#cfd8e3", strokeWidth=6).encode(
                    y=alt.Y("category:N", title=None, axis=alt.Axis(labelLimit=200)), x="start:Q", x2="days:Q")
                pts = alt.Chart(tl).mark_point(filled=True, size=170, opacity=1).encode(
                    y="category:N", x=alt.X("days:Q", title="median days after PO creation"),
                    color=alt.Color("step:N", scale=alt.Scale(domain=["Goods receipt", "Invoice receipt", "Payment"],
                                                              range=[BLUE, ORANGE, GREEN]), title=None),
                    shape=alt.Shape("step:N", scale=alt.Scale(range=["circle", "diamond", "square"]), title=None),
                    tooltip=["category", "step", alt.Tooltip("days:Q", format=".1f"), alt.Tooltip("items:Q", format=",")])
                st.altair_chart((base + pts).properties(height=260), width="stretch")
    with r:
        with st.container(border=True):
            st.markdown("**Most common process variants**")
            v = T["variants"].head(12).copy()
            v["variant"] = (v["variant"].str.replace("Create Purchase Order Item", "PO")
                            .str.replace("Create Purchase Requisition Item", "Requisition")
                            .str.replace("Record Goods Receipt", "GR").str.replace("Record Invoice Receipt", "IR")
                            .str.replace("Vendor creates invoice", "Vendor invoice").str.replace("Clear Invoice", "Pay")
                            .str.replace("Remove Payment Block", "Unblock").str.replace(" > ", " → "))
            st.dataframe(v[["variant", "items", "share", "median_cycle_days"]], hide_index=True, width="stretch", height=300,
                         column_config={"variant": st.column_config.TextColumn("path (GR = goods receipt, IR = invoice receipt)", width="medium"),
                                        "items": st.column_config.NumberColumn(format="localized"),
                                        "share": st.column_config.ProgressColumn("share", format="percent", min_value=0,
                                                                                 max_value=float(v["share"].max())),
                                        "median_cycle_days": st.column_config.NumberColumn("days to pay", format="%.0f")})
            st.caption(f"Variants over the whole log; the top 5 cover {T['variants']['share'].head(5).sum():.0%} of items.")

# ================================================================ compliance
with tabs[2]:
    st.markdown("<div class='note'><b>Matching rules.</b> <b>3-way, invoice after GR</b>: the invoice may only be "
                "recorded after the goods receipt. <b>3-way, invoice before GR</b>: the invoice may come first, but "
                "payment needs the goods receipt. <b>2-way</b>: no goods receipt expected. "
                "<b>Consignment</b>: no invoice per item. A violation is an item handled against its own rule.</div>",
                unsafe_allow_html=True)
    comp = (I.groupby("item_category").agg(items=("case_id", "size"), violations=("violation", "sum"),
                                           value=("net_worth_eur", lambda s: s[I.loc[s.index, "violation"]].sum()),
                                           block=("blocked", "mean"), days=("cycle_days", "median"))
            .reset_index().sort_values("items", ascending=False))
    comp["rate"] = comp["violations"] / comp["items"]
    l, r = st.columns([1, 1])
    with l:
        with st.container(border=True):
            st.markdown("**Violations and value at risk by matching type**")
            st.altair_chart(alt.Chart(comp).mark_bar(color=RED, cornerRadiusEnd=3).encode(
                y=alt.Y("item_category:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
                x=alt.X("value:Q", title="value of violating items (€)", axis=alt.Axis(format="~s")),
                tooltip=["item_category", alt.Tooltip("items:Q", format=","), "violations",
                         alt.Tooltip("rate:Q", format=".2%"), alt.Tooltip("value:Q", format=",.0f")]
            ).properties(height=260), width="stretch")
            st.caption("All violations are in one matching type: invoices paid before the goods receipt.")
    with r:
        with st.container(border=True):
            st.markdown("**Violations by month of PO creation**")
            mv = I.groupby("month").agg(violations=("violation", "sum"), rate=("violation", "mean")).reset_index()
            st.altair_chart(alt.Chart(mv).mark_area(line={"color": RED}, color=alt.Gradient(
                gradient="linear", stops=[alt.GradientStop(color="#ffffff", offset=0), alt.GradientStop(color="#f3b8b0", offset=1)],
                x1=1, x2=1, y1=1, y2=0)).encode(
                x=alt.X("yearmonth(month):T", title=None, axis=alt.Axis(format="%b %y")),
                y=alt.Y("violations:Q", title="violating items"),
                tooltip=[alt.Tooltip("yearmonth(month):T", title="month"), "violations", alt.Tooltip("rate:Q", format=".2%")]
            ).properties(height=290), width="stretch")
    with st.container(border=True):
        st.markdown("**By matching type**")
        st.dataframe(comp, hide_index=True, width="stretch", column_config={
                "item_category": "matching type", "items": st.column_config.NumberColumn(format="localized"),
                "value": st.column_config.NumberColumn("value at risk (€)", format="localized"),
                "block": st.column_config.NumberColumn("block rate", format="percent"),
                "days": st.column_config.NumberColumn("days to pay", format="%.0f"),
                "rate": st.column_config.NumberColumn("violation rate", format="percent")})
    with st.container(border=True):
        st.markdown(f"**Violating items, largest value first** — {len(viol):,} items, {eur(viol['net_worth_eur'].sum())}")
        cols = ["case_id", "po_date", "vendor", "item_category", "spend_area", "net_worth_eur", "blocked", "cycle_days"]
        st.dataframe(viol.sort_values("net_worth_eur", ascending=False)[cols].head(500), hide_index=True,
                     width="stretch", height=320, column_config={
                         "po_date": st.column_config.DateColumn("PO created"),
                         "net_worth_eur": st.column_config.NumberColumn("value (€)", format="localized"),
                         "cycle_days": st.column_config.NumberColumn("days to pay", format="%.0f")})
        st.download_button("⬇ Download all violating items (CSV)", viol[cols].to_csv(index=False).encode(),
                           "p2p_violations.csv", "text/csv")

# ================================================================ vendors
with tabs[3]:
    vs = (I.groupby("vendor").agg(items=("case_id", "size"), spend=("net_worth_eur", "sum"),
                                  block=("blocked", "mean"), viol=("violation", "mean"),
                                  price=("price_changed", "mean"), gr_days=("po_to_gr_days", "median"),
                                  pay_days=("cycle_days", "median")).reset_index())
    min_items = st.slider("Only vendors with at least this many PO items", 5, 500, 30, step=5)
    vs = vs[(vs["items"] >= min_items) & (vs["spend"] > 0)].copy()
    if vs.empty:
        st.info("No vendor has that many items in this selection.")
    else:
        rate = I["blocked"].mean()
        med_spend = vs["spend"].median()
        vs["blocked_value"] = vs["spend"] * vs["block"]
        vs["segment"] = np.select(
            [(vs["spend"] >= med_spend) & (vs["block"] >= rate), (vs["spend"] >= med_spend),
             (vs["block"] >= rate)], ["Fix first", "Strategic, smooth", "Noisy, small"], "Low priority")
        seg_col = alt.Scale(domain=["Fix first", "Strategic, smooth", "Noisy, small", "Low priority"],
                            range=[RED, BLUE, ORANGE, "#b8c4d0"])
        l, r = st.columns([3, 2])
        with l:
            with st.container(border=True):
                st.markdown("**Supplier matrix: spend vs payment-block rate**")
                pts = alt.Chart(vs).mark_circle(opacity=.75, stroke="white", strokeWidth=.6).encode(
                    x=alt.X("spend:Q", scale=alt.Scale(type="log", domain=[float(vs["spend"].min()) * .8, float(vs["spend"].max()) * 1.2]), title="spend (€, log scale)", axis=alt.Axis(format="~s")),
                    y=alt.Y("block:Q", title="items with payment block", axis=alt.Axis(format="%")),
                    size=alt.Size("items:Q", legend=None, scale=alt.Scale(range=[25, 600])),
                    color=alt.Color("segment:N", scale=seg_col, title=None),
                    tooltip=["vendor", alt.Tooltip("items:Q", format=","), alt.Tooltip("spend:Q", format=",.0f"),
                             alt.Tooltip("block:Q", format=".1%", title="block rate"), "segment",
                             alt.Tooltip("gr_days:Q", format=".1f", title="median days to goods receipt")])
                rules = (alt.Chart(pd.DataFrame({"y": [rate]})).mark_rule(strokeDash=[5, 4], color=GREY).encode(y="y:Q")
                         + alt.Chart(pd.DataFrame({"x": [med_spend]})).mark_rule(strokeDash=[5, 4], color=GREY).encode(x="x:Q"))
                st.altair_chart((rules + pts).properties(height=420).interactive(), width="stretch")
                st.caption("Dashed lines: median vendor spend and the overall block rate. Scroll to zoom.")
        with r:
            with st.container(border=True):
                st.markdown("**Fix first: the most blocked value**")
                ff = vs.nlargest(12, "blocked_value")[["vendor", "items", "spend", "block", "blocked_value"]]
                st.dataframe(ff, hide_index=True, width="stretch", height=420, column_config={
                    "items": st.column_config.NumberColumn(format="localized"),
                    "spend": st.column_config.NumberColumn("spend (€)", format="compact"),
                    "block": st.column_config.ProgressColumn("block rate", format="percent", min_value=0, max_value=1),
                    "blocked_value": st.column_config.NumberColumn("blocked value (€)", format="compact")})

        with st.container(border=True):
            st.markdown("**Vendor profile**")
            choice = st.selectbox("Vendor", vs.sort_values("spend", ascending=False)["vendor"], label_visibility="collapsed")
            g = I[I["vendor"] == choice]
            row = vs[vs["vendor"] == choice].iloc[0]
            q = st.columns(5)
            kpi(q[0], "Spend", eur(row["spend"]), f"{int(row['items']):,} PO items", "info")
            kpi(q[1], "Block rate", f"{row['block']:.1%}", f"overall {rate:.1%}", "warn" if row["block"] > rate else "ok")
            kpi(q[2], "Price changes", f"{row['price']:.1%}", "items with a price change", "info")
            kpi(q[3], "Days to goods receipt", f"{row['gr_days']:.1f}" if pd.notna(row["gr_days"]) else "–", "median", "info")
            kpi(q[4], "Days to payment", f"{row['pay_days']:.0f}" if pd.notna(row["pay_days"]) else "–", "median", "info")
            gm = g.groupby("month").agg(items=("case_id", "size"), block=("blocked", "mean")).reset_index()
            a, b = st.columns([3, 2])
            a.altair_chart(alt.layer(
                alt.Chart(gm).mark_bar(color=SKY).encode(x=alt.X("yearmonth(month):T", title=None, axis=alt.Axis(format="%b %y")),
                                                         y=alt.Y("items:Q", title="PO items")),
                alt.Chart(gm).mark_line(color=ORANGE, strokeWidth=2.5, point=True).encode(
                    x="yearmonth(month):T", y=alt.Y("block:Q", title="block rate", axis=alt.Axis(format="%", titleColor=ORANGE)))
            ).resolve_scale(y="independent").properties(height=220), width="stretch")
            mix = g.groupby("spend_area")["net_worth_eur"].sum().nlargest(6).reset_index()
            b.altair_chart(alt.Chart(mix).mark_arc(innerRadius=55).encode(
                theta="net_worth_eur:Q", color=alt.Color("spend_area:N", title=None, scale=alt.Scale(scheme="tableau10")),
                tooltip=["spend_area", alt.Tooltip("net_worth_eur:Q", format=",.0f", title="€")]
            ).properties(height=220), width="stretch")

# ================================================================ prediction
with tabs[4]:
    model = report("model_payment_block.json")
    rs = T.get("risk_scores")
    if not model or rs is None:
        st.info("Run the pipeline to train the model.")
    else:
        st.markdown(f"<div class='note'><b>The question:</b> when a PO item is created, will it get a payment block "
                    f"within 120 days? Trained on {model['n_train']:,} items ({model['train_period'][0][:10]} – "
                    f"{model['train_period'][1][:10]}), tested on the next {model['n_test']:,} "
                    f"({model['test_period'][0][:10]} – {model['test_period'][1][:10]}). Only facts known at creation "
                    "are used; vendor history comes from earlier orders only.</div>", unsafe_allow_html=True)
        rs = rs.sort_values("risk", ascending=False).reset_index(drop=True)
        n, pos = len(rs), rs["target"].sum()
        l, r = st.columns([3, 2])
        with r:
            with st.container(border=True):
                st.markdown("**How many items can buyers review?**")
                share = st.slider("Review the riskiest share of new PO items", 1, 50, 10, format="%d%%") / 100
                top_n = max(1, int(n * share))
                hit = rs["target"].head(top_n).sum()
                q = st.columns(2)
                kpi(q[0], "Items to review", f"{top_n:,}", f"{share:.0%} of {n:,}", "info")
                kpi(q[1], "Blocks caught", f"{hit / pos:.0%}", f"{int(hit):,} of {int(pos):,}", "ok")
                st.write("")
                q = st.columns(2)
                kpi(q[0], "Hit rate", f"{hit / top_n:.0%}", f"random: {pos / n:.0%}", "warn")
                kpi(q[1], "Lift", f"{(hit / top_n) / (pos / n):.1f}×", "vs reviewing at random", "warn")
        with l:
            with st.container(border=True):
                st.markdown("**Gains curve: share of payment blocks caught vs share of items reviewed**")
                pts = np.linspace(0.01, 1, 60)
                rows = []
                for name, col in [("Logistic regression", "risk"), ("Vendor history only", "vendor_block_rate_hist")]:
                    rng = np.random.default_rng(0).random(n)
                    order = np.lexsort((rng, -rs[col].to_numpy()))
                    cum = np.cumsum(rs["target"].to_numpy()[order]) / pos
                    rows += [{"model": name, "reviewed": p, "caught": cum[max(0, int(n * p) - 1)]} for p in pts]
                rows += [{"model": "Random", "reviewed": p, "caught": p} for p in pts]
                g = pd.DataFrame(rows)
                chart = alt.Chart(g).mark_line(strokeWidth=2.5).encode(
                    x=alt.X("reviewed:Q", axis=alt.Axis(format="%"), title="share of new items reviewed (riskiest first)"),
                    y=alt.Y("caught:Q", axis=alt.Axis(format="%"), title="share of payment blocks caught"),
                    color=alt.Color("model:N", scale=alt.Scale(domain=["Logistic regression", "Vendor history only", "Random"],
                                                               range=[BLUE, ORANGE, GREY]), title=None),
                    strokeDash=alt.condition(alt.datum.model == "Random", alt.value([5, 4]), alt.value([1, 0])),
                    tooltip=["model", alt.Tooltip("reviewed:Q", format=".0%"), alt.Tooltip("caught:Q", format=".0%")])
                mark = alt.Chart(pd.DataFrame({"x": [share]})).mark_rule(color=NAVY, strokeDash=[2, 2]).encode(x="x:Q")
                st.altair_chart((chart + mark).properties(height=330), width="stretch")

        l, r = st.columns([1, 1])
        with l:
            with st.container(border=True):
                st.markdown("**Model comparison on the test period**")
                mdf = pd.DataFrame([{"model": k.replace("baseline_", "baseline: ").replace("_", " "), **v}
                                    for k, v in model["models"].items()])
                st.dataframe(mdf, hide_index=True, width="stretch", column_config={
                    "roc_auc": st.column_config.NumberColumn("ROC-AUC", format="%.3f"),
                    "pr_auc": st.column_config.NumberColumn("PR-AUC", format="%.3f"),
                    "precision_top10": st.column_config.ProgressColumn("hit rate, top 10%", format="percent",
                                                                       min_value=0, max_value=1)})
                st.caption("Honest reading: the vendor's own history carries most of the signal; the models add a "
                           "little on top. Gradient boosting does not beat the simpler logistic regression here.")
        with r:
            with st.container(border=True):
                st.markdown("**What raises or lowers the risk** (logistic-regression weights)")
                co = T.get("model_coefficients")
                if co is not None:
                    co = co[~co["feature"].str.startswith("cat__company")].copy()
                    f = co["feature"].str.replace("cat__", "").str.replace("num__", "").str.replace("infrequent_sklearn", "other")
                    for col, lab in [("item_category_", "matching: "), ("document_type_", "document: "),
                                     ("spend_area_", "spend area: "), ("spend_class_", "spend class: "),
                                     ("vendor_block_rate_hist", "vendor's past block rate"),
                                     ("vendor_items_hist", "vendor's past item count"), ("log_value", "order value (log)"),
                                     ("has_requisition", "has a requisition")]:
                        f = f.str.replace(col, lab, regex=False)
                    co["feature"] = f
                    co = co.reindex(co["coefficient"].abs().sort_values(ascending=False).index).head(12)
                    st.altair_chart(alt.Chart(co).mark_bar(cornerRadiusEnd=3).encode(
                        y=alt.Y("feature:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
                        x=alt.X("coefficient:Q", title="weight (log-odds, standardised numbers)"),
                        color=alt.condition(alt.datum.coefficient > 0, alt.value(ORANGE), alt.value(BLUE)),
                        tooltip=["feature", alt.Tooltip("coefficient:Q", format=".2f")]).properties(height=340), width="stretch")

        with st.container(border=True):
            st.markdown("**Review list: riskiest PO items in the test period**")
            wl = rs.copy()
            if cats:
                wl = wl[wl["item_category"].isin(cats)]
            if areas:
                wl = wl[wl["spend_area"].isin(areas)]
            if vendor_q:
                wl = wl[wl["vendor"].str.contains(vendor_q.strip(), case=False, regex=False)]
            wl["outcome"] = np.where(wl["target"] == 1, "🟠 was blocked", "✅ no block")
            st.dataframe(wl.head(300)[["case_id", "po_created", "vendor", "item_category", "spend_area",
                                       "value_at_creation", "risk", "outcome"]],
                         hide_index=True, width="stretch", height=330, column_config={
                             "po_created": st.column_config.DatetimeColumn("PO created", format="YYYY-MM-DD"),
                             "value_at_creation": st.column_config.NumberColumn("value (€)", format="localized"),
                             "risk": st.column_config.ProgressColumn("predicted risk", format="percent", min_value=0, max_value=1)})
            st.caption("This is what a buyer would get each morning: new items ranked by risk, so price or quantity "
                       "mismatches are fixed before the invoice arrives. 'Outcome' shows what really happened.")

# ================================================================ data & method
with tabs[5]:
    l, r = st.columns([1, 1])
    with l:
        with st.container(border=True):
            st.markdown("**Data-quality checks**")
            dq = report("data_quality.json")
            if dq:
                dq = pd.DataFrame(dq)
                dq["status"] = dq.apply(lambda x: "✅ passed" if x["passed"] else
                                        ("❌ error" if x["severity"] == "error" else "⚠️ handled"), axis=1)
                st.dataframe(dq[["status", "check", "rows", "meaning"]], hide_index=True, width="stretch",
                             column_config={"rows": st.column_config.NumberColumn(format="localized"),
                                            "meaning": st.column_config.TextColumn(width="large")})
            st.caption("Errors stop the pipeline; warnings are handled and counted.")
    with r:
        with st.container(border=True):
            st.markdown("**Pipeline**")
            st.graphviz_chart("""digraph { rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled",
              fillcolor="#eef4fb", color="#0a6ed1", fontname="Helvetica", fontsize=10];
              x [label="XES log\\n1.5 M events"]; d [label="DuckDB\\nraw tables"]; s [label="SQL staging\\n+ 7 checks"];
              p [label="Process mining\\nSQL"]; m [label="Payment-block\\nmodel"]; a [label="Dashboard"];
              x -> d -> s -> p -> a; p -> m -> a; }""", width="stretch")
            st.markdown("""
- **Ingestion:** the 700 MB XES file is streamed one trace at a time into Parquet and DuckDB.
- **Process mining:** ordered events, directly-follows graph, variants and step durations in plain SQL.
- **Compliance:** every item is checked against its own matching rule (2-way, 3-way before/after GR, consignment).
- **Model:** time-based split, 120-day horizon, vendor history from earlier orders only, compared with two baselines.
- **Tests:** a synthetic log with planted violations and blocks, so every expected number is known.
""")
    with st.container(border=True):
        st.markdown("**Limitations**")
        st.markdown("""
- The log has no payment terms, so lost cash discounts cannot be measured.
- Payment blocks are mostly set automatically; often only their removal is logged, so either event counts as a block.
- The log ends in January 2019: recent orders are still open, which is why late months look better than they are.
- Matching rules are checked from event order; approved exceptions in SAP are not visible in the log.
""")
