# Florida Public Land Tracker: refresh pipeline

Pulls government-owned parcels for Miami-Dade, Broward and Palm Beach, tags who owns
each one, logs what changed since the last run, and writes `data/parcels.json` for
the tracker page ("Load data file").

## Run it

    python3 run.py                 # all counties
    python3 run.py --only broward  # one county

Needs Python 3.8+ and open internet access. No packages to install. Run it weekly
(cron, Windows Task Scheduler, or a GitHub Actions schedule). Exit code is 1 if any
county failed; that county keeps its last good data and is not reported as "removed".

## Files

| File | What it does |
|---|---|
| `config.json` | Counties, and which data source each one uses |
| `providers.py` | One adapter per data source. All return the same record shape |
| `core.py` | Government-owner detection, unit estimate, change log |
| `run.py` | Ties it together and writes the output |
| `zoning_density.csv` | Your lookup: jurisdiction + zoning code -> category and max units per acre |
| `surplus_parcels.csv` | Parcels on a county or city surplus list |
| `tests/test_pipeline.py` | Offline end-to-end test against a mock server |

## Zoning

Free parcel feeds carry no zoning, so `run.py` checks each parcel's centre point
against the layers under `zoning_sources` in `config.json` (city layers first,
the county's unincorporated layer last). Only layers with `enabled: true` are
used; each has a `note` saying what is confirmed. A layer that errors is skipped
for that run and reported. Density is not in any map layer: add rows to
`zoning_density.csv`, keyed by the jurisdiction name used in `zoning_sources`.

## Switching a county to a paid source

Edit that county's `providers` list in `config.json`. Examples are under
`paid_example`. `regrid_file` reads a Regrid county CSV export; `regrid_api` calls
the Regrid Parcel API with a token from the `REGRID_TOKEN` environment variable.
Providers are tried in order, so you can list a paid source first and the free
state feed second as a fallback.

To add a different vendor, subclass `Provider` in `providers.py`, return records
with the keys in `FIELDS`, and add it to `PROVIDERS`.

## What is and is not verified

- Verified 2026-11-11: the statewide layer in `config.json` exists, uses the field
  names this code requests, and was last edited 2026-10-23.
- Tested offline only: paging, classification, change log, outage handling, and
  the Regrid file format, all against invented data.
- Not yet run: a live pull (the build environment could not reach the GIS
  servers), the Regrid API adapter (no licence), the three `appraiser_url`
  deep-link patterns, and the zoning layers. Three are enabled (layer and code field confirmed
  by reading their published metadata on 2026-11-11); none has been queried live.
