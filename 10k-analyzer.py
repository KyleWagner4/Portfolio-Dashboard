from flask import Flask, request, render_template_string
import requests
from datetime import date

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Kyle Wagner wagnerkc03@yahoo.com"
}

_ticker_map_cache = None


def get_ticker_map():
    global _ticker_map_cache
    if _ticker_map_cache is None:
        resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS)
        resp.raise_for_status()
        raw = resp.json()
        _ticker_map_cache = {
            entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
            for entry in raw.values()
        }
    return _ticker_map_cache


def period_days(entry):
    start = date.fromisoformat(entry["start"])
    end = date.fromisoformat(entry["end"])
    return (end - start).days


def get_annual_series(us_gaap_tags, tag_name):
    """Pull and clean one annual 10-K series for a given us-gaap tag.
    Handles both duration tags (income statement, cash flow) and instant
    tags (balance sheet). Dedupes by END DATE alone, preferring whichever
    entry is closest to a normal ~365-day period, then most recently filed."""
    if tag_name not in us_gaap_tags:
        return None

    entries = us_gaap_tags[tag_name]["units"].get("USD", [])
    if not entries:
        entries = us_gaap_tags[tag_name]["units"].get("USD/shares", [])

    annual_entries = []
    for e in entries:
        if e.get("form") != "10-K":
            continue
        if "start" in e:
            if period_days(e) > 300:
                annual_entries.append(e)
        else:
            annual_entries.append(e)

    seen = {}
    for e in annual_entries:
        period_key = e["end"]
        if period_key not in seen:
            seen[period_key] = e
        else:
            existing = seen[period_key]
            existing_days = period_days(existing) if "start" in existing else None
            new_days = period_days(e) if "start" in e else None
            if new_days is not None and existing_days is not None:
                if abs(new_days - 365) < abs(existing_days - 365):
                    seen[period_key] = e
                elif abs(new_days - 365) == abs(existing_days - 365) and e["filed"] > existing["filed"]:
                    seen[period_key] = e
            elif e["filed"] > existing["filed"]:
                seen[period_key] = e

    return sorted(seen.values(), key=lambda e: e["end"])


def merge_series(*series_lists):
    """Merge multiple tag series into one deduped timeline by end date,
    keeping the most recently filed value for any overlapping period."""
    merged = {}
    for series in series_lists:
        if not series:
            continue
        for e in series:
            period_key = e["end"]
            if period_key not in merged or e["filed"] > merged[period_key]["filed"]:
                merged[period_key] = e
    return sorted(merged.values(), key=lambda e: e["end"])


# ── METRIC DEFINITIONS ─────────────────────────────────────────────
# Each metric maps to one or more candidate XBRL tags, tried and merged
# together (handles tag transitions, e.g. Revenues -> RevenueFromContract...)
METRIC_TAGS = {
    # Income Statement
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "gross_profit": ["GrossProfit"],
    "operating_expenses": ["OperatingExpenses", "CostsAndExpenses"],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseNonoperating", "InterestExpenseOther"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "tax_expense": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_outstanding": ["WeightedAverageNumberOfSharesOutstandingBasic"],

    # Balance Sheet
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "stockholders_equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt", "UnsecuredLongTermDebt", "DebtAndCapitalLeaseObligations"],
    "inventory": ["InventoryNet"],
    "accounts_receivable": ["AccountsReceivableNetCurrent"],

    # Cash Flow Statement
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "investing_cash_flow": ["NetCashProvidedByUsedInInvestingActivities"],
    "financing_cash_flow": ["NetCashProvidedByUsedInFinancingActivities"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
}

# Which metrics belong on which tab, and their display labels
INCOME_STATEMENT_ROWS = [
    ("revenue", "Revenue"),
    ("cost_of_revenue", "Cost of Revenue"),
    ("gross_profit", "Gross Profit"),
    ("operating_expenses", "Operating Expenses"),
    ("operating_income", "Operating Income (EBIT)"),
    ("interest_expense", "Interest Expense"),
    ("pretax_income", "Pre-Tax Income"),
    ("tax_expense", "Income Tax Expense"),
    ("net_income", "Net Income"),
    ("eps_basic", "EPS (Basic)"),
    ("eps_diluted", "EPS (Diluted)"),
]

BALANCE_SHEET_ROWS = [
    ("total_assets", "Total Assets"),
    ("current_assets", "Current Assets"),
    ("cash", "Cash & Equivalents"),
    ("inventory", "Inventory"),
    ("accounts_receivable", "Accounts Receivable"),
    ("total_liabilities", "Total Liabilities"),
    ("current_liabilities", "Current Liabilities"),
    ("long_term_debt", "Long-Term Debt"),
    ("stockholders_equity", "Stockholders' Equity"),
]

CASH_FLOW_ROWS = [
    ("operating_cash_flow", "Operating Cash Flow"),
    ("capex", "Capital Expenditures"),
    ("free_cash_flow", "Free Cash Flow"),
    ("investing_cash_flow", "Investing Cash Flow"),
    ("financing_cash_flow", "Financing Cash Flow"),
    ("dividends_paid", "Dividends Paid"),
    ("buybacks", "Share Buybacks"),
]

RATIO_ROWS = [
    ("net_margin", "Net Margin", "pct"),
    ("gross_margin", "Gross Margin", "pct"),
    ("operating_margin", "Operating Margin", "pct"),
    ("roa", "Return on Assets (ROA)", "pct"),
    ("roe", "Return on Equity (ROE)", "pct"),
    ("current_ratio", "Current Ratio", "ratio"),
    ("debt_to_equity", "Debt / Equity", "ratio"),
    ("free_cash_flow", "Free Cash Flow", "dollars"),
]


def fetch_all_metrics(us_gaap_tags):
    """Pull every defined metric, merging tag variants where needed."""
    results = {}
    for metric_name, tag_candidates in METRIC_TAGS.items():
        series_list = [get_annual_series(us_gaap_tags, tag) for tag in tag_candidates]
        merged = merge_series(*series_list)
        results[metric_name] = merged
    return results


def combine_all_metrics(metric_series_dict):
    """Combine every metric series into one dict keyed by fiscal year,
    with computed ratios layered on top."""
    combined = {}
    for metric_name, series in metric_series_dict.items():
        for e in series or []:
            fy = e["end"][:4]
            combined.setdefault(fy, {})[metric_name] = e["val"]
            combined[fy]["period_end"] = e["end"]

    for fy, vals in combined.items():
        rev = vals.get("revenue")
        ni = vals.get("net_income")
        gp = vals.get("gross_profit")
        oi = vals.get("operating_income")
        assets = vals.get("total_assets")
        equity = vals.get("stockholders_equity")
        liabilities = vals.get("total_liabilities")
        cur_assets = vals.get("current_assets")
        cur_liabilities = vals.get("current_liabilities")
        ocf = vals.get("operating_cash_flow")
        capex = vals.get("capex")
        cogs = vals.get("cost_of_revenue")

        # Computed fallback: some companies (e.g. Ford) don't tag Gross Profit
        # directly, but it can be derived whenever both inputs are available
        if gp is None and rev is not None and cogs is not None:
            gp = rev - cogs
            vals["gross_profit"] = gp

        if ni is not None and rev:
            vals["net_margin"] = round(ni / rev * 100, 2)
        if gp is not None and rev:
            vals["gross_margin"] = round(gp / rev * 100, 2)
        if oi is not None and rev:
            vals["operating_margin"] = round(oi / rev * 100, 2)
        if ni is not None and assets:
            vals["roa"] = round(ni / assets * 100, 2)
        if ni is not None and equity and equity > 0:
            vals["roe"] = round(ni / equity * 100, 2)
        if cur_assets is not None and cur_liabilities:
            vals["current_ratio"] = round(cur_assets / cur_liabilities, 2)
        if liabilities is not None and equity and equity > 0:
            vals["debt_to_equity"] = round(liabilities / equity, 2)
        if ocf is not None and capex is not None:
            vals["free_cash_flow"] = ocf - abs(capex)

    return dict(sorted(combined.items(), reverse=True))


def fetch_company_data(ticker):
    """Full pipeline: ticker -> CIK -> raw EDGAR data -> normalized combined metrics."""
    ticker_map = get_ticker_map()
    ticker = ticker.upper().strip()

    if ticker not in ticker_map:
        return None, None, f"Ticker '{ticker}' not found in SEC EDGAR ticker list."

    cik = ticker_map[ticker]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        return None, None, f"Could not retrieve EDGAR data for '{ticker}' (CIK {cik})."

    data = resp.json()
    entity_name = data.get("entityName", ticker)
    us_gaap_tags = data.get("facts", {}).get("us-gaap", {})

    if not us_gaap_tags:
        return None, None, f"No financial data available for '{ticker}'."

    all_series = fetch_all_metrics(us_gaap_tags)
    combined = combine_all_metrics(all_series)

    return entity_name, combined, None


def fmt_dollars(val):
    if val is None:
        return "—"
    return f"${val:,.0f}"


def fmt_pct(val):
    if val is None:
        return "—"
    return f"{val:.2f}%"


def fmt_ratio(val):
    if val is None:
        return "—"
    return f"{val:.2f}x"


def fmt_eps(val):
    if val is None:
        return "—"
    return f"${val:.2f}"


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>10-K / 10-Q Filing Analyzer</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #faf8f3;
    color: #1c1c1a;
    font-family: 'Source Serif 4', Georgia, serif;
    line-height: 1.6;
  }
  .masthead {
    border-bottom: 3px double #1c1c1a;
    padding: 32px 48px 20px;
    max-width: 960px;
    margin: 0 auto;
  }
  .masthead-eyebrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #8a5a2e;
    margin-bottom: 8px;
  }
  .masthead h1 { font-size: 38px; font-weight: 700; letter-spacing: -0.5px; }
  .masthead-sub { font-size: 14px; color: #5c5a52; margin-top: 6px; font-style: italic; }

  main { max-width: 960px; margin: 0 auto; padding: 36px 48px 80px; }

  .search-box {
    display: flex; gap: 10px; margin-bottom: 36px;
    border: 1px solid #1c1c1a; padding: 4px; background: #fff;
  }
  .search-box input {
    flex: 1; border: none; padding: 12px 14px;
    font-family: 'IBM Plex Mono', monospace; font-size: 14px;
    letter-spacing: 1px; text-transform: uppercase; background: transparent;
  }
  .search-box input:focus { outline: none; }
  .search-box button {
    background: #1c1c1a; color: #faf8f3; border: none; padding: 12px 24px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    letter-spacing: 1.5px; text-transform: uppercase; cursor: pointer;
  }
  .search-box button:hover { background: #8a5a2e; }

  .error-note {
    border-left: 3px solid #a33; background: #fdf2f2; padding: 14px 18px;
    font-size: 14px; color: #7a2222; margin-bottom: 30px;
  }

  .entity-header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #d8d3c8; }
  .entity-header h2 { font-size: 26px; font-weight: 600; }
  .entity-header .meta {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8a5a2e;
    letter-spacing: 1px; text-transform: uppercase; margin-top: 4px;
  }

  .year-select-row {
    display: flex; align-items: center; gap: 12px; margin-bottom: 28px;
  }
  .year-select-row label {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 1px;
    text-transform: uppercase; color: #5c5a52;
  }
  .year-select-row select {
    font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 600;
    padding: 8px 14px; border: 1px solid #1c1c1a; background: #fff; color: #1c1c1a;
    cursor: pointer;
  }

  .tabs {
    display: flex; gap: 2px; margin-bottom: 0; border-bottom: 2px solid #1c1c1a;
  }
  .tab-button {
    font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; letter-spacing: 1px;
    text-transform: uppercase; padding: 12px 20px; background: #efe9da;
    border: 1px solid #1c1c1a; border-bottom: none; cursor: pointer;
    color: #5c5a52; position: relative; top: 2px;
  }
  .tab-button.active { background: #faf8f3; color: #1c1c1a; font-weight: 600; }
  .tab-content { display: none; padding-top: 30px; max-width: 640px; }
  .tab-content.active { display: block; }

  .stat-row {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 14px 4px; border-bottom: 1px solid #ebe7dd;
  }
  .stat-row:hover { background: #f3efe4; }
  .stat-label {
    font-size: 15px; color: #3a382f;
  }
  .stat-value {
    font-family: 'IBM Plex Mono', monospace; font-size: 16px; font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .negative { color: #a33; }

  .period-note {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #8a8475;
    margin-bottom: 18px; letter-spacing: 0.5px;
  }

  footer {
    max-width: 960px; margin: 40px auto 0; padding: 20px 48px;
    border-top: 1px solid #d8d3c8; font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px; color: #8a8475; letter-spacing: 0.5px;
  }
</style>
</head>
<body>

<div class="masthead">
  <p class="masthead-eyebrow">Filed with the U.S. Securities and Exchange Commission</p>
  <h1>10-K / 10-Q Filing Analyzer</h1>
  <p class="masthead-sub">Structured financial data, pulled directly from SEC EDGAR XBRL filings.</p>
</div>

<main>
  <form class="search-box" method="GET" action="/">
    <input type="text" name="ticker" placeholder="Enter ticker, e.g. AAPL" value="{{ ticker or '' }}" autofocus>
    <button type="submit">Analyze</button>
  </form>

  {% if error %}
  <div class="error-note">{{ error }}</div>
  {% endif %}

  {% if entity_name %}
  <div class="entity-header">
    <h2>{{ entity_name }}</h2>
    <p class="meta">{{ ticker }} &nbsp;·&nbsp; Annual figures, most recent filings, USD</p>
  </div>

  <div class="year-select-row">
    <label for="year-select">Fiscal Year</label>
    <select id="year-select" name="year" form="year-form">
      {% for fy in fiscal_years %}
      <option value="{{ fy }}" {{ 'selected' if fy == selected_year else '' }}>FY{{ fy }}</option>
      {% endfor %}
    </select>
  </div>
  <form id="year-form" method="GET" action="/" style="display:none;">
    <input type="hidden" name="ticker" value="{{ ticker }}">
  </form>
  <script>
    document.getElementById('year-select').addEventListener('change', function() {
      document.getElementById('year-form').submit();
    });
  </script>

  <div class="tabs">
    <button class="tab-button active" onclick="showTab(event, 'income')">Income Statement</button>
    <button class="tab-button" onclick="showTab(event, 'balance')">Balance Sheet</button>
    <button class="tab-button" onclick="showTab(event, 'cashflow')">Cash Flow</button>
    <button class="tab-button" onclick="showTab(event, 'ratios')">Ratios &amp; Valuation</button>
  </div>

  {% set year_data = combined.get(selected_year, {}) %}

  <div id="income" class="tab-content active">
    <p class="period-note">Period ending {{ year_data.get('period_end', '—') }}</p>
    {% for key, label in income_rows %}
      {% set val = year_data.get(key) %}
      <div class="stat-row">
        <span class="stat-label">{{ label }}</span>
        {% if key in ['eps_basic', 'eps_diluted'] %}
          <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_eps(val) }}</span>
        {% else %}
          <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_dollars(val) }}</span>
        {% endif %}
      </div>
    {% endfor %}
  </div>

  <div id="balance" class="tab-content">
    <p class="period-note">As of {{ year_data.get('period_end', '—') }}</p>
    {% for key, label in balance_rows %}
      {% set val = year_data.get(key) %}
      <div class="stat-row">
        <span class="stat-label">{{ label }}</span>
        <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_dollars(val) }}</span>
      </div>
    {% endfor %}
  </div>

  <div id="cashflow" class="tab-content">
    <p class="period-note">Period ending {{ year_data.get('period_end', '—') }}</p>
    {% for key, label in cashflow_rows %}
      {% set val = year_data.get(key) %}
      <div class="stat-row">
        <span class="stat-label">{{ label }}</span>
        <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_dollars(val) }}</span>
      </div>
    {% endfor %}
  </div>

  <div id="ratios" class="tab-content">
    <p class="period-note">Period ending {{ year_data.get('period_end', '—') }}</p>
    {% for key, label, kind in ratio_rows %}
      {% set val = year_data.get(key) %}
      <div class="stat-row">
        <span class="stat-label">{{ label }}</span>
        {% if kind == 'pct' %}
          <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_pct(val) }}</span>
        {% elif kind == 'ratio' %}
          <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_ratio(val) }}</span>
        {% else %}
          <span class="stat-value {{ 'negative' if val and val < 0 else '' }}">{{ fmt_dollars(val) }}</span>
        {% endif %}
      </div>
    {% endfor %}
  </div>

  {% endif %}
</main>

<footer>
  Data sourced from SEC EDGAR XBRL Frames API &nbsp;·&nbsp; For informational purposes only, not investment advice.
</footer>

<script>
function showTab(evt, tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-button').forEach(el => el.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  evt.currentTarget.classList.add('active');
}
</script>

</body>
</html>
"""


@app.route("/")
def index():
    ticker = request.args.get("ticker", "").strip()
    entity_name = None
    combined = None
    error = None
    fiscal_years = []
    selected_year = request.args.get("year", "")

    if ticker:
        entity_name, combined, error = fetch_company_data(ticker)
        if combined:
            fiscal_years = list(combined.keys())  # already sorted most-recent-first
            if not selected_year or selected_year not in combined:
                selected_year = fiscal_years[0]

    return render_template_string(
        PAGE_TEMPLATE,
        ticker=ticker,
        entity_name=entity_name,
        combined=combined or {},
        error=error,
        fiscal_years=fiscal_years,
        selected_year=selected_year,
        income_rows=INCOME_STATEMENT_ROWS,
        balance_rows=BALANCE_SHEET_ROWS,
        cashflow_rows=CASH_FLOW_ROWS,
        ratio_rows=RATIO_ROWS,
        fmt_dollars=fmt_dollars,
        fmt_pct=fmt_pct,
        fmt_ratio=fmt_ratio,
        fmt_eps=fmt_eps,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5050)

    