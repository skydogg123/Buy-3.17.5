# Daily Stock Screener (GitHub Actions version)

Runs the RSI + MACD screen on GitHub's cloud servers on a daily schedule —
independent of your computer or the Claude Cowork app being open.

## Files

- `stock_screen.py` — the screen logic (same RSI/MACD math as the Cowork version)
- `watchlist.txt` — your ticker list; edit directly on GitHub any time to change it
- `requirements.txt` — the one Python dependency (`requests`)
- `.github/workflows/daily-screen.yml` — the schedule + job definition

## Setup (about 5 minutes)

1. **Create a new repository** on GitHub (public or private — private is fine,
   this is a low-traffic job).
2. **Add these four files**, keeping the folder structure intact — drag-and-drop
   upload on github.com works, or use `git push` if you're comfortable with it.
   The `.github/workflows/daily-screen.yml` path matters; GitHub only picks up
   workflows from that exact folder.
3. **Add secrets** — repo Settings → Secrets and variables → Actions → "New
   repository secret". Add:
   - `ALPHAVANTAGE_API_KEY` — your Alpha Vantage key
   - `SENDER_EMAIL` — the Gmail address you want the report sent *from*
   - `SENDER_APP_PASSWORD` — a Gmail "app password" for that address
     (Google Account → Security → 2-Step Verification must be on → App
     passwords → generate one for "Mail")
   - `RECIPIENT_EMAIL` *(optional)* — defaults to `bump52@hotmail.com` if
     you skip this
4. **Test it** — go to the "Actions" tab → "Daily stock screen" → "Run
   workflow" (this is the manual-trigger button, works any time, no waiting
   for the schedule).
5. Check your inbox (and spam folder, for the first run) for the report.

## Notes

- **Schedule**: currently set to 22:00 UTC = 5:00 PM Central *Daylight* Time.
  Central Time falls back to Standard Time (UTC-6) in winter, which would
  shift this to 4:00 PM local. GitHub Actions cron doesn't auto-adjust for
  DST — see the comment in the workflow file for how to handle that if it
  matters to you.
- **Runtime**: with ~183 tickers spaced 15 seconds apart, a full run takes
  roughly 45 minutes. If your upgraded Alpha Vantage plan allows faster
  calls, lower `CALL_SPACING_SECONDS` near the top of `stock_screen.py` to
  speed this up (and use less of your GitHub Actions minutes, if this repo
  is private — free personal accounts get 2,000 minutes/month for private
  repos; public repos are unlimited).
- **Delivery**: this sends a real email (not a Gmail draft, unlike the
  Cowork version) via SMTP.
- This is fully independent of Cowork's scheduler. Once you've confirmed a
  couple of successful runs, you can disable the `daily-stock-screen` task
  in Cowork, or leave it running in parallel as a backup.
