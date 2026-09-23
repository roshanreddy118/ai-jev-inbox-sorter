# Jev Inbox Sorter

A small web app that classifies your recent **unread Gmail** as SPAM / NOT_SPAM
using [Jev](https://api.typesafe.ai) (TypeSafe's System One decision model) and
optionally moves confident spam to your Spam folder.

- **Jev** makes the SPAM / NOT_SPAM decision (choice + confidence).
- **IMAP** (Python stdlib) reads the inbox and moves the mail.
- **Preview (dry-run) by default** — nothing moves until you turn on the move toggle.
- Your Gmail **app password is used only for the run and never stored or logged.**

## How it works

```
Browser form (gmail + app password + threshold)
      │  POST /api/sort
      ▼
Vercel Python function ──> IMAP: read recent unread
      │                    Jev:  classify all in ONE batched call
      ▼                    (move confident spam only if "live")
JSON results ──> rendered in the page
```

The Jev API key is **yours** and lives in a Vercel environment variable. The
user's Gmail credentials arrive in the request body, are used for that single
invocation, and are discarded when the stateless function returns.

## Project layout

| Path | Purpose |
|---|---|
| `index.html` | Responsive UI (mobile column / desktop two-column) |
| `api/sort.py` | Vercel serverless function: `POST /api/sort` |
| `gmail_jev_sorter.py` | Core: `sort_inbox()` + a CLI, and the Jev batch call |
| `jev_test.py` | Minimal Jev test; exposes `ask_jev()` |
| `dev_server.py` | Local preview server (not deployed) |
| `test_should_move.py` | Offline self-check of the move rule |
| `vercel.json` | Python runtime + 60s max function duration |

## Deploy to Vercel

1. Push this repo to GitHub (see below).
2. In Vercel: **Add New → Project → Import** this GitHub repo.
3. Framework preset: **Other** (the `api/*.py` file is auto-detected as a Python function).
4. Add an **Environment Variable**:
   - `JEV_API_KEY` = your Jev / TypeSafe key (`apikey_...`)
5. **Deploy.** Your app is at `https://<project>.vercel.app`.

> The 60s function limit (Hobby plan) means each run is capped at ~20 messages.

## Use it

Open the deployed URL (or run locally, below):

1. Enter your **Gmail address**.
2. Enter a **Gmail App Password** — not your normal password. Create one at
   <https://myaccount.google.com/apppasswords> (requires 2-Step Verification, and
   IMAP enabled in Gmail Settings → Forwarding and POP/IMAP).
3. Set the **sensitivity** (higher = only very confident spam moves) and how many
   recent unread to check.
4. **Preview** first. When the results look right, flip **Move spam** on and run again.

## Run locally

```bash
export JEV_API_KEY='apikey_...'
python3 dev_server.py            # open http://localhost:8000
```

CLI (no web UI):

```bash
export JEV_API_KEY='apikey_...'
export GMAIL_ADDRESS='you@gmail.com'
export GMAIL_APP_PASSWORD='xxxxxxxxxxxxxxxx'
python3 gmail_jev_sorter.py                # dry-run
python3 gmail_jev_sorter.py --live         # move confident spam
```

## Safety notes

- Preview/dry-run opens the mailbox **read-only** and uses `BODY.PEEK`, so it
  cannot change anything or even mark mail as read.
- Only messages Jev calls **SPAM at/above the threshold** are moved.
- A false positive buries a real email in Spam — start with a high threshold and a
  small message count, and eyeball the preview before going live.
- Never commit your `JEV_API_KEY` or app password. Keys go in Vercel env vars.
