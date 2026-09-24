"""Offline self-check for act_on_messages(). No mailbox, no network.

act_on_messages permanently deletes mail, so its targeting and its trash-vs-delete
IMAP command sequence are the risky logic that gets the check. We stub the IMAP
connection with a fake that records every call, so we can assert exactly what
would hit a real server.

Run: python3 test_act_on_messages.py
"""
import gmail_jev_sorter as g

g.time.sleep = lambda *_: None  # don't actually wait during retry tests


class FakeIMAP:
    """Minimal stand-in that records the IMAP calls act_on_messages makes."""
    def __init__(self, present_ids, appear_after=None):
        self.present = set(present_ids)  # Message-IDs that "exist" in Spam now
        # {mid: n} -> mid becomes findable on the (n+1)-th search attempt,
        # simulating Gmail's index catching up after a fresh move.
        self.appear_after = appear_after or {}
        self.seen = {}
        self.calls = []                  # ordered log of (op, *args)

    def login(self, u, p): self.calls.append(("login",))
    def list(self):
        return ("OK", [
            b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
        ])
    def select(self, box, readonly=False): self.calls.append(("select", box, readonly))
    def search(self, charset, *criteria):
        # two shapes: ("X-GM-RAW","rfc822msgid:mid") or ("HEADER","Message-ID",'"<mid>"')
        if criteria[0] == "X-GM-RAW":
            mid = "<" + criteria[1].split("rfc822msgid:", 1)[-1] + ">"
        else:
            mid = criteria[-1].strip('"')
            if not mid.startswith("<"):
                mid = "<" + mid + ">"   # normalise bracket-stripped fallback
        self.calls.append(("search", mid.strip("<>")))
        self.seen[mid] = self.seen.get(mid, 0) + 1
        here = mid in self.present or (
            mid in self.appear_after and self.seen[mid] > self.appear_after[mid])
        return ("OK", [b"7" if here else b""])
    def copy(self, num, box): self.calls.append(("copy", num, box))
    def store(self, num, flag, val): self.calls.append(("store", num, flag, val))
    def expunge(self): self.calls.append(("expunge",))
    def close(self): pass
    def logout(self): pass


def run_with(present, ids, action, appear_after=None):
    fake = FakeIMAP(present, appear_after)
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
assert "here@x" in searched, "must search for the present Message-ID"
assert "gone@x" in searched, "must search for the missing Message-ID"
print("ok: acts only on ids present in Spam, counts not-found")

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

# 6. index lag: a just-moved message misses the first retry round but appears on
#    a later one -> it must still be acted on, not counted as not-found.
#    Each retry round issues up to 2 searches (X-GM-RAW then HEADER), so use a
#    threshold that spans past the first round.
res, calls = run_with(set(), ["<lag@x>"], "delete", appear_after={"<lag@x>": 2})
assert res == {"action": "delete", "requested": 1, "done": 1, "not_found": 0}, res
n_searches = sum(1 for c in calls if c[0] == "search" and c[1] == "lag@x")
assert n_searches >= 2, "must retry the search when the first attempt misses"
print("ok: retries find a freshly-moved message the index missed at first")

print("\nAll act_on_messages checks passed.")
