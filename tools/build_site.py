#!/usr/bin/env python3
"""Build the data files the hosted site reads (docs/data.json, docs/boundaries.json) from data/parcels.json.
Run after every refresh:  python3 tools/build_site.py"""
import json, os, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(root, "data", "parcels.json")))
cfg = json.load(open(os.path.join(root, "config.json")))
skip = set(cfg.get("exclude_owner_levels", []))
cols = ["id", "county", "owner", "owner_level", "gov_basis", "use_code", "use_label", "acres", "vacant", "just_value",
        "address", "city", "lat", "lon", "zoning", "zoning_category", "max_du_per_acre", "est_units", "flood_zone",
        "surplus_list", "leased", "first_seen", "zoning_jurisdiction", "zoning_description", "department", "max_du_per_acre_high", "density_note", "land_use"]
dc = ["county", "owner", "owner_level", "gov_basis", "use_label", "city", "zoning", "zoning_category", "surplus_list",
      "first_seen", "zoning_jurisdiction", "zoning_description", "flood_zone", "department", "density_note", "land_use"]
dicts, idx, rows = {c: [] for c in dc}, {c: {} for c in dc}, []
def enc(c, v):
    if v is None: return None
    if c in idx:
        if v not in idx[c]:
            idx[c][v] = len(dicts[c]); dicts[c].append(v)
        return idx[c][v]
    if c in ("lat", "lon"): return round(v, 5)
    if c == "acres": return round(v, 2)
    if c in ("vacant", "leased"): return 1 if v else 0
    if c == "just_value": return int(v)
    return v
parcels = [p for p in d["parcels"] if p.get("owner_level") not in skip]
for p in parcels:
    if p.get("zoning_description"): p["zoning_description"] = p["zoning_description"].replace("\xa0", " ").strip()
    rows.append([enc(c, p.get(c)) for c in cols])
have = {s["county"]: s for s in d["sources"]}
src = []
for k, c in cfg["counties"].items():
    s = dict(have.get(k) or dict(county=k, label=c["label"], provider=None, fetched=None, error="Not loaded yet"))
    s["parcels"] = sum(1 for p in parcels if p["county"] == k)
    if s.get("provider"): s["provider"] = "Florida statewide parcel layer (%s tax roll)" % (parcels[0].get("roll_year") if parcels else "")
    src.append(s)
doc = dict(generated_at=d["generated_at"], example=False, sources=src, changes=[c for c in d.get("changes", [])][:300],
           appraiser_urls={k: v["appraiser_url"] for k, v in cfg["counties"].items()},
           packed=dict(cols=cols, dicts=dicts, rows=rows),
           parcel_layers={k: v['providers'][0]['url'] for k, v in cfg['counties'].items() if v['providers'][0].get('url')})
geo = json.load(open(os.path.join(root, "app", "boundaries.json")))
out = {"dev": [], "places": [{"name": p["name"], "polys": p["polys"]} for p in geo.get("places", [])]}
for k, c in cfg["counties"].items():          # development limits: outer rings
    bc = c.get("development_boundary")
    fp = bc and os.path.join(root, bc["file"])
    if fp and os.path.exists(fp):
        for f in json.load(open(fp))["features"]:
            g = f["geometry"]
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
                if len(poly[0]) >= 4:
                    out["dev"].append([[round(x, 5), round(y, 5)] for x, y in poly[0]])
docs = os.path.join(root, "docs")
os.makedirs(docs, exist_ok=True)
json.dump(doc, open(os.path.join(docs, "data.json"), "w"), separators=(",", ":"))
json.dump(out, open(os.path.join(docs, "boundaries.json"), "w"), separators=(",", ":"))
open(os.path.join(docs, ".nojekyll"), "w").write("")
print("site data: %d parcels, data.json %.1f MB, %d development-limit rings" % (len(parcels), os.path.getsize(os.path.join(docs, "data.json")) / 1e6, len(out["dev"])))
