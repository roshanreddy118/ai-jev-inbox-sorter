"""Minimal Jev (TypeSafe System One) test: send one question, print the answer.

Run:
    export JEV_API_KEY='apikey_...'
    python3 jev_test.py
"""
import json
import os
import urllib.request

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def ask_jev(state: dict, questions: dict, model: str = "jev-latest") -> dict:
    """POST one decision request to Jev and return the parsed 'answers' dict."""
    key = os.environ["JEV_API_KEY"]  # set via env var, never hardcode
    payload = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


if __name__ == "__main__":
    # State = the data you want judged. Questions = the typed judgments to make.
    state = {
        "from": "winner@lotto-prize-intl.biz",
        "subject": "CONGRATULATIONS!! You WON $5,000,000 claim NOW",
        "body": "Send your bank details and a $200 processing fee to claim your prize.",
    }
    questions = {
        "is_spam": {
            "type": "choice",  # choice | score | noul(boolean)
            "instructions": "Is this email spam/scam/phishing, or a legitimate message?",
            "criteria": {
                "SPAM": "Unsolicited bulk mail, scams, phishing, prize/lottery fraud.",
                "NOT_SPAM": "A legitimate personal or business email the recipient wants.",
            },
        }
    }

    result = ask_jev(state, questions)
    print(json.dumps(result, indent=2))

    ans = result["answers"]["is_spam"]
    print(f"\n-> {ans['choice']}  (confidence {ans['confidence']})")
