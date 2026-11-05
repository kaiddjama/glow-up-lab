#!/usr/bin/env python3
"""Checks that PROTOCOLE-INVENTAIRE.md says the same as the code: the settings line (section 8) against the defaults
in amazon_sync.py, and the full-check times (section 4) against the cron lines of stock-sync.yml. Fails on any gap,
so the protocol cannot silently drift from what really runs."""
import os
import re
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
proto = open(os.path.join(root, "PROTOCOLE-INVENTAIRE.md"), encoding="utf-8").read()
code = open(os.path.join(root, "stock-sync", "amazon_sync.py"), encoding="utf-8").read()
wf = open(os.path.join(root, ".github", "workflows", "stock-sync.yml"), encoding="utf-8").read()
gaps = []
for name, val in re.findall(r"\b([A-Z_]{4,})=([0-9]+(?:,[0-9]+)?)", proto.split("## 8.")[1].split("## 9.")[0]):
    m = re.search(rf'os\.environ\.get\("{name}", "([^"]+)"\)', code)
    if not m:
        gaps.append(f"{name}: not found in amazon_sync.py")
        continue
    code_val = m.group(1)
    if name == "NO_DATE_KEEPS":
        ok = val == code_val
    else:
        ok = float(val.replace(",", ".")) == float(code_val)
    if not ok:
        gaps.append(f"{name}: protocol says {val}, code says {code_val}")
crons = sorted(f"{(int(h) + 3) % 24:02d}:{int(m):02d}" for m, h in re.findall(r'cron: "(\d+) (\d+) \* \* \*"', wf))
times = re.search(r"\| ([0-9:, ]+) \| Contrôle complet", proto)
proto_times = sorted(t.strip() for t in times.group(1).split(",")) if times else []
if crons != proto_times:
    gaps.append(f"full-check times: protocol says {proto_times}, stock-sync.yml says {crons} (Djibouti time)")
for g in gaps:
    print("GAP:", g)
if gaps:
    sys.exit("PROTOCOLE-INVENTAIRE.md does not match the code: update it in the same change.")
print("Protocol matches the code.")
