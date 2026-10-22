import json
import re
import subprocess
import sys


def load_coverage(path, root):
    data = json.load(open(path))
    executed, executable = {}, {}
    for f, info in data["files"].items():
        f = f.replace("\\", "/")
        if not f.startswith("/"):
            f = f"{root}/brain/{f}"
        executed[f] = set(info["executed_lines"])
        executable[f] = set(info["executed_lines"]) | set(info["missing_lines"])
    return executed, executable


def added_lines(base, head, paths=None):
    cmd = ["git", "diff", "-U0", base, head, "--"]
    if paths:
        cmd += paths
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    current = None
    result = {}
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/"):]
            result.setdefault(current, set())
        elif line.startswith("@@") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2) or 1)
            result[current].update(range(start, start + count))
    return {k: v for k, v in result.items() if v}


def report(base, head, label):
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip()
    executed, executable = load_coverage(f"{root}/brain/cov_report.json", root)
    print(f"\n=== {label}: {base}..{head} ===")
    totals = {"src": [0, 0], "test": [0, 0]}
    for rel, added in sorted(added_lines(base, head).items()):
        if not rel.endswith(".py"):
            continue
        abs_path = f"{root}/{rel}"
        if abs_path not in executable:
            print(f"\n{rel}  [not measured]  {len(added)} added lines")
            continue
        lines = added & executable[abs_path]
        covered = lines & executed[abs_path]
        missing = sorted(lines - covered)
        bucket = "test" if "/tests/" in rel else "src"
        totals[bucket][0] += len(covered)
        totals[bucket][1] += len(lines)
        pct = (100.0 * len(covered) / len(lines)) if lines else 100.0
        print(f"\n{rel}  [{bucket}]  {len(covered)}/{len(lines)} = {pct:.0f}%")
        if missing:
            print("  uncovered: " + ",".join(str(n) for n in missing))
    for bucket, (c, t) in totals.items():
        if t:
            print(f"\n{bucket.upper()} TOTAL: {c}/{t} = {100.0 * c / t:.1f}%")


if __name__ == "__main__":
    report(sys.argv[1], sys.argv[2], sys.argv[3])
