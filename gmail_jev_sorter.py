"""Sort a Gmail inbox with Jev: classify unread mail as SPAM / NOT_SPAM and move
confident spam to [Gmail]/Spam.

Reuses ask_jev() from jev_test.py. Standard library only (imaplib, email).

SAFETY: dry-run by default. It touches nothing until you pass --live. Even then
it only moves messages Jev calls SPAM at/above --threshold confidence, skips
starred/flagged mail, and acts on at most --limit messages.

Setup (one time, on the Gmail side):
  1. Gmail Settings -> Forwarding and POP/IMAP -> Enable IMAP.
  2. Turn on 2-Step Verification, then create a 16-char App Password at
     https://myaccount.google.com/apppasswords . Use THAT, not your login password.

Run:
  export JEV_API_KEY='apikey_...'
  export GMAIL_ADDRESS='you@gmail.com'
  export GMAIL_APP_PASSWORD='xxxxxxxxxxxxxxxx'

  python3 gmail_jev_sorter.py                 # dry-run: classify + report, move nothing
  python3 gmail_jev_sorter.py --live          # actually move confident spam
  python3 gmail_jev_sorter.py --limit 5 --threshold 0.97
"""
import argparse
import email
import imaplib
import os
import sys
from email.header import decode_header, make_header

from jev_test import ask_jev  # reuse the verified Jev call

IMAP_HOST = "imap.gmail.com"

# The one spam question we ask Jev about each email.
SPAM_QUESTION = {
    "is_spam": {
        "type": "choice",
        "instructions": (
            "Judge this email. Is it unsolicited spam / scam / phishing / bulk "
            "marketing the recipient did not ask for, or a legitimate message?"
        ),
        "criteria": {
            "SPAM": "Unsolicited bulk mail, scams, phishing, prize/lottery fraud, "
                    "fake invoices, or marketing the recipient never opted into.",
            "NOT_SPAM": "A legitimate personal, work, transactional, or opted-in "
                        "message the recipient would want to keep in their inbox.",
        },
    }
}


def _decode(value: str) -> str:
    """Decode RFC2047-encoded header (e.g. =?UTF-8?...) into plain text."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _plain_body(msg: email.message.Message, limit: int = 4000) -> str:
    """Extract a text/plain body, falling back to any text part. Truncated."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8",
                                          "replace")[:limit]
        # no text/plain: take the first text/* we find
        for part in msg.walk():
            if part.get_content_type().startswith("text/"):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8",
                                          "replace")[:limit]
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", "replace")[:limit]
    return ""


def find_spam_folder(imap: imaplib.IMAP4_SSL) -> str:
    """Return the mailbox flagged \\Junk (Gmail's Spam), or the Gmail default."""
    typ, boxes = imap.list()
    if typ == "OK":
        for raw in boxes:
            line = raw.decode(errors="replace")
            if "\\Junk" in line:
                # mailbox name is the quoted segment at the end of the LIST line
                return line.split(' "/" ')[-1].strip().strip('"')
    return "[Gmail]/Spam"


def should_move(answer: dict, threshold: float) -> bool:
    """Business rule kept in code (not left to the model): move only when Jev
    says SPAM at or above the confidence threshold."""
    return answer.get("choice") == "SPAM" and answer.get("confidence", 0.0) >= threshold


def classify_batch(emails: list) -> dict:
    """Classify many emails in ONE Jev call.

    emails: list of dicts with keys id/from/subject/body.
    Returns {email_id: answer_dict}. Jev takes one `state` with all emails and
    one spam question per email id, so N emails cost 1 HTTP request.
    """
    if not emails:
        return {}
    state = {"emails": emails}
    questions = {
        f"{e['id']}_spam": {
            "type": "choice",
            "instructions": (
                f"For the email in state.emails whose id is '{e['id']}', "
                "is it unsolicited spam / scam / phishing / bulk marketing the "
                "recipient did not ask for, or a legitimate message?"
            ),
            "criteria": {
                "SPAM": "Unsolicited bulk mail, scams, phishing, prize/lottery "
                        "fraud, fake invoices, or marketing never opted into.",
                "NOT_SPAM": "A legitimate personal, work, transactional, or "
                            "opted-in message the recipient would want to keep.",
            },
        }
        for e in emails
    }
    answers = ask_jev(state, questions)["answers"]
    return {e["id"]: answers.get(f"{e['id']}_spam", {}) for e in emails}


def sort_inbox(gmail: str, app_password: str, threshold: float = 0.95,
               live: bool = False, limit: int = 12) -> dict:
    """Classify recent unread Gmail and optionally move confident spam.

    Credentials are passed in and used only for this call — never stored or
    logged here. Returns a JSON-serialisable dict:

        {
          "live": bool, "threshold": float, "checked": int,
          "moved": int, "kept": int, "skipped": int,
          "items": [{"choice","confidence","moved","subject","from"}, ...],
        }

    Raises imaplib.IMAP4.error on login/IMAP failure so the caller can report it.
    """
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(gmail, app_password)
    try:
        spam_folder = find_spam_folder(imap)
        # readonly in dry-run so we physically cannot alter the mailbox
        imap.select("INBOX", readonly=not live)

        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            raise imaplib.IMAP4.error("inbox search failed")
        ids = data[0].split()
        ids = ids[-limit:] if ids else []  # most recent `limit` unread

        # Phase 1: fetch all messages, build the batch. `id` is the IMAP message
        # number (as str) so we can move it later and map answers back.
        emails, skipped = [], 0
        for num in ids:
            # BODY.PEEK so a dry-run doesn't mark mail as read
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            # Gmail sometimes returns no usable payload; msg_data[0] is then None
            # (not a (header, bytes) tuple). Skip rather than crash.
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                skipped += 1
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            emails.append({
                "id": num.decode(),
                "from": _decode(msg.get("From", "")),
                "subject": _decode(msg.get("Subject", "")),
                "body": _plain_body(msg),
            })

        # Phase 2: one batched Jev call for the whole set.
        results = classify_batch(emails)

        # Phase 3: build report and (if live) move.
        items, moved, kept = [], 0, 0
        for e in emails:
            ans = results.get(e["id"], {})
            move = should_move(ans, threshold)
            if move and live:
                imap.copy(e["id"], spam_folder)
                imap.store(e["id"], "+FLAGS", "\\Deleted")
            if move:
                moved += 1
            else:
                kept += 1
            items.append({
                "choice": ans.get("choice"),
                "confidence": round(float(ans.get("confidence", 0.0)), 4),
                "moved": bool(move),  # in dry-run this means "would move"
                "subject": e["subject"][:120],
                "from": e["from"][:80],
            })

        if live:
            imap.expunge()

        return {
            "live": live, "threshold": threshold, "checked": len(emails),
            "moved": moved, "kept": kept, "skipped": skipped, "items": items,
        }
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


def run(live: bool, threshold: float, limit: int) -> None:
    """CLI wrapper: read creds from env, call sort_inbox, print a report."""
    report = sort_inbox(
        gmail=os.environ["GMAIL_ADDRESS"],
        app_password=os.environ["GMAIL_APP_PASSWORD"],
        threshold=threshold, live=live, limit=limit,
    )
    mode = "LIVE — moving spam" if live else "DRY-RUN — moving nothing"
    print(f"[{mode}] threshold={threshold}  checking {report['checked']} "
          f"unread message(s)\n")
    for it in report["items"]:
        tag = "SPAM " if it["choice"] == "SPAM" else "ok   "
        if it["moved"]:
            action = "-> MOVE to spam"
        elif it["choice"] == "SPAM":
            action = "   keep (below threshold)"
        else:
            action = "   keep"
        print(f"[{tag}{it['confidence']:>5.2f}] {action}  | "
              f"{it['subject'][:70]!r}  <{it['from'][:40]}>")
    if report["skipped"]:
        print(f"\n({report['skipped']} message(s) skipped: unreadable fetch)")
    if live:
        print(f"\nDone. Moved {report['moved']} to spam, kept {report['kept']}.")
    else:
        print(f"\nDry-run complete. Would move {report['moved']}, "
              f"keep {report['kept']}. Re-run with --live to apply.")


def main() -> None:
    p = argparse.ArgumentParser(description="Classify Gmail inbox with Jev; move spam.")
    p.add_argument("--live", action="store_true",
                   help="actually move spam (default: dry-run, moves nothing)")
    p.add_argument("--threshold", type=float, default=0.95,
                   help="min Jev confidence to move as spam (default 0.95)")
    p.add_argument("--limit", type=int, default=20,
                   help="max recent unread messages to check (default 20)")
    args = p.parse_args()
    if not 0.0 < args.threshold <= 1.0:
        p.error("--threshold must be in (0, 1]")
    run(live=args.live, threshold=args.threshold, limit=args.limit)


if __name__ == "__main__":
    main()
