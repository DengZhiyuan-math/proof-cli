"""Create the ADR-0025 implementation tickets from 260-tickets-final.md: python3 -I create_tickets.py [--go].
Without --go it only prints what it would create. Created numbers are kept in tickets-state.json, so a rerun skips them."""
import http.client, json, os, re, subprocess, sys, urllib.request

GO = "--go" in sys.argv
SRC = "260-tickets-final.md"
STATE = "tickets-state.json"
REPO = {"T": "DengZhiyuan-math/proof-cli", "C": "DengZhiyuan-math/proof-cli", "A": "zeqome/proof-agents", "W": "zeqome/proof-web"}
LABELS = {"T": [], "C": ["ready-for-agent"], "A": ["enhancement"], "W": ["enhancement"]}
TITLE_T0 = "ADR-0025: five states and four computed conclusions"
HANDLE = re.compile(r"\b(T0|C[1-9]|A[1-5]|W[1-4])\b")

def parse():
    text = open(SRC, encoding="utf-8").read()
    tickets, cur = [], None
    for line in text.split("\n"):
        m = re.match(r"^(##|###) (T0|C[1-9]|A[1-5]|W[1-4]) · (.*)$", line)
        if m:
            cur = {"id": m.group(2), "title": m.group(3).split(" · ")[-1], "lines": []}
            tickets.append(cur)
            continue
        if line.startswith("## ") or line.strip() == "---":
            cur = None
            continue
        if cur is not None:
            cur["lines"].append(line)
    for t in tickets:
        if t["id"] == "T0":
            t["title"] = TITLE_T0
        body = "\n".join(t["lines"]).strip("\n")
        body = re.sub(r"\b([ACW])(\d)–\1(\d)\b", lambda m: ", ".join(f"{m.group(1)}{k}" for k in range(int(m.group(2)), int(m.group(3)) + 1)), body)
        blocked = re.search(r"^Blocked by: (.*)$", body, re.M).group(1)
        t["blocked_by"] = [] if blocked.strip() in ("—", "-") else [b.strip() for b in blocked.split(",")]
        if not t["blocked_by"]:
            body = re.sub(r"\n*^Blocked by: .*$", "", body, flags=re.M)
        body = body.replace("Part of DengZhiyuan-math/proof-cli T0.", "Part of T0.")
        t["body"] = body
    return tickets

def ref(handle, from_repo, state):
    if handle not in state:  # a forward reference: filled in by the second pass
        return handle
    repo, num = REPO[handle[0]], state[handle]["number"]
    return f"#{num}" if repo == from_repo else f"{repo}#{num}"

def api(method, path, data=None):
    tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=None if data is None else json.dumps(data).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req) as r:
            try:
                raw = r.read()
            except http.client.IncompleteRead as e:  # the proxy sometimes cuts a large response short
                return r.status, {"_partial": True}
            return r.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def add_dep(repo, number, blocker):
    code, _ = api("POST", f"/repos/{repo}/issues/{number}/dependencies/blocked_by", {"issue_id": state[blocker]["id"]})
    return f"{blocker}:{code}"

tickets = parse()
assert [t["id"] for t in tickets] == ["T0"] + [f"C{k}" for k in range(1, 10)] + [f"A{k}" for k in range(1, 6)] + [f"W{k}" for k in range(1, 5)], [t["id"] for t in tickets]
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
order = [t["id"] for t in tickets]
for t in tickets:
    for b in t["blocked_by"]:
        assert order.index(b) < order.index(t["id"]), (t["id"], b)
def qualify(t, repo):
    """In a private repo, a bare #N would name that repo's own issue: point it at proof-cli."""
    if repo == REPO["C"]:
        return
    t["title"] = re.sub(r", from (#\d+(?:, #\d+)*)\)", lambda m: "; proof-cli " + m.group(1) + ")", t["title"])
    t["body"] = re.sub(r"(?<![\w/-])#(\d+)", r"DengZhiyuan-math/proof-cli#\1", t["body"])

for t in tickets:
    repo = REPO[t["id"][0]]
    qualify(t, repo)
    if t["id"] in state:
        st = state[t["id"]]
        if GO and "deps" not in st:
            st["deps"] = [add_dep(repo, st["number"], b) for b in t["blocked_by"]]
            json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
            print("deps for", t["id"], st["deps"])
        else:
            print("skip", t["id"], st["number"])
        continue
    if not GO:
        fake = {h: {"number": 900 + i} for i, h in enumerate(order)}
        body = HANDLE.sub(lambda m: ref(m.group(1), repo, fake), t["body"])
        print(f"== {t['id']} [{repo}] {t['title']} labels={LABELS[t['id'][0]]} blocked_by={t['blocked_by']} body={len(body)} chars")
        if t["id"] in ("T0", "C7", "A2", "W4"):
            print(body[:900]); print()
        continue
    body = HANDLE.sub(lambda m: ref(m.group(1), repo, state), t["body"])
    code, d = api("POST", f"/repos/{repo}/issues", {"title": t["title"], "body": body, "labels": LABELS[t["id"][0]]})
    if code != 201:
        sys.exit(f"{t['id']}: create failed {code} {d}")
    state[t["id"]] = {"repo": repo, "number": d["number"], "id": d["id"], "url": d["html_url"], "body": body, "title": t["title"]}
    json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
    state[t["id"]]["deps"] = [add_dep(repo, d["number"], b) for b in t["blocked_by"]]
    json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
    print("created", t["id"], d["html_url"], state[t["id"]]["deps"])

if GO:  # second pass: every handle now has a number
    for t in tickets:
        st = state[t["id"]]
        body = HANDLE.sub(lambda m: ref(m.group(1), st["repo"], state), t["body"])
        if body != st["body"]:
            code, d = api("PATCH", f"/repos/{st['repo']}/issues/{st['number']}", {"body": body})
            if code != 200:
                sys.exit(f"{t['id']}: patch failed {code} {d}")
            st["body"] = body
            json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
            print("patched", t["id"])
