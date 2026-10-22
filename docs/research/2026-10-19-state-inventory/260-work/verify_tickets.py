import json, re, subprocess, urllib.request, http.client
tok = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
def get(path):
    out = subprocess.run(["curl", "-s", "-H", f"Authorization: Bearer {tok}", "-H", "Accept: application/vnd.github+json",
                          "https://api.github.com" + path], capture_output=True, text=True).stdout
    return json.loads(out)
state = json.load(open("tickets-state.json"))
src = open("create_tickets.py", encoding="utf-8").read().split("tickets = parse()")[0]
ns = {}; exec(src.replace("GO = \"--go\" in sys.argv", "GO = False"), ns)
want_blocked = {t["id"]: t["blocked_by"] for t in ns["parse"]()}
by_id = {v["id"]: k for k, v in state.items()}
bad = 0
for h, st in state.items():
    d = get(f"/repos/{st['repo']}/issues/{st['number']}")
    deps = get(f"/repos/{st['repo']}/issues/{st['number']}/dependencies/blocked_by")
    got_blocked = sorted(by_id.get(x["id"], "?") for x in deps)
    ok = (d["title"] == st["title"] and d["body"] == st["body"] and sorted(want_blocked[h]) == got_blocked
          and not ns["HANDLE"].search(d["body"].replace("ADR-0025", "")))
    labels = [l["name"] for l in d["labels"]]
    if not ok:
        bad += 1
    print(h, st["repo"].split("/")[1], st["number"], "OK" if ok else "MISMATCH", labels, got_blocked)
print("mismatches:", bad)
