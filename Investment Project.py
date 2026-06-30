import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import numpy as np
from scipy.optimize import minimize
from fpdf import FPDF
import os
from supabase import create_client

# ─── SUPABASE ─────────────────────────────────────────────────────
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
supabase     = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

NEWS_API_KEY = st.secrets.get("NEWS_API_KEY", os.environ.get("NEWS_API_KEY", ""))


# ─── AUTH FUNCTIONS ───────────────────────────────────────────────
def get_user():
    if "access_token" not in st.session_state:
        return None
    try:
        user = supabase.auth.get_user(st.session_state.access_token)
        if user and user.user:
            st.session_state.user_id = user.user.id
            return user.user
        return None
    except:
        return None


def sign_up(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        return res.user, None
    except Exception as e:
        return None, str(e)


def sign_in(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.access_token = res.session.access_token
        st.session_state.user_id      = res.user.id
        return res.user, None
    except Exception as e:
        return None, str(e)


def sign_out():
    try:
        supabase.auth.sign_out()
    except:
        pass
    for key in ["access_token", "user_id", "holdings", "realized_gains"]:
        if key in st.session_state:
            del st.session_state[key]


def get_user_id():
    return st.session_state.get("user_id", None)


def get_auth_client():
    access_token = st.session_state.get("access_token", "")
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client.postgrest.auth(access_token)
    return client


# ─── DATABASE FUNCTIONS ───────────────────────────────────────────
def load_holdings():
    user_id = get_user_id()
    if not supabase or not user_id:
        return []
    try:
        auth_client = get_auth_client()
        result = auth_client.table("holdings").select("*").eq("user_id", user_id).execute()
        if result.data:
            return [{
                "Ticker":        r["ticker"],
                "Shares":        r["shares"],
                "Cost Basis":    r["cost_basis"],
                "Purchase Date": r.get("purchase_date", "")
            } for r in result.data]
        return []
    except:
        return []


def save_holdings(holdings):
    user_id = get_user_id()
    if not supabase or not user_id:
        return
    try:
        auth_client = get_auth_client()
        auth_client.table("holdings").delete().eq("user_id", user_id).execute()
        for h in holdings:
            auth_client.table("holdings").insert({
                "ticker":        h["Ticker"],
                "shares":        h["Shares"],
                "cost_basis":    h["Cost Basis"],
                "purchase_date": h.get("Purchase Date", str(pd.Timestamp.today().date())),
                "user_id":       user_id
            }).execute()
    except Exception as e:
        st.error(f"Database error: {e}")


def log_transaction(ticker, transaction_type, shares, price, cost_basis=None, realized_gain=None, transaction_date=None):
    user_id = get_user_id()
    if not supabase or not user_id:
        return
    try:
        auth_client = get_auth_client()
        auth_client.table("transactions").insert({
            "ticker":                 ticker,
            "transaction_type":       transaction_type,
            "shares":                 shares,
            "price":                  price,
            "cost_basis_at_time":     cost_basis,
            "realized_gain":          realized_gain,
            "transaction_date_input": transaction_date or str(pd.Timestamp.today().date()),
            "user_id":                user_id
        }).execute()
    except:
        pass


def load_transactions():
    user_id = get_user_id()
    if not supabase or not user_id:
        return []
    try:
        auth_client = get_auth_client()
        result = auth_client.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return result.data
    except:
        return []


# ─── CONFIG ───────────────────────────────────────────────────────
st.set_page_config(page_title="Portfolio Dashboard", layout="wide", page_icon="📈")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background-color: #1a1a1a; }
    .stAppHeader { background-color: #1a1a1a !important; }
    .stMain { background-color: #1a1a1a !important; }
    .stMainBlockContainer { background-color: #1a1a1a !important; }
    header[data-testid="stHeader"] { background-color: #1a1a1a !important; }
    section[data-testid="stSidebar"] {
        background-color: #141414;
        border-right: 1px solid #2a2a2a;
    }
    .metric-card {
        background: #222222;
        border: 1px solid #2a2a2a;
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 8px;
    }
    .metric-label {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        color: #888888;
        margin-bottom: 8px;
    }
    .metric-value { font-size: 28px; font-weight: 700; color: #ffffff; line-height: 1; }
    .metric-value.green { color: #00ff88; }
    .metric-value.red { color: #ff4d4d; }
    .metric-delta { font-size: 13px; font-weight: 500; margin-top: 6px; }
    .delta-green { color: #00ff88; }
    .delta-red { color: #ff4d4d; }
    .section-header {
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 2px;
        text-transform: uppercase;
        color: #888888;
        margin: 32px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #2a2a2a;
    }
    .dashboard-title {
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 3px;
        text-transform: uppercase;
        color: #888888;
        margin-bottom: 4px;
    }
    .dashboard-subtitle { font-size: 32px; font-weight: 700; color: #ffffff; margin-bottom: 8px; }
    div[data-testid="stDataFrame"] { border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; }
    div[data-testid="stDataFrame"] > div { background-color: #222222 !important; }
    iframe { background: #222222 !important; }
    [data-testid="stNumberInputContainer"] { background: #222222 !important; border: 1px solid #2a2a2a !important; border-radius: 8px !important; }
    .stButton > button {
        background: #2a2a2a; color: #ffffff; border: 1px solid #333333;
        border-radius: 8px; font-size: 12px; font-weight: 500;
        letter-spacing: 0.5px; width: 100%; transition: all 0.2s;
    }
    .stButton > button:hover { background: #333333; border-color: #4a9eff; }
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        background: #222222; border: 1px solid #2a2a2a; color: #ffffff; border-radius: 8px;
    }
    .stSelectbox > div > div { background: #222222; border: 1px solid #2a2a2a; border-radius: 8px; }
    .stTabs [data-baseweb="tab-list"] { background: #222222; border-radius: 12px; padding: 4px; gap: 16px; }
    .stTabs [data-baseweb="tab"] {
        background: transparent; border-radius: 8px; color: #888888;
        font-size: 12px; font-weight: 500; letter-spacing: 1px; text-transform: uppercase;
    }
    .stTabs [aria-selected="true"] { background: #2a2a2a !important; color: #ffffff !important; }
    .stDivider { border-color: #2a2a2a !important; }
    [data-testid="stNumberInputContainer"] > div { background: #222222 !important; }
    .stNumberInput input { background: #222222 !important; }
    div[data-testid="stDataFrame"] div[data-testid="stDataFrameGlideDataEditor"] { background: #222222 !important; }
    div[data-testid="stDataFrame"] canvas { background: #222222 !important; }
    [class*="gdg-"] { background: #222222 !important; }
</style>
""", unsafe_allow_html=True)


# ─── PLOT LAYOUT ──────────────────────────────────────────────────
PLOT_LAYOUT = dict(
    paper_bgcolor="#222222", plot_bgcolor="#222222",
    font=dict(family="Inter", color="#888888", size=11),
    xaxis=dict(gridcolor="#2a2a2a", linecolor="#2a2a2a", tickcolor="#2a2a2a"),
    yaxis=dict(gridcolor="#2a2a2a", linecolor="#2a2a2a", tickcolor="#2a2a2a"),
    legend=dict(orientation="h", bgcolor="rgba(0,0,0,0)", font=dict(color="#ffffff")),
    margin=dict(l=40, r=40, t=40, b=40),
)


# ─── DEFAULTS ─────────────────────────────────────────────────────
DEFAULT_HOLDINGS = []
INITIAL_INVESTMENT = 10000.00
START_DATE         = "2025-01-01"


# ─── AUTH SCREEN ──────────────────────────────────────────────────
user = get_user()

if not user:
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("<div style='height:80px'></div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:24px;font-weight:700;color:#ffffff;margin-bottom:6px;'>Portfolio Dashboard</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:13px;color:#888888;margin-bottom:24px;'>Sign in to access your portfolio</div>", unsafe_allow_html=True)

        auth_mode = st.radio("", ["Sign In", "Sign Up"], horizontal=True, label_visibility="collapsed")
        st.divider()

        email    = st.text_input("Email", placeholder="you@email.com")
        password = st.text_input("Password", type="password", placeholder="Password")

        if auth_mode == "Sign In":
            if st.button("Sign In", use_container_width=True):
                if email and password:
                    user, error = sign_in(email, password)
                    if error:
                        st.error(f"Sign in failed: {error}")
                    else:
                        st.session_state.holdings = load_holdings()
                        st.session_state.realized_gains = []
                        st.rerun()
                else:
                    st.error("Please enter your email and password.")
        else:
            if st.button("Create Account", use_container_width=True):
                if email and password:
                    user, error = sign_up(email, password)
                    if error:
                        st.error(f"Sign up failed: {error}")
                    else:
                        st.success("Account created. Check your email to confirm, then sign in.")
                else:
                    st.error("Please enter your email and password.")
    st.stop()


# ─── SESSION STATE ────────────────────────────────────────────────
if "holdings" not in st.session_state:
    st.session_state.holdings = load_holdings()

if "realized_gains" not in st.session_state:
    st.session_state.realized_gains = []


# ─── SIDEBAR ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<div class='section-header'>Manage Positions</div>", unsafe_allow_html=True)

    mode = st.radio("Mode", ["Buy", "Sell"], horizontal=True, label_visibility="collapsed")

    st.divider()

    # ── BUY ───────────────────────────────────────────────────────
    if mode == "Buy":
        st.markdown("<div class='metric-label'>Buy / Add Position</div>", unsafe_allow_html=True)
        buy_ticker = st.text_input("Ticker", placeholder="Ticker e.g. VGT", key="buy_ticker").upper().strip()
        buy_shares = st.number_input("Number of Shares", min_value=0.0001, step=0.001, format="%.3f", key="buy_shares")
        buy_cost   = st.number_input("Price Paid Per Share ($)", min_value=0.01, step=0.01, format="%.2f", key="buy_cost")
        buy_date   = st.date_input("Purchase Date", value=pd.Timestamp.today(), key="buy_date")

        if st.button("+ Buy"):
            if buy_ticker:
                existing = [h["Ticker"] for h in st.session_state.holdings]
                if buy_ticker in existing:
                    holding     = next(h for h in st.session_state.holdings if h["Ticker"] == buy_ticker)
                    old_shares  = holding["Shares"]
                    old_cost    = holding["Cost Basis"]
                    new_total   = old_shares + buy_shares
                    new_avg     = ((old_shares * old_cost) + (buy_shares * buy_cost)) / new_total
                    holding["Shares"]     = round(new_total, 6)
                    holding["Cost Basis"] = round(new_avg, 4)
                    save_holdings(st.session_state.holdings)
                    log_transaction(buy_ticker, "buy", buy_shares, buy_cost, transaction_date=str(buy_date))
                    st.success(f"Updated {buy_ticker}: {new_total:.3f} shares @ ${new_avg:.2f} avg")
                    st.rerun()
                else:
                    try:
                        price = yf.Ticker(buy_ticker).fast_info["last_price"]
                        if price and price > 0:
                            st.session_state.holdings.append({
                                "Ticker":        buy_ticker,
                                "Shares":        buy_shares,
                                "Cost Basis":    buy_cost,
                                "Purchase Date": str(buy_date)
                            })
                            save_holdings(st.session_state.holdings)
                            log_transaction(buy_ticker, "buy", buy_shares, buy_cost, transaction_date=str(buy_date))
                            st.success(f"Added {buy_ticker}")
                            st.rerun()
                        else:
                            st.error(f"Could not find {buy_ticker}")
                    except Exception:
                        st.error(f"Could not find {buy_ticker}")

    # ── SELL ──────────────────────────────────────────────────────
    elif mode == "Sell":
        if not st.session_state.holdings:
            st.markdown("<div style='color:#888888;font-size:13px;'>No positions to sell.</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='metric-label'>Sell / Reduce Position</div>", unsafe_allow_html=True)
            sell_tickers = [h["Ticker"] for h in st.session_state.holdings]
            sell_ticker  = st.selectbox("Position", sell_tickers, label_visibility="collapsed", key="sell_ticker")
            sell_shares  = st.number_input("Number of Shares to Sell", min_value=0.0001, step=0.001, format="%.3f", key="sell_shares")
            sell_price   = st.number_input("Sale Price Per Share ($)", min_value=0.01, step=0.01, format="%.2f", key="sell_price")
            sell_date    = st.date_input("Sale Date", value=pd.Timestamp.today(), key="sell_date")

            if st.button("- Sell"):
                holding = next(h for h in st.session_state.holdings if h["Ticker"] == sell_ticker)
                if sell_shares > holding["Shares"]:
                    st.error(f"You only have {holding['Shares']:.3f} shares of {sell_ticker}")
                else:
                    realized_gain       = (sell_price - holding["Cost Basis"]) * sell_shares
                    remaining           = round(holding["Shares"] - sell_shares, 6)
                    cost_basis_snapshot = holding["Cost Basis"]
                    if remaining == 0:
                        st.session_state.holdings = [h for h in st.session_state.holdings if h["Ticker"] != sell_ticker]
                        st.success(f"Closed {sell_ticker} position")
                    else:
                        holding["Shares"] = remaining
                        st.success(f"Sold {sell_shares:.3f} shares of {sell_ticker}")
                    st.session_state.realized_gains.append({
                        "Ticker":        sell_ticker,
                        "Shares Sold":   sell_shares,
                        "Sale Price":    sell_price,
                        "Cost Basis":    cost_basis_snapshot,
                        "Realized Gain": round(realized_gain, 2),
                        "Date":          str(sell_date)
                    })
                    save_holdings(st.session_state.holdings)
                    log_transaction(sell_ticker, "sell", sell_shares, sell_price, cost_basis_snapshot, realized_gain, transaction_date=str(sell_date))
                    st.rerun()

    # ── EDIT ──────────────────────────────────────────────────────
    elif mode == "Edit":
        if not st.session_state.holdings:
            st.markdown("<div style='color:#888888;font-size:13px;'>No positions to edit.</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='metric-label'>Edit Position</div>", unsafe_allow_html=True)
            edit_tickers = [h["Ticker"] for h in st.session_state.holdings]
            edit_ticker  = st.selectbox("Position", edit_tickers, label_visibility="collapsed", key="edit_ticker")
            holding      = next(h for h in st.session_state.holdings if h["Ticker"] == edit_ticker)
            edit_shares  = st.number_input("Shares", value=float(holding["Shares"]), min_value=0.0001, step=0.001, format="%.3f", label_visibility="collapsed", key="edit_shares")
            edit_cost    = st.number_input("Cost Basis", value=float(holding["Cost Basis"]), min_value=0.01, step=0.01, format="%.2f", label_visibility="collapsed", key="edit_cost")

            if st.button("Update"):
                holding["Shares"]     = round(edit_shares, 6)
                holding["Cost Basis"] = round(edit_cost, 4)
                save_holdings(st.session_state.holdings)
                log_transaction(edit_ticker, "edit", edit_shares, edit_cost)
                st.success(f"Updated {edit_ticker}")
                st.rerun()

            st.divider()

            if st.button("Remove Position"):
                st.session_state.holdings = [h for h in st.session_state.holdings if h["Ticker"] != edit_ticker]
                save_holdings(st.session_state.holdings)
                st.success(f"Removed {edit_ticker}")
                st.rerun()

    st.divider()

    if st.button("Reset to Default"):
        st.session_state.holdings       = []
        st.session_state.realized_gains = []
        save_holdings([])
        st.rerun()

    st.divider()

    st.markdown("<div class='metric-label'>Export</div>", unsafe_allow_html=True)
    generate_pdf = st.button("Generate PDF Report")

    st.divider()

    if st.button("Sign Out"):
        sign_out()
        st.rerun()

    if st.session_state.realized_gains:
        st.divider()
        st.markdown("<div class='metric-label'>Realized Gains This Session</div>", unsafe_allow_html=True)
        total_realized = sum(g["Realized Gain"] for g in st.session_state.realized_gains)
        color = "#00ff88" if total_realized >= 0 else "#ff4d4d"
        st.markdown(f"<div style='font-size:18px;font-weight:700;color:{color};'>${total_realized:,.2f}</div>", unsafe_allow_html=True)
        for g in st.session_state.realized_gains:
            gain_color = "#00ff88" if g["Realized Gain"] >= 0 else "#ff4d4d"
            st.markdown(f"<div style='font-size:11px;color:#888888;margin-top:6px;'>{g['Date']} · {g['Ticker']} · {g['Shares Sold']:.3f} shares · <span style='color:{gain_color};'>${g['Realized Gain']:,.2f}</span></div>", unsafe_allow_html=True)


# ─── FETCH DATA ───────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_prices(tickers):
    prices = {}
    for t in tickers:
        try:
            prices[t] = yf.Ticker(t).fast_info["last_price"]
        except:
            prices[t] = None
    return prices


@st.cache_data(ttl=3600)
def get_history(tickers, start):
    if not tickers:
        return pd.DataFrame()
    df = yf.download(list(tickers), start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.dropna(how="all")


@st.cache_data(ttl=3600)
def get_news(tickers):
    articles = []
    for ticker in tickers:
        try:
            info  = yf.Ticker(ticker).info
            query = info.get("longName") or info.get("shortName") or ticker
        except:
            query = ticker
        url = (f"https://newsapi.org/v2/everything?q={query}"
               f"&sortBy=publishedAt&pageSize=3&language=en&apiKey={NEWS_API_KEY}")
        try:
            r = requests.get(url).json()
            if r.get("status") == "ok":
                for a in r.get("articles", []):
                    if a.get("title") and a.get("url"):
                        articles.append({
                            "ticker":      ticker,
                            "title":       a.get("title", ""),
                            "source":      a.get("source", {}).get("name", ""),
                            "published":   a.get("publishedAt", "")[:10],
                            "url":         a.get("url", ""),
                            "description": a.get("description", ""),
                        })
        except Exception:
            pass
    return articles


# ─── HEADER ───────────────────────────────────────────────────────
st.markdown("<div class='dashboard-title'>Personal Finance</div>", unsafe_allow_html=True)
st.markdown("<div class='dashboard-subtitle'>Portfolio Dashboard</div>", unsafe_allow_html=True)
st.markdown(f"<div style='font-size:11px;color:#888888;letter-spacing:1px;margin-bottom:24px;'>LAST UPDATED &nbsp;·&nbsp; {pd.Timestamp.now().strftime('%B %d, %Y  %I:%M %p')}</div>", unsafe_allow_html=True)


# ─── EMPTY STATE ──────────────────────────────────────────────────
if not st.session_state.holdings:
    st.markdown("""
    <div class='metric-card' style='text-align:center;padding:60px 24px;margin-top:32px;'>
        <div style='font-size:20px;font-weight:600;color:#ffffff;margin-bottom:10px;'>No positions yet</div>
        <div style='color:#888888;font-size:14px;'>Use the Buy mode in the sidebar to add your first position.</div>
    </div>""", unsafe_allow_html=True)
    st.stop()


# ─── DATA ─────────────────────────────────────────────────────────
tickers = tuple(h["Ticker"] for h in st.session_state.holdings)
prices  = get_prices(tickers)
hist    = get_history(tickers + ("SPY",), START_DATE)


# ─── CALCULATIONS ─────────────────────────────────────────────────
rows = []
for h in st.session_state.holdings:
    ticker        = h["Ticker"]
    current_price = prices.get(ticker)
    if not current_price:
        continue
    current_value = current_price * h["Shares"]
    cost          = h["Cost Basis"] * h["Shares"]
    gain          = current_value - cost
    pct           = (gain / cost) * 100
    rows.append({
        "Ticker":          ticker,
        "Shares":          h["Shares"],
        "Cost Basis":      h["Cost Basis"],
        "Purchase Date":   h.get("Purchase Date", ""),
        "Current Price":   round(current_price, 2),
        "Current Value":   round(current_value, 2),
        "Gain/Loss ($)":   round(gain, 2),
        "Gain/Loss (%)":   round(pct, 2),
    })

df       = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Ticker","Shares","Cost Basis","Purchase Date","Current Price","Current Value","Gain/Loss ($)","Gain/Loss (%)"])
df.index = df.index + 1

total_value      = df["Current Value"].sum() if not df.empty else 0.0
total_cost       = sum(h["Cost Basis"] * h["Shares"] for h in st.session_state.holdings) if st.session_state.holdings else 0.0
total_gain       = total_value - total_cost
total_pct        = (total_gain / total_cost * 100) if total_cost > 0 else 0.0
portfolio_return = ((total_value - INITIAL_INVESTMENT) / INITIAL_INVESTMENT * 100) if INITIAL_INVESTMENT > 0 else 0.0

spy_hist    = hist["SPY"].dropna()
spy_start   = float(spy_hist.iloc[0])
spy_current = float(spy_hist.iloc[-1])
spy_return  = ((spy_current - spy_start) / spy_start) * 100
vs_spy      = portfolio_return - spy_return

portfolio_hist = pd.Series(0.0, index=hist.index)
for h in st.session_state.holdings:
    ticker = h["Ticker"]
    if ticker in hist.columns:
        first_price     = hist[ticker].dropna().iloc[0]
        portfolio_hist += (hist[ticker] / first_price) * (h["Cost Basis"] * h["Shares"])

portfolio_hist = portfolio_hist[portfolio_hist > 0]
portfolio_norm = ((portfolio_hist - portfolio_hist.iloc[0]) / portfolio_hist.iloc[0]) * 100
spy_norm       = ((spy_hist - spy_start) / spy_start) * 100

daily_returns     = portfolio_hist.pct_change().dropna()
spy_daily         = spy_hist.pct_change().dropna()
annualized_return = ((1 + daily_returns.mean()) ** 252 - 1) * 100
annualized_vol    = daily_returns.std() * (252 ** 0.5) * 100
risk_free         = 0.045
sharpe            = (annualized_return / 100 - risk_free) / (annualized_vol / 100)
rolling_max       = portfolio_hist.cummax()
drawdown          = (portfolio_hist - rolling_max) / rolling_max * 100
max_drawdown      = drawdown.min()


# ─── PDF GENERATION ───────────────────────────────────────────────
if generate_pdf:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 12, "Portfolio Dashboard", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 6, f"Generated {pd.Timestamp.now().strftime('%B %d, %Y at %I:%M %p')}", ln=True)
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 6, "PORTFOLIO SUMMARY", ln=True)
    pdf.set_draw_color(220, 220, 220)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(4)

    metrics = [
        ("Total Value",           f"${total_value:,.2f}"),
        ("Total Gain / Loss",     f"${total_gain:,.2f}"),
        ("Portfolio Return",      f"{portfolio_return:.2f}%"),
        ("SPY Return",            f"{spy_return:.2f}%"),
        ("vs SPY",                f"{vs_spy:+.2f}%"),
        ("Sharpe Ratio",          f"{sharpe:.2f}"),
        ("Max Drawdown",          f"{max_drawdown:.2f}%"),
        ("Annualized Volatility", f"{annualized_vol:.2f}%"),
    ]
    for label, value in metrics:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(130, 130, 130)
        pdf.cell(80, 7, label)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 7, value, ln=True)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 6, "HOLDINGS", ln=True)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(4)

    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(100, 100, 100)
    col_widths = [20, 18, 24, 24, 22, 24, 22, 22]
    headers    = ["Ticker", "Shares", "Cost Basis", "Pur. Date", "Cur. Price", "Cur. Value", "G/L ($)", "G/L (%)"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, h, border=0, fill=True)
    pdf.ln()

    for _, row in df.reset_index().iterrows():
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_widths[0], 7, str(row["Ticker"]))
        pdf.cell(col_widths[1], 7, str(row["Shares"]))
        pdf.cell(col_widths[2], 7, f"${row['Cost Basis']:.2f}")
        pdf.cell(col_widths[3], 7, str(row.get("Purchase Date", "")))
        pdf.cell(col_widths[4], 7, f"${row['Current Price']:.2f}")
        pdf.cell(col_widths[5], 7, f"${row['Current Value']:,.2f}")
        gl_dollar = row["Gain/Loss ($)"]
        gl_pct    = row["Gain/Loss (%)"]
        pdf.set_text_color(0, 150, 80) if gl_dollar >= 0 else pdf.set_text_color(200, 0, 0)
        pdf.cell(col_widths[6], 7, f"${gl_dollar:,.2f}")
        pdf.cell(col_widths[7], 7, f"{gl_pct:.2f}%")
        pdf.ln()

    if st.session_state.realized_gains:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(130, 130, 130)
        pdf.cell(0, 6, "REALIZED GAINS THIS SESSION", ln=True)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(4)
        for g in st.session_state.realized_gains:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(30, 7, g["Date"])
            pdf.cell(20, 7, g["Ticker"])
            pdf.cell(40, 7, f"{g['Shares Sold']:.3f} shares sold")
            pdf.cell(40, 7, f"@ ${g['Sale Price']:.2f}")
            g_color = (0, 150, 80) if g["Realized Gain"] >= 0 else (200, 0, 0)
            pdf.set_text_color(*g_color)
            pdf.cell(0, 7, f"${g['Realized Gain']:,.2f}", ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(170, 170, 170)
    pdf.cell(0, 6, f"Portfolio Dashboard · Generated {pd.Timestamp.now().strftime('%B %d, %Y')}", ln=True)
    pdf.cell(0, 6, "This report is for informational purposes only and does not constitute financial advice.", ln=True)

    pdf_bytes = pdf.output()
    st.sidebar.download_button(
        label="Download PDF",
        data=bytes(pdf_bytes),
        file_name=f"portfolio_report_{pd.Timestamp.now().strftime('%Y_%m_%d')}.pdf",
        mime="application/pdf"
    )


# ─── METRICS ──────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
gain_color = "green" if total_gain >= 0 else "red"
vs_color   = "green" if vs_spy >= 0 else "red"
arrow      = "↑" if vs_spy >= 0 else "↓"

with c1:
    st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>Total Value</div>
        <div class='metric-value green'>${total_value:,.2f}</div>
    </div>""", unsafe_allow_html=True)

with c2:
    st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>Total Gain / Loss</div>
        <div class='metric-value {gain_color}'>${total_gain:,.2f}</div>
        <div class='metric-delta delta-{gain_color}'>{total_pct:.2f}%</div>
    </div>""", unsafe_allow_html=True)

with c3:
    st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>Portfolio Return</div>
        <div class='metric-value {gain_color}'>${total_value - INITIAL_INVESTMENT:,.2f}</div>
        <div class='metric-delta delta-{gain_color}'>{portfolio_return:.2f}%</div>
    </div>""", unsafe_allow_html=True)

with c4:
    st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>SPY Return</div>
        <div class='metric-value'>{spy_return:.2f}%</div>
    </div>""", unsafe_allow_html=True)

with c5:
    st.markdown(f"""<div class='metric-card'>
        <div class='metric-label'>vs SPY</div>
        <div class='metric-value {vs_color}'>{vs_spy:+.2f}%</div>
        <div class='metric-delta delta-{vs_color}'>{arrow} Relative Return</div>
    </div>""", unsafe_allow_html=True)

st.divider()


# ─── TABS ─────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Overview", "vs S&P 500", "Dollar Performance", "News", "Statistics", "Monte Carlo", "Efficient Frontier", "Transaction History"
])


# ── TAB 1: OVERVIEW ───────────────────────────────────────────────
with tab1:
    st.markdown("<div class='section-header'>Allocation & Performance</div>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)

    with col1:
        fig = px.pie(df, values="Current Value", names="Ticker",
                     color_discrete_sequence=["#4a9eff","#00ff88","#ff4d4d","#ffd700","#a855f7","#fb923c"])
        fig.update_traces(textfont_color="white", hole=0.4)
        fig.update_layout(**PLOT_LAYOUT, title=dict(text="Allocation", font=dict(color="#ffffff", size=13)))
        st.plotly_chart(fig, width="stretch")

    with col2:
        colors = ["#00ff88" if x > 0 else "#ff4d4d" for x in df["Gain/Loss ($)"]]
        fig    = go.Figure(go.Bar(x=df["Ticker"], y=df["Gain/Loss ($)"],
                                  marker_color=colors, marker_line_width=0))
        fig.update_layout(**PLOT_LAYOUT, title=dict(text="Gain / Loss by Position",
                          font=dict(color="#ffffff", size=13)))
        st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-header'>Holdings</div>", unsafe_allow_html=True)
    st.dataframe(df, width="stretch")


# ── TAB 2: VS S&P 500 ─────────────────────────────────────────────
with tab2:
    st.markdown("<div class='section-header'>Portfolio vs S&P 500</div>", unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Your Return</div>
            <div class='metric-value green'>{portfolio_return:.2f}%</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>SPY Return</div>
            <div class='metric-value'>{spy_return:.2f}%</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Difference</div>
            <div class='metric-value {vs_color}'>{vs_spy:+.2f}%</div>
            <div class='metric-delta delta-{vs_color}'>{arrow} vs benchmark</div>
        </div>""", unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=portfolio_norm.index, y=portfolio_norm.values,
                             name="Your Portfolio", line=dict(color="#00ff88", width=2)))
    fig.add_trace(go.Scatter(x=spy_norm.index, y=spy_norm.values,
                             name="SPY", line=dict(color="#4a9eff", width=2)))
    diff = portfolio_norm - spy_norm.reindex(portfolio_norm.index, method="ffill")
    fig.add_trace(go.Scatter(x=diff.index, y=diff.values, name="Difference",
                             line=dict(color="#ffd700", width=1, dash="dot")))
    fig.update_layout(**PLOT_LAYOUT, yaxis_title="Return (%)", xaxis_title="Date",
                      title=dict(text="Return Comparison", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")


# ── TAB 3: DOLLAR PERFORMANCE ─────────────────────────────────────
with tab3:
    st.markdown("<div class='section-header'>Dollar Performance</div>", unsafe_allow_html=True)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Current Value</div>
            <div class='metric-value green'>${total_value:,.2f}</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Total Gain</div>
            <div class='metric-value {gain_color}'>${total_gain:,.2f}</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Initial Investment</div>
            <div class='metric-value'>${INITIAL_INVESTMENT:,.2f}</div>
        </div>""", unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=portfolio_hist.index, y=portfolio_hist.values,
                             name="Portfolio Value", line=dict(color="#00ff88", width=2),
                             fill="tozeroy", fillcolor="rgba(0,255,136,0.05)"))
    fig.add_hline(y=INITIAL_INVESTMENT, line_dash="dash", line_color="#888888",
                  annotation_text=f"Initial ${INITIAL_INVESTMENT:,.0f}",
                  annotation_font_color="#888888", annotation_position="bottom right")
    y_min = portfolio_hist.min() * 0.98
    y_max = portfolio_hist.max() * 1.02
    fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k != "yaxis"},
                      yaxis=dict(range=[y_min, y_max], gridcolor="#2a2a2a"),
                      yaxis_title="Value ($)", xaxis_title="Date",
                      title=dict(text="Portfolio Value Over Time", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-header'>Individual Position Return Over Time</div>", unsafe_allow_html=True)
    fig         = go.Figure()
    colors_list = ["#00ff88","#4a9eff","#ff4d4d","#ffd700","#a855f7","#fb923c"]
    for i, h in enumerate(st.session_state.holdings):
        ticker = h["Ticker"]
        if ticker in hist.columns:
            pos_hist = hist[ticker].dropna()
            pos_norm = ((pos_hist - pos_hist.iloc[0]) / pos_hist.iloc[0]) * 100
            fig.add_trace(go.Scatter(x=pos_norm.index, y=pos_norm.values,
                                     name=ticker, line=dict(color=colors_list[i % len(colors_list)], width=2)))
    fig.update_layout(**PLOT_LAYOUT, yaxis_title="Return (%)", xaxis_title="Date",
                      title=dict(text="Position Returns Over Time", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")


# ── TAB 4: NEWS ───────────────────────────────────────────────────
with tab4:
    st.markdown("<div class='section-header'>Market News</div>", unsafe_allow_html=True)
    articles = get_news(tickers)

    if not articles:
        st.markdown("<div class='metric-card'><div style='color:#888888;'>No news available. You may have hit the free tier limit of 100 requests/day.</div></div>", unsafe_allow_html=True)
    else:
        for ticker in tickers:
            ticker_articles = [a for a in articles if a["ticker"] == ticker]
            if not ticker_articles:
                continue
            st.markdown(f"<div class='section-header'>{ticker}</div>", unsafe_allow_html=True)
            for a in ticker_articles:
                st.markdown(f"""
                <div class='metric-card' style='margin-bottom:12px;'>
                    <div class='metric-label'>{a['source']} &nbsp;·&nbsp; {a['published']}</div>
                    <a href='{a['url']}' target='_blank' style='color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;'>
                        {a['title']}
                    </a>
                    <div style='color:#888888;font-size:13px;margin-top:8px;'>{a['description'] or ''}</div>
                </div>""", unsafe_allow_html=True)


# ── TAB 5: STATISTICS ─────────────────────────────────────────────
with tab5:
    st.markdown("<div class='section-header'>Portfolio Statistics</div>", unsafe_allow_html=True)

    spy_annualized_vol    = spy_daily.std() * (252 ** 0.5) * 100
    spy_annualized_return = ((1 + spy_daily.mean()) ** 252 - 1) * 100
    spy_sharpe            = (spy_annualized_return / 100 - risk_free) / (spy_annualized_vol / 100)

    best_day       = daily_returns.max() * 100
    worst_day      = daily_returns.min() * 100
    best_day_date  = daily_returns.idxmax().strftime("%b %d %Y")
    worst_day_date = daily_returns.idxmin().strftime("%b %d %Y")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        color = "green" if sharpe > 1 else "red"
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Sharpe Ratio</div>
            <div class='metric-value {color}'>{sharpe:.2f}</div>
            <div class='metric-delta' style='color:#888888;'>SPY: {spy_sharpe:.2f}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Annualized Volatility</div>
            <div class='metric-value'>{annualized_vol:.2f}%</div>
            <div class='metric-delta' style='color:#888888;'>SPY: {spy_annualized_vol:.2f}%</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Max Drawdown</div>
            <div class='metric-value red'>{max_drawdown:.2f}%</div>
            <div class='metric-delta' style='color:#888888;'>Peak to trough</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Annualized Return</div>
            <div class='metric-value green'>{annualized_return:.2f}%</div>
            <div class='metric-delta' style='color:#888888;'>SPY: {spy_annualized_return:.2f}%</div>
        </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Best Day</div>
            <div class='metric-value green'>+{best_day:.2f}%</div>
            <div class='metric-delta' style='color:#888888;'>{best_day_date}</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Worst Day</div>
            <div class='metric-value red'>{worst_day:.2f}%</div>
            <div class='metric-delta' style='color:#888888;'>{worst_day_date}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div class='section-header'>Drawdown Over Time</div>", unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown.values,
                             name="Drawdown", line=dict(color="#ff4d4d", width=2),
                             fill="tozeroy", fillcolor="rgba(255,77,77,0.1)"))
    fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k != "yaxis"},
                      yaxis=dict(gridcolor="#2a2a2a", ticksuffix="%"),
                      yaxis_title="Drawdown (%)", xaxis_title="Date",
                      title=dict(text="Portfolio Drawdown", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-header'>Correlation Heatmap</div>", unsafe_allow_html=True)
    holding_tickers = [h["Ticker"] for h in st.session_state.holdings]
    corr_df         = hist[holding_tickers].pct_change().dropna().corr().round(2)
    fig = go.Figure(go.Heatmap(
        z=corr_df.values,
        x=corr_df.columns.tolist(),
        y=corr_df.index.tolist(),
        colorscale=[[0, "#ff4d4d"], [0.5, "#222222"], [1, "#00ff88"]],
        zmin=-1, zmax=1,
        text=corr_df.values,
        texttemplate="%{text}",
        textfont=dict(color="#ffffff", size=12),
    ))
    fig.update_layout(**PLOT_LAYOUT,
                      title=dict(text="Holdings Correlation Matrix", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-header'>Rolling 30-Day Volatility</div>", unsafe_allow_html=True)
    rolling_vol     = daily_returns.rolling(30).std() * (252 ** 0.5) * 100
    spy_rolling_vol = spy_daily.rolling(30).std() * (252 ** 0.5) * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=rolling_vol.index, y=rolling_vol.values,
                             name="Your Portfolio", line=dict(color="#00ff88", width=2)))
    fig.add_trace(go.Scatter(x=spy_rolling_vol.index, y=spy_rolling_vol.values,
                             name="SPY", line=dict(color="#4a9eff", width=2)))
    fig.update_layout(**PLOT_LAYOUT, yaxis_title="Volatility (%)", xaxis_title="Date",
                      title=dict(text="Rolling 30-Day Annualized Volatility", font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")


# ── TAB 6: MONTE CARLO ────────────────────────────────────────────
with tab6:
    st.markdown("<div class='section-header'>Monte Carlo Simulation</div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        years = st.selectbox("Projection Period", [1, 3, 5, 10], index=2)
    with c2:
        simulations = st.selectbox("Number of Simulations", [500, 1000, 2000], index=1)
    with c3:
        monthly_contribution = st.number_input("Monthly Contribution ($)", min_value=0.0, step=50.0, value=0.0, format="%.2f")

    trading_days   = years * 252
    mean_return    = daily_returns.mean()
    std_return     = daily_returns.std()
    starting_value = total_value

    np.random.seed(42)
    all_paths = np.zeros((trading_days, simulations))
    for i in range(simulations):
        daily = np.random.normal(mean_return, std_return, trading_days)
        path  = [starting_value]
        for j, r in enumerate(daily):
            new_val = path[-1] * (1 + r)
            if monthly_contribution > 0 and j % 21 == 0:
                new_val += monthly_contribution
            path.append(new_val)
        all_paths[:, i] = path[1:]

    p10          = np.percentile(all_paths, 10, axis=1)
    p50          = np.percentile(all_paths, 50, axis=1)
    p90          = np.percentile(all_paths, 90, axis=1)
    final_values = all_paths[-1, :]
    worst        = np.percentile(final_values, 5)
    median       = np.percentile(final_values, 50)
    best         = np.percentile(final_values, 95)
    prob_profit  = (final_values > starting_value).mean() * 100

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Worst Case (5th %ile)</div>
            <div class='metric-value red'>${worst:,.0f}</div>
            <div class='metric-delta' style='color:#888888;'>{((worst-starting_value)/starting_value*100):+.1f}%</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Median Case (50th %ile)</div>
            <div class='metric-value'>${median:,.0f}</div>
            <div class='metric-delta' style='color:#888888;'>{((median-starting_value)/starting_value*100):+.1f}%</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Best Case (95th %ile)</div>
            <div class='metric-value green'>${best:,.0f}</div>
            <div class='metric-delta' style='color:#888888;'>{((best-starting_value)/starting_value*100):+.1f}%</div>
        </div>""", unsafe_allow_html=True)
    with m4:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-label'>Prob. of Profit</div>
            <div class='metric-value green'>{prob_profit:.1f}%</div>
            <div class='metric-delta' style='color:#888888;'>vs starting value</div>
        </div>""", unsafe_allow_html=True)

    trading_dates = pd.date_range(start=pd.Timestamp.today(), periods=trading_days, freq='B')
    fig = go.Figure()
    for i in range(0, simulations, simulations // 200):
        fig.add_trace(go.Scatter(x=trading_dates, y=all_paths[:, i], mode='lines',
                                 line=dict(color='rgba(0,255,136,0.03)', width=1),
                                 showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=trading_dates, y=p90, name="90th Percentile",
                             line=dict(color="#00ff88", width=2)))
    fig.add_trace(go.Scatter(x=trading_dates, y=p50, name="Median",
                             line=dict(color="#ffffff", width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=trading_dates, y=p10, name="10th Percentile",
                             line=dict(color="#ff4d4d", width=2)))
    fig.add_hline(y=starting_value, line_dash="dot", line_color="#888888",
                  annotation_text=f"Current: ${starting_value:,.0f}",
                  annotation_font_color="#888888", annotation_position="bottom right")
    fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k != "yaxis"},
                      yaxis=dict(gridcolor="#2a2a2a", tickprefix="$"),
                      yaxis_title="Portfolio Value ($)", xaxis_title="Date",
                      title=dict(text=f"Monte Carlo Simulation — {simulations} Paths over {years} Years",
                                 font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-header'>Final Value Distribution</div>", unsafe_allow_html=True)
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=final_values, nbinsx=80, marker_color="#00ff88", opacity=0.7, name="Final Values"))
    fig.add_vline(x=worst,          line_dash="dash", line_color="#ff4d4d", annotation_text="5th %ile",  annotation_font_color="#ff4d4d")
    fig.add_vline(x=median,         line_dash="dash", line_color="#ffffff", annotation_text="Median",    annotation_font_color="#ffffff")
    fig.add_vline(x=best,           line_dash="dash", line_color="#00ff88", annotation_text="95th %ile", annotation_font_color="#00ff88")
    fig.add_vline(x=starting_value, line_dash="dot",  line_color="#888888", annotation_text="Current",   annotation_font_color="#888888")
    fig.update_layout(**PLOT_LAYOUT, xaxis_title="Final Portfolio Value ($)", yaxis_title="Number of Simulations",
                      title=dict(text=f"Distribution of Final Portfolio Values after {years} Years",
                                 font=dict(color="#ffffff", size=13)))
    st.plotly_chart(fig, width="stretch")

    st.markdown(f"""<div class='metric-card' style='margin-top:16px;'>
        <div class='metric-label'>Methodology</div>
        <div style='color:#888888;font-size:13px;line-height:1.6;'>
            This simulation uses <strong style='color:#ffffff;'>{simulations:,} randomized paths</strong> based on your portfolio's
            historical daily mean return of <strong style='color:#ffffff;'>{mean_return*100:.4f}%</strong> and
            daily volatility of <strong style='color:#ffffff;'>{std_return*100:.4f}%</strong>.
            Each path simulates <strong style='color:#ffffff;'>{trading_days:,} trading days</strong> using geometric Brownian motion.
            Past performance does not guarantee future results.
        </div>
    </div>""", unsafe_allow_html=True)


# ── TAB 7: EFFICIENT FRONTIER ─────────────────────────────────────
with tab7:
    st.markdown("<div class='section-header'>Efficient Frontier</div>", unsafe_allow_html=True)

    if len(st.session_state.holdings) < 2:
        st.markdown("<div class='metric-card'><div style='color:#888888;'>Add at least 2 positions to view the Efficient Frontier.</div></div>", unsafe_allow_html=True)
    else:
        holding_tickers = [h["Ticker"] for h in st.session_state.holdings]
        returns_df      = hist[holding_tickers].pct_change().dropna()
        mean_returns    = returns_df.mean() * 252
        cov_matrix      = returns_df.cov() * 252
        n_assets        = len(holding_tickers)

        def portfolio_performance(weights):
            ret    = np.dot(weights, mean_returns)
            vol    = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            sharpe = (ret - risk_free) / vol
            return ret, vol, sharpe

        def neg_sharpe(weights):
            return -portfolio_performance(weights)[2]

        def portfolio_vol(weights, target_return):
            return portfolio_performance(weights)[1]

        constraints  = [{"type": "eq", "fun": lambda x: np.sum(x) - 1}]
        bounds       = tuple((0, 1) for _ in range(n_assets))
        init_weights = np.array([1/n_assets] * n_assets)

        max_sharpe_result         = minimize(neg_sharpe, init_weights, method="SLSQP", bounds=bounds, constraints=constraints)
        ms_ret, ms_vol, ms_sharpe = portfolio_performance(max_sharpe_result.x)
        ms_weights                = max_sharpe_result.x

        target_returns           = np.linspace(mean_returns.min(), mean_returns.max(), 100)
        frontier_vols, frontier_rets = [], []
        for target in target_returns:
            cons   = constraints + [{"type": "eq", "fun": lambda x, t=target: portfolio_performance(x)[0] - t}]
            result = minimize(portfolio_vol, init_weights, args=(target,), method="SLSQP", bounds=bounds, constraints=cons)
            if result.success:
                frontier_vols.append(portfolio_performance(result.x)[1])
                frontier_rets.append(target)

        n_random                           = 3000
        rand_vols, rand_rets, rand_sharpes = [], [], []
        for _ in range(n_random):
            w = np.random.dirichlet(np.ones(n_assets))
            r, v, s = portfolio_performance(w)
            rand_vols.append(v)
            rand_rets.append(r)
            rand_sharpes.append(s)

        total_val    = sum(prices.get(h["Ticker"], 0) * h["Shares"] for h in st.session_state.holdings)
        curr_weights = np.array([(prices.get(h["Ticker"], 0) * h["Shares"]) / total_val for h in st.session_state.holdings])
        curr_ret, curr_vol, curr_sharpe = portfolio_performance(curr_weights)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Your Sharpe Ratio</div>
                <div class='metric-value {"green" if curr_sharpe > 1 else "red"}'>{curr_sharpe:.2f}</div>
                <div class='metric-delta' style='color:#888888;'>Current allocation</div>
            </div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Max Sharpe Ratio</div>
                <div class='metric-value green'>{ms_sharpe:.2f}</div>
                <div class='metric-delta' style='color:#888888;'>Optimal allocation</div>
            </div>""", unsafe_allow_html=True)
        with m3:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Your Volatility</div>
                <div class='metric-value'>{curr_vol*100:.2f}%</div>
                <div class='metric-delta' style='color:#888888;'>Annualized</div>
            </div>""", unsafe_allow_html=True)
        with m4:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Optimal Volatility</div>
                <div class='metric-value'>{ms_vol*100:.2f}%</div>
                <div class='metric-delta' style='color:#888888;'>At max Sharpe</div>
            </div>""", unsafe_allow_html=True)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=rand_vols, y=rand_rets, mode="markers",
            marker=dict(color=rand_sharpes, colorscale=[[0,"#ff4d4d"],[0.5,"#ffd700"],[1,"#00ff88"]],
                        size=3, opacity=0.4, showscale=True,
                        colorbar=dict(title="Sharpe", thickness=12, len=0.5,
                                      tickfont=dict(color="#888888"), title_font=dict(color="#888888"))),
            name="Random Portfolios", hovertemplate="Vol: %{x:.1%}<br>Return: %{y:.1%}<extra></extra>"
        ))
        if frontier_vols:
            fig.add_trace(go.Scatter(x=frontier_vols, y=frontier_rets, mode="lines",
                                     line=dict(color="#ffffff", width=2), name="Efficient Frontier"))
        fig.add_trace(go.Scatter(x=[ms_vol], y=[ms_ret], mode="markers",
                                 marker=dict(color="#ffd700", size=14, symbol="star"),
                                 name=f"Max Sharpe ({ms_sharpe:.2f})",
                                 hovertemplate=f"Max Sharpe<br>Vol: {ms_vol:.1%}<br>Return: {ms_ret:.1%}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[curr_vol], y=[curr_ret], mode="markers",
                                 marker=dict(color="#4a9eff", size=14, symbol="diamond"),
                                 name=f"Your Portfolio ({curr_sharpe:.2f})",
                                 hovertemplate=f"Your Portfolio<br>Vol: {curr_vol:.1%}<br>Return: {curr_ret:.1%}<extra></extra>"))
        fig.update_layout(**{k: v for k, v in PLOT_LAYOUT.items() if k not in ("xaxis", "yaxis")},
                          xaxis=dict(gridcolor="#2a2a2a", tickformat=".0%", title="Annualized Volatility"),
                          yaxis=dict(gridcolor="#2a2a2a", tickformat=".0%", title="Annualized Return"),
                          title=dict(text="Efficient Frontier — Risk vs Return", font=dict(color="#ffffff", size=13)))
        st.plotly_chart(fig, width="stretch")

        st.markdown("<div class='section-header'>Optimal Portfolio Weights vs Current</div>", unsafe_allow_html=True)
        weights_df = pd.DataFrame({
            "Ticker":         holding_tickers,
            "Current Weight": [f"{w*100:.1f}%" for w in curr_weights],
            "Optimal Weight": [f"{w*100:.1f}%" for w in ms_weights],
            "Difference":     [f"{(ms_weights[i] - curr_weights[i])*100:+.1f}%" for i in range(n_assets)]
        })
        weights_df.index = weights_df.index + 1

        fig = go.Figure()
        fig.add_trace(go.Bar(x=holding_tickers, y=curr_weights*100, name="Current",
                             marker_color="#4a9eff", marker_line_width=0))
        fig.add_trace(go.Bar(x=holding_tickers, y=ms_weights*100, name="Optimal (Max Sharpe)",
                             marker_color="#ffd700", marker_line_width=0))
        fig.update_layout(**PLOT_LAYOUT, barmode="group", yaxis_title="Weight (%)", xaxis_title="",
                          title=dict(text="Current vs Optimal Weights", font=dict(color="#ffffff", size=13)))
        st.plotly_chart(fig, width="stretch")

        st.dataframe(weights_df, width="stretch")

        st.markdown(f"""<div class='metric-card' style='margin-top:16px;'>
            <div class='metric-label'>Methodology</div>
            <div style='color:#888888;font-size:13px;line-height:1.6;'>
                The Efficient Frontier represents all portfolios that maximize return for a given level of risk using
                <strong style='color:#ffffff;'>Markowitz Mean-Variance Optimization</strong>. The
                <strong style='color:#ffffff;'>star</strong> marks the Maximum Sharpe Ratio portfolio.
                The <strong style='color:#ffffff;'>diamond</strong> marks your current allocation.
            </div>
        </div>""", unsafe_allow_html=True)


# ── TAB 8: TRANSACTION HISTORY ────────────────────────────────────
with tab8:
    st.markdown("<div class='section-header'>Transaction History</div>", unsafe_allow_html=True)

    transactions = load_transactions()

    if not transactions:
        st.markdown("<div class='metric-card'><div style='color:#888888;'>No transactions recorded yet.</div></div>", unsafe_allow_html=True)
    else:
        buys  = [t for t in transactions if t["transaction_type"] == "buy"]
        sells = [t for t in transactions if t["transaction_type"] == "sell"]

        total_invested        = sum(t["shares"] * t["price"] for t in buys)
        total_realized        = sum(t["realized_gain"] for t in sells if t.get("realized_gain"))
        total_sell_gain_color = "green" if total_realized >= 0 else "red"

        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Total Transactions</div>
                <div class='metric-value'>{len(transactions)}</div>
            </div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Total Invested</div>
                <div class='metric-value green'>${total_invested:,.2f}</div>
            </div>""", unsafe_allow_html=True)
        with m3:
            st.markdown(f"""<div class='metric-card'>
                <div class='metric-label'>Total Realized Gains</div>
                <div class='metric-value {total_sell_gain_color}'>${total_realized:,.2f}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div class='section-header'>All Transactions</div>", unsafe_allow_html=True)

        tx_rows = []
        for t in transactions:
            realized = f"${t['realized_gain']:,.2f}" if t.get("realized_gain") is not None else "-"
            tx_rows.append({
                "Date":          (t.get("transaction_date_input") or t.get("transaction_date", ""))[:10],
                "Type":          t["transaction_type"].upper(),
                "Ticker":        t["ticker"],
                "Shares":        round(t["shares"], 4),
                "Price":         f"${t['price']:,.2f}",
                "Total":         f"${t['shares'] * t['price']:,.2f}",
                "Realized Gain": realized,
            })

        tx_df       = pd.DataFrame(tx_rows)
        tx_df.index = tx_df.index + 1
        st.dataframe(tx_df, width="stretch")

        if sells:
            st.markdown("<div class='section-header'>Realized Gains Over Time</div>", unsafe_allow_html=True)
            sell_labels = [f"{t['ticker']} {(t.get('transaction_date_input') or t.get('transaction_date', ''))[:10]}" for t in sells if t.get("realized_gain") is not None]
            sell_gains  = [t["realized_gain"] for t in sells if t.get("realized_gain") is not None]
            sell_colors = ["#00ff88" if g >= 0 else "#ff4d4d" for g in sell_gains]

            fig = go.Figure(go.Bar(x=sell_labels, y=sell_gains, marker_color=sell_colors, marker_line_width=0))
            fig.update_layout(**PLOT_LAYOUT, yaxis_title="Realized Gain ($)", xaxis_title="",
                              title=dict(text="Realized Gains by Transaction", font=dict(color="#ffffff", size=13)))
            st.plotly_chart(fig, width="stretch")

