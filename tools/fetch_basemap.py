#!/usr/bin/env python3
"""Fetch basemap geometry (water, highways, streets with names) for the tri-county area from the
Census Bureau's TIGERweb service and write it as small JSON files under app/basemap/.
Run by the "Fetch basemap" workflow; the tracker page loads these files instead of map tiles."""
import json, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

B = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
X0, Y0, X1, Y1, CELL = -80.95, 25.08, -79.95, 27.03, 0.1
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "basemap")
os.makedirs(OUT, exist_ok=True)


def call(u, p, post=False, tries=4):
    data = urllib.parse.urlencode(p)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(u if post else u + "?" + data, data=data.encode() if post else None,
                                         headers={"User-Agent": "Mozilla/5.0 govland-tracker"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, dict) and "error" in d:
                raise RuntimeError(str(d["error"])[:200])
            return d
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("%s: %s" % (u[-60:], last))


def find_layer(svc, wanted):
    m = call("%s/%s/MapServer" % (B, svc), {"f": "json"})
    names = [(l["id"], l["name"]) for l in m["layers"]]
    print("LAYERS", svc, names[:40], flush=True)
    for w in wanted:
        for i, n in names:
            if n.strip().lower() == w.lower():
                url = "%s/%s/MapServer/%d" % (B, svc, i)
                f = [x["name"] for x in call(url, {"f": "json"}).get("fields", [])]
                print("USING", url, "fields", f, flush=True)
                return url, f
    raise RuntimeError("no layer named %s in %s" % (wanted, svc))


def ids(url, env, where="1=1"):
    d = call(url + "/query", {"where": where, "geometry": "%s,%s,%s,%s" % env, "geometryType": "esriGeometryEnvelope",
                              "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "returnIdsOnly": "true", "f": "json"})
    return d.get("objectIds") or []


def feats(url, oids, fields, offset, chunk=400):
    for i in range(0, len(oids), chunk):
        d = call(url + "/query", {"objectIds": ",".join(map(str, oids[i:i + chunk])), "outFields": ",".join(fields),
                                  "returnGeometry": "true", "outSR": 4326, "geometryPrecision": 5,
                                  "maxAllowableOffset": offset, "f": "json"}, post=True)
        for f in d.get("features", []):
            yield f


def pick(fields, *cands):
    up = {f.upper(): f for f in fields}
    return next((up[c] for c in cands if c in up), None)


def nm(attrs, key):
    return (str(attrs.get(key) or "").strip()) if key else ""


def major(kind, wanted, fname_key):
    url, fields = find_layer("Transportation", wanted)
    nk = pick(fields, "NAME", "FULLNAME", "BASENAME")
    oid = ids(url, (X0, Y0, X1, Y1))
    out = {}
    for f in feats(url, oid, [nk] if nk else ["OBJECTID"], 0.0001):
        for path in (f.get("geometry") or {}).get("paths", []):
            if len(path) > 1:
                out.setdefault(nm(f["attributes"], nk), []).append([round(v, 4) for pt in path for v in pt[:2]])
    print(kind, "features", len(oid), "names", len(out), flush=True)
    return out


def water():
    url, fields = find_layer("Hydro", ["Areal Hydrography"])
    ak, nk = pick(fields, "AREAWATER"), pick(fields, "NAME", "FULLNAME", "BASENAME")
    oid = ids(url, (X0, Y0, X1, Y1), "%s >= 40000" % ak if ak else "1=1")
    polys = []
    for f in feats(url, oid, [k for k in (nk, ak) if k] or ["OBJECTID"], 0.0002, chunk=150):
        rings = [[round(v, 4) for pt in r for v in pt[:2]] for r in (f.get("geometry") or {}).get("rings", []) if len(r) > 3]
        if rings:
            polys.append(rings)
    print("water polygons", len(polys), "of", len(oid), "ids; area field", ak, flush=True)
    return polys


def local_cell(args):
    url, nk, i, j = args
    cx, cy = X0 + i * CELL, Y0 + j * CELL
    try:
        oid = ids(url, (cx, cy, cx + CELL, cy + CELL))
        roads, n = {}, 0
        for f in feats(url, oid, [nk] if nk else ["OBJECTID"], 0.00003):
            for path in (f.get("geometry") or {}).get("paths", []):
                if len(path) < 2:
                    continue
                mx, my = path[len(path) // 2][:2]          # a path belongs to the cell holding its middle vertex
                if not (cx <= mx < cx + CELL and cy <= my < cy + CELL):
                    continue
                roads.setdefault(nm(f["attributes"], nk), []).append(
                    [int(round((v - (cx, cy)[k % 2]) * 1e5)) for pt in path for k, v in enumerate(pt[:2])])
                n += 1
        if n:
            json.dump({"x0": round(cx, 2), "y0": round(cy, 2), "r": roads}, open(os.path.join(OUT, "r_%d_%d.json" % (i, j)), "w"), separators=(",", ":"))
        return (i, j, n, None)
    except Exception as e:
        return (i, j, 0, str(e)[:150])


def main():
    json.dump({"p": major("primary", ["Primary Roads"], "p"), "s": major("secondary", ["Secondary Roads"], "s")},
              open(os.path.join(OUT, "major.json"), "w"), separators=(",", ":"))
    try:
        json.dump(water(), open(os.path.join(OUT, "water.json"), "w"), separators=(",", ":"))
    except Exception as e:
        print("WATER FAILED", e, flush=True)
    url, fields = find_layer("Transportation", ["Local Roads"])
    nk = pick(fields, "NAME", "FULLNAME", "BASENAME")
    ni, nj = int(round((X1 - X0) / CELL)), int(round((Y1 - Y0) / CELL + 0.49))
    jobs = [(url, nk, i, j) for i in range(ni) for j in range(nj)]
    cells, failed, total = [], [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, j, n, err in pool.map(local_cell, jobs):
            if err:
                failed.append("%d_%d" % (i, j)); print("CELL FAILED", i, j, err, flush=True)
            elif n:
                cells.append("%d_%d" % (i, j)); total += n
    json.dump({"x0": X0, "y0": Y0, "cell": CELL, "cells": cells, "failed": failed, "fetched": time.strftime("%Y-%m-%d")},
              open(os.path.join(OUT, "index.json"), "w"), separators=(",", ":"))
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print("DONE cells %d, failed %d, street segments %d, total %.1f MB" % (len(cells), len(failed), total, size / 1e6), flush=True)


main()
