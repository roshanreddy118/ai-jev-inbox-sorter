"""Self-check for the move decision. No mailbox, no network.

The move rule is the only place a bug loses real mail (a false positive buries a
legit email in spam), so it gets the check. Run: python3 test_should_move.py
"""
from gmail_jev_sorter import should_move

TH = 0.95
cases = [
    # (answer, threshold, expected_move, why)
    ({"choice": "SPAM", "confidence": 1.0}, TH, True, "confident spam moves"),
    ({"choice": "SPAM", "confidence": 0.95}, TH, True, "exactly at threshold moves"),
    ({"choice": "SPAM", "confidence": 0.949}, TH, False, "just under threshold stays"),
    ({"choice": "NOT_SPAM", "confidence": 1.0}, TH, False, "confident ham never moves"),
    ({"choice": "NOT_SPAM", "confidence": 0.10}, TH, False, "unsure ham stays"),
    ({}, TH, False, "missing/garbage answer never moves"),
]

for ans, th, expected, why in cases:
    got = should_move(ans, th)
    assert got is expected, f"FAIL ({why}): should_move({ans}, {th}) -> {got}, want {expected}"
    print(f"ok: {why}")

print("\nAll move-decision checks passed.")
