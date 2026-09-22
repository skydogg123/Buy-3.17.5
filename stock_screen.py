#!/usr/bin/env python3
"""
Daily RSI + MACD stock screen — optimized for paid Alpha Vantage tier.
MACD tuned to 3, 17, 5 for faster crossovers.

Runs entirely on GitHub Actions' cloud infrastructure -- no dependency on any
local computer being on. Reads tickers from watchlist.txt in this repo,
pulls daily prices from Alpha Vantage, computes RSI (Wilder) and MACD in
code, evaluates the screen conditions, and emails the results.

OPTIMIZATION (paid tier $50/month):
- Uses "full" historical data (20+ years) instead of "compact" (100 days)
- Minimal call spacing (0.1s) — paid tier can handle 2000+ calls/minute
- Can scan 180+ tickers in under 1 minute

MODIFICATION:
- MACD now uses fast=3, slow=17, signal=5 (instead of 12, 26, 9)
  for faster, more responsive crossovers.

Required environment variables (set as GitHub Secrets):
  ALPHAVANTAGE_API_KEY   - your Alpha Vantage API key
  SENDER_EMAIL            - Gmail address the report is sent FROM
  SENDER_APP_PASSWORD     - Gmail "app password" for that address
                             (Google Account -> Security -> App passwords)
Optional:
  RECIPIENT_EMAIL         - where the report is sent TO (defaults to
                             bump52@hotmail.com if not set)
"""

import csv
import io
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests

WATCHLIST_FILE = "watchlist.txt"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
RSI_PERIOD = 14
RSI_OVERSOLD_THRESHOLD = 38
RSI_LOOKBACK_DAYS = 5
CALL_SPACING_SECONDS = 0.1  # paid tier: 2000+ calls/min, so minimal spacing

# MACD parameters — tuned for faster response
MACD_FAST = 3
MACD_SLOW = 17
MACD_SIGNAL = 5


# ---------------------------------------------------------------------------
# Indicator math (Wilder RSI + standard EMA-based MACD).
# Validated to match a reference implementation to machine precision --
# do not modify without re-validating.
# ---------------------------------------------------------------------------

def wilder_rsi(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return []
    gain = loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    avg_g, avg_l = gain / period, loss / period

    def rsi_from(g, l):
        return 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)

    out = [rsi_from(avg_g, avg_l)]
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        out.append(rsi_from(avg_g, avg_l))
    return out


def ema(vals, n):
    if len(vals) < n:
        return []
    k = 2.0 / (n + 1)
    prev = sum(vals[:n]) / n
    out = [prev]
    for v in vals[n:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def macd_calc(closes, fast=MACD_FAST, slow=MACD_SLOW, sig=MACD_SIGNAL):
    e_f, e_s = ema(closes, fast), ema(closes, slow)
    if not e_f or not e_s:
        return [], []
    off = len(e_f) - len(e_s)
    macd = [e_f[i + off] - v for i, v in enumerate(e_s)]
    signal = ema(macd, sig)
    if not signal:
        return [], []
    return macd[len(macd) - len(signal):], signal


# ---------------------------------------------------------------------------
# Data + screen
# ---------------------------------------------------------------------------

def load_watchlist(path):
    tickers = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tickers.append(line.upper())
    return tickers


def fetch_closes(ticker, api_key):
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker,
        "outputsize": "full",  # PAID TIER: use full 20+ years of data
        "datatype": "csv",
        "apikey": api_key,
    }
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    resp.raise_for_status()
    text = resp.text
    if not text.strip() or "Error Message" in text or "Note" in text[:50] or "Information" in text[:50]:
        return None, text[:200]

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows or "close" not in rows[0]:
        return None, "unexpected response format"

    # Alpha Vantage CSV is newest-first; we need oldest-first for the math.
    rows.reverse()
    try:
        closes = [float(r["close"]) for r in rows]
        dates = [r["timestamp"] for r in rows]
    except (KeyError, ValueError) as e:
        return None, f"parse error: {e}"
    return (dates, closes), None


def screen_ticker(ticker, api_key):
    result, err = fetch_closes(ticker, api_key)
    if err:
        return {"symbol": ticker, "error": err}

    dates, closes = result
    rsi = wilder_rsi(closes)
    macd, signal = macd_calc(closes)

    if len(rsi) < RSI_LOOKBACK_DAYS or len(macd) < 2 or len(signal) < 2:
        return {"symbol": ticker, "error": "not enough history"}

    rsi_last5 = rsi[-RSI_LOOKBACK_DAYS:]
    cond1 = min(rsi_last5) < RSI_OVERSOLD_THRESHOLD  # oversold within last 5 days
    cond2 = macd[-2] <= signal[-2] and macd[-1] > signal[-1]  # fresh bullish cross
    fired = cond1 and cond2

    return {
        "symbol": ticker,
        "date": dates[-1],
        "close": closes[-1],
        "rsi": rsi[-1],
        "rsi_5d_low": min(rsi_last5),
        "cond1": cond1,
        "cond2": cond2,
        "fired": fired,
    }


def build_report(results):
    fired = [r for r in results if not r.get("error") and r["fired"]]
    errors = [r for r in results if r.get("error")]
    ok = [r for r in results if not r.get("error")]

    lines = []
    lines.append(f"Stock screen run: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"(MACD: fast={MACD_FAST}, slow={MACD_SLOW}, signal={MACD_SIGNAL})")
    if fired:
        lines.append(f"\n{len(fired)} of {len(ok)} tickers FIRED today:\n")
        for r in fired:
            lines.append(
                f"  ** {r['symbol']:<8} close={r['close']:<10.2f} "
                f"RSI={r['rsi']:.1f}  5d-low-RSI={r['rsi_5d_low']:.1f}"
            )
    else:
        lines.append(f"\nNo tickers fired today (0 of {len(ok)}). This is the normal, common outcome.\n")

    lines.append("\nFull results:")
    lines.append(f"{'Symbol':<8}{'Close':<10}{'RSI':<8}{'5d Low RSI':<12}{'Cond1':<7}{'Cond2':<7}{'FIRED':<7}")
    for r in ok:
        lines.append(
            f"{r['symbol']:<8}{r['close']:<10.2f}{r['rsi']:<8.1f}{r['rsi_5d_low']:<12.1f}"
            f"{'Y' if r['cond1'] else 'n':<7}{'Y' if r['cond2'] else 'n':<7}{'Y' if r['fired'] else 'n':<7}"
        )

    if errors:
        lines.append("\nErrors (data unavailable, not counted as pass/fail):")
        for r in errors:
            lines.append(f"  {r['symbol']}: {r['error']}")

    subject = f"Stock screen {datetime.now(timezone.utc):%Y-%m-%d} — {len(fired)} fired (MACD 3/17/5)"
    return subject, "\n".join(lines)


def send_email(subject, body):
    sender = os.environ["SENDER_EMAIL"]
    app_password = os.environ["SENDER_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", "bump52@hotmail.com")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, app_password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        print("ALPHAVANTAGE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    tickers = load_watchlist(WATCHLIST_FILE)
    if not tickers:
        send_email("Stock screen — no watchlist found", "watchlist.txt was missing or empty.")
        return

    results = []
    for i, ticker in enumerate(tickers):
        results.append(screen_ticker(ticker, api_key))
        if i < len(tickers) - 1:
            time.sleep(CALL_SPACING_SECONDS)

    subject, body = build_report(results)
    send_email(subject, body)
    print(subject)
    print(body)


if __name__ == "__main__":
    main()
