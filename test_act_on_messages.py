"""Offline self-check for act_on_messages(). No mailbox, no network.

act_on_messages permanently deletes mail, so its targeting and its trash-vs-delete
IMAP command sequence are the risky logic that gets the check. We stub the IMAP
connection with a fake that records every call, so we can assert exactly what
would hit a real server.

Run: python3 test_act_on_messages.py
"""
import gmail_jev_sorter as g


class FakeIMAP:
    """Minimal stand-in that records the IMAP calls act_on_messages makes."""
    def __init__(self, present_ids):
        self.present = set(present_ids)  # Message-IDs that "exist" in Spam
        self.calls = []                  # ordered log of (op, *args)

    def login(self, u, p): self.calls.append(("login",))
    def list(self):
        return ("OK", [
            b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
        ])
    def select(self, box, readonly=False): self.calls.append(("select", box, readonly))
    def search(self, charset, *criteria):
        # criteria == ("HEADER","Message-ID", '"<mid>"') — value is quoted now
        mid = criteria[-1].strip('"')
        self.calls.append(("search", mid))
        return ("OK", [b"7" if mid in self.present else b""])
    def copy(self, num, box): self.calls.append(("copy", num, box))
    def store(self, num, flag, val): self.calls.append(("store", num, flag, val))
    def expunge(self): self.calls.append(("expunge",))
    def close(self): pass
    def logout(self): pass


def run_with(present, ids, action):
    fake = FakeIMAP(present)
    g.imaplib.IMAP4_SSL = lambda host: fake            # patch the constructor
    res = g.act_on_messages("u@gmail.com", "pw", ids, action)
    return res, fake.calls


# 1. trash: existing message -> copy to Trash, flag Deleted, expunge
res, calls = run_with({"<a@x>"}, ["<a@x>"], "trash")
assert res == {"action": "trash", "requested": 1, "done": 1, "not_found": 0}, res
assert ("select", "[Gmail]/Spam", False) in calls
assert ("copy", b"7", "[Gmail]/Trash") in calls, "trash must place a copy in Trash"
assert ("store", b"7", "+FLAGS", "\\Deleted") in calls
assert ("expunge",) in calls
print("ok: trash copies to Trash then removes from Spam")

# 2. delete: existing message -> flag Deleted + expunge, but NEVER copy anywhere
res, calls = run_with({"<b@x>"}, ["<b@x>"], "delete")
assert res["done"] == 1 and res["not_found"] == 0, res
assert not any(c[0] == "copy" for c in calls), "permanent delete must not copy"
assert ("store", b"7", "+FLAGS", "\\Deleted") in calls
assert ("expunge",) in calls
print("ok: delete expunges without copying (irreversible path is clean)")

# 3. targeting: only ids found in Spam are acted on; missing ones counted.
#    A found id searches once; a missing id also tries the bracket-stripped form.
res, calls = run_with({"<here@x>"}, ["<here@x>", "<gone@x>"], "trash")
assert res == {"action": "trash", "requested": 2, "done": 1, "not_found": 1}, res
searched = [c[1] for c in calls if c[0] == "search"]
assert "<here@x>" in searched, "must search the exact Message-ID"
assert "gone@x" in searched, "must fall back to bracket-stripped form when not found"
print("ok: acts only on ids present in Spam, counts not-found, uses fallback")

# 4. bad action rejected before any IMAP work
try:
    g.act_on_messages("u", "p", ["<a@x>"], "nuke")
    raise SystemExit("FAIL: bad action was not rejected")
except ValueError:
    print("ok: invalid action raises ValueError")

# 5. empty id list is a no-op (no login/expunge)
res = g.act_on_messages("u", "p", ["", "  "], "delete")
assert res == {"action": "delete", "requested": 0, "done": 0, "not_found": 0}, res
print("ok: empty/blank ids -> no-op")

print("\nAll act_on_messages checks passed.")
