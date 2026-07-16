# census2011-tamilnadu-pipeline

Automated GitHub Actions pipeline that fetches district-level Census of
India 2011 data products for Tamil Nadu (32 districts, 2011 boundaries)
into this repo, version-controlled and citeable.

Built to feed the socio-demographic layer (population density, urbanisation
rate, literacy rate) of a district × month × year dengue transmission
determinants study — see `docs/Census2011_TamilNadu_Workflow.docx` for the
full data-acquisition workflow and rationale.

## Structure

```
.github/workflows/fetch-census-tn.yml   GitHub Actions workflow (manual trigger)
scripts/fetch_census.py                 Fetch script — standard library only, no pip installs
data/census/dchb/                       District Census Handbook Part A/B PDFs (32 districts)
data/census/pca/                        State-wide Primary Census Abstract files
data/census/unresolved.csv              Anything the script couldn't resolve automatically
docs/Census2011_TamilNadu_Workflow.docx Full manual workflow, data dictionary, district list
```

## Setup

1. Push this repo to GitHub (see below).
2. In the repo, go to **Settings → Actions → General → Workflow permissions**
   and select **Read and write permissions**. Without this the commit step
   in the workflow will fail with a 403.
3. Go to the **Actions** tab → **Fetch Census 2011 - Tamil Nadu** →
   **Run workflow**. Census 2011 is static data, so this only needs to run
   once (workflow_dispatch, no cron schedule). Re-running later is safe —
   the script skips files it already has.
4. After the run, check `data/census/unresolved.csv` — the source site
   (censusindia.gov.in) is scraped via regex against its NADA catalog
   pages, not a documented API, so some districts may need a manual
   download using the steps in `docs/Census2011_TamilNadu_Workflow.docx`
   section 5.

## Pushing this repo to GitHub

This folder is already a git repo with an initial commit. Create an empty
repository on GitHub (no README/license/gitignore — this already has them),
then:

```bash
cd census2011-tamilnadu-pipeline
git remote add origin https://github.com/<your-username>/census2011-tamilnadu-pipeline.git
git branch -M main
git push -u origin main
```

## Notes

- No API keys or secrets required.
- The fetch script was written and syntax-checked in a network-restricted
  environment that could not reach censusindia.gov.in directly, so its
  scraping logic is best-effort — verify the first live run's output and
  adjust `scripts/fetch_census.py` if the site's markup has changed.
- Census 2011 predates Tamil Nadu's 2019 district reorganisation (32 → 38
  districts). Crosswalk using LGD codes before merging with newer data.
