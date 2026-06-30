import requests

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


def get_us_gaap_tags(ticker):
    ticker_map = get_ticker_map()
    ticker = ticker.upper().strip()
    if ticker not in ticker_map:
        raise ValueError(f"Ticker '{ticker}' not found.")
    cik = ticker_map[ticker]
    resp = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    print(f"Loaded: {data.get('entityName')}  ({len(data['facts']['us-gaap'])} us-gaap tags)\n")
    return data["facts"]["us-gaap"]


def search_tags(us_gaap_tags, search_terms):
    """search_terms: dict of { label: [keyword, keyword, ...] }
    Prints every tag name containing any of the given keywords."""
    for label, terms in search_terms.items():
        matches = set()
        for tag in us_gaap_tags:
            for term in terms:
                if term in tag.lower():
                    matches.add(tag)
        print(f"--- {label} ---")
        if matches:
            for m in sorted(matches):
                print(f"  {m}")
        else:
            print("  (no matches found)")
        print()


# ── EDIT THESE TWO THINGS PER INVESTIGATION ─────────────────────────
TICKER_TO_CHECK = "ETSY"
SEARCH_TERMS = {
    "Debt (broad)": ["debt", "convertiblenotes", "notespayable"],
}

# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tags = get_us_gaap_tags(TICKER_TO_CHECK)
    search_tags(tags, SEARCH_TERMS)

    