"""Recompute the published preservation digest; optionally check the local trial bytes."""
import argparse
import hashlib
import json
from pathlib import Path


def aggregate(rows, field):
    data = "".join(row["path"] + "\0" + row[field] + "\n"
                   for row in sorted(rows, key=lambda row: row["path"]))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--trial-root", type=Path)
    args = parser.parse_args()
    record = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = record["files"]
    errors = []
    if len(rows) != record["captured_files"] or len({row["path"] for row in rows}) != len(rows):
        errors.append("file count or duplicate path")
    for field, key in (("before_sha256", "manifest_before_sha256"), ("after_sha256", "manifest_after_sha256")):
        if aggregate(rows, field) != record[key]:
            errors.append(key)
    for row in rows:
        path = Path(row["path"])
        if path.is_absolute() or ".." in path.parts:
            errors.append("invalid relative path: " + row["path"])
            continue
        if row["before_sha256"] != row["after_sha256"]:
            errors.append("changed file: " + row["path"])
        if args.trial_root:
            digest = hashlib.sha256((args.trial_root / path).read_bytes()).hexdigest()
            if digest != row["after_sha256"]:
                errors.append("current bytes: " + row["path"])
    print(json.dumps({"files": len(rows), "errors": errors, "current_bytes_checked": args.trial_root is not None}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
