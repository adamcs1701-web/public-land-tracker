#!/usr/bin/env python3
"""Re-apply the ownership and zoning rules to the saved data without re-downloading it.
Use after changing the rules in core.py:  python3 reprocess.py"""
import json, os
import core
base = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(base, "config.json")))
path = os.path.join(base, cfg["output"])
doc = json.load(open(path))
density = core.load_table(os.path.join(base, cfg["zoning_density_table"]), ("jurisdiction", "zoning_code"))
surplus = core.load_table(os.path.join(base, cfg["surplus_list"]), ("county", "parcel_id"))
bounds = {k: (core.Boundary(json.load(open(os.path.join(base, c["development_boundary"]["file"]))), c["development_boundary"].get("name", "")), c["development_boundary"].get("drop_outside"))
          for k, c in cfg["counties"].items() if c.get("development_boundary") and os.path.exists(os.path.join(base, c["development_boundary"]["file"]))}
keep, dropped = [], 0
for p in doc["parcels"]:
    rec = dict(p); rec["zoning_category"] = None; rec["max_du_per_acre"] = None
    if p["county"] in bounds:
        b, drop = bounds[p["county"]]
        rec["inside_boundary"] = b.contains(rec.get("lon"), rec.get("lat"))
        if drop and rec["inside_boundary"] is False:
            dropped += 1
            continue
    r = core.enrich(rec, cfg["counties"][p["county"]], density, surplus)
    if r is None or r["owner_level"] in set(cfg.get("exclude_owner_levels", [])):
        dropped += 1
        continue
    for k in ("provider", "last_seen", "first_seen"):
        r[k] = p.get(k)
    keep.append(r)
doc["parcels"] = keep
for s in doc["sources"]:
    s["parcels"] = sum(1 for p in keep if p["county"] == s["county"])
json.dump(doc, open(path, "w"), separators=(",", ":"))
print("kept %d, dropped %d (not government, excluded owner type, or outside the development boundary)" % (len(keep), dropped))
