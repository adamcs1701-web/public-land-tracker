#!/usr/bin/env python3
"""Refresh the government-land dataset.  Usage: python3 run.py [--config config.json]
Schedule it weekly (cron / GitHub Actions); each run rewrites the output file and
appends to its change log."""
import argparse, datetime, json, os, sys
from concurrent.futures import ThreadPoolExecutor
import core, providers

p = argparse.ArgumentParser()
p.add_argument("--config", default="config.json")
p.add_argument("--only", help="comma-separated county keys")
args = p.parse_args()
base = os.path.dirname(os.path.abspath(args.config))
cfg = json.load(open(args.config))
rel = lambda x: os.path.join(base, x) if x else x
out_path = rel(cfg["output"])
today = datetime.date.today().isoformat()

prev = json.load(open(out_path)) if os.path.exists(out_path) else {"parcels": [], "changes": []}
key = lambda r: r["county"] + "|" + r["id"]
EXCLUDE = set(cfg.get("exclude_owner_levels", []))
def _still_in_scope(r):       # so a rule change is not reported as parcels leaving government hands
    b = cfg["counties"].get(r["county"], {}).get("development_boundary") or {}
    return r.get("owner_level") not in EXCLUDE and not (b.get("drop_outside") and r.get("inside_boundary") is False)
old = {key(r): r for r in prev["parcels"] if _still_in_scope(r)}
density = core.load_table(rel(cfg.get("zoning_density_table")), ("jurisdiction", "zoning_code"))
surplus = core.load_table(rel(cfg.get("surplus_list")), ("county", "parcel_id"))

# Zoning found in the last 60 days is reused; older answers are looked up again.
zoning_recheck_after = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
new, sources, failed = {}, [], []
wanted = set(args.only.split(",")) if args.only else None
for ckey, ccfg in cfg["counties"].items():
    if wanted and ckey not in wanted:
        new.update({k: r for k, r in old.items() if r["county"] == ckey})
        sources.extend(s for s in prev.get("sources", []) if s.get("county") == ckey)
        continue
    ok = False
    for pcfg in ccfg["providers"]:
        if pcfg.get("path"):
            pcfg = dict(pcfg, path=rel(pcfg["path"]))
        try:
            prov = providers.make(pcfg, ckey, ccfg)
            n_raw = n_kept = 0
            got = {}
            zsrc = (cfg.get("zoning_sources") or {}).get(ckey, [])
            bcfg = ccfg.get("development_boundary")
            bound = core.load_boundary(bcfg, base)
            recs, n_outside = [], 0
            for rec in prov.fetch():
                n_raw += 1
                if not core.owner_level(rec["owner"], rec["use_code"], rec["public_land_flag"], ccfg.get("owner_patterns", ()))[0]:
                    continue
                if (rec["acres"] or 0) < cfg.get("min_acres", 0):
                    continue
                if bound:
                    rec["inside_boundary"] = bound.contains(rec["lon"], rec["lat"])
                    if bcfg.get("drop_outside") and rec["inside_boundary"] is False:
                        n_outside += 1
                        continue
                recs.append(rec)
            if bound:
                print("%-11s %d parcels outside the %s dropped" % (ckey, n_outside, bound.name), flush=True)
            print("%-11s %d candidate parcels, looking up zoning..." % (ckey, len(recs)), flush=True)

            def add_zoning(rec):            # free feeds carry no zoning
                prev_rec = old.get(ckey + "|" + rec["id"])
                if (not rec["zoning"] and prev_rec and prev_rec.get("zoning") and prev_rec.get("lat") == rec["lat"]
                        and prev_rec.get("last_seen", "") >= zoning_recheck_after):
                    for f in ("zoning", "zoning_jurisdiction", "zoning_description", "zoning_group"):   # reuse a recent answer
                        rec[f] = prev_rec.get(f)
                if not rec["zoning"] and rec["lat"] is not None and zsrc:
                    hit = core.zoning_lookup(rec["lat"], rec["lon"], zsrc)
                    if hit:
                        rec["zoning_jurisdiction"], rec["zoning"], rec["zoning_description"], rec["zoning_group"] = hit
                return rec
            with ThreadPoolExecutor(max_workers=8) as pool:
                recs = list(pool.map(add_zoning, recs))
            for rec in recs:
                r = core.enrich(rec, ccfg, density, surplus)
                if r and r["owner_level"] not in EXCLUDE:
                    r["provider"], r["last_seen"] = prov.name, today
                    got[key(r)] = r
                    n_kept += 1
            new.update(got)
            sk = getattr(prov, "skipped", [])
            sources.append(dict(county=ckey, label=ccfg["label"], provider=prov.name,
                                source_as_of=prov.as_of(), fetched=today, parcels=len(got),
                                skipped_rows=sum(b - a + 1 for a, b in sk)))
            nz = sum(1 for x in got.values() if x["zoning"])
            print("%-11s %-38s %6d fetched, %6d government parcels kept, %6d with zoning" % (ckey, prov.name, n_raw, len(got), nz))
            for s in zsrc:
                if s.get("_dead"):
                    print("   zoning layer skipped (%s): %s" % (s["jurisdiction"], s["_dead"][:120]), file=sys.stderr)
            ok = True
            break
        except Exception as e:
            print("%-11s %s FAILED: %s" % (ckey, pcfg.get("name", pcfg["type"]), e), file=sys.stderr)
    if not ok:
        failed.append(ckey)
        new.update({k: r for k, r in old.items() if r["county"] == ckey})  # keep last good data
        sources.append(dict(county=ckey, label=ccfg["label"], provider=None, fetched=None,
                            error="all providers failed; showing last good data", parcels=0))

changes = core.diff(old, new, today, failed)
doc = dict(generated_at=today, example=False, sources=sources,
           parcels=sorted(new.values(), key=key), changes=(changes + prev.get("changes", []))[:5000])
os.makedirs(os.path.dirname(out_path), exist_ok=True)
json.dump(doc, open(out_path, "w"), separators=(",", ":"))
print("wrote %s: %d parcels, %d new changes%s" % (out_path, len(new), len(changes),
      ", FAILED: " + ",".join(failed) if failed else ""))
sys.exit(1 if failed else 0)
