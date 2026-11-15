# AI Policy Tracker: Indian States and UTs

A pipeline that collects news about AI-related actions by Indian state and Union Territory governments, filters it to events where a state government is the actor, removes duplicate reports, scores how well each state is covered, and publishes the result as a static dashboard.

Live dashboard: _link to be added once GitHub Pages is enabled for `/docs`_

Data window: 15 Nov 2025 to 15 Nov 2026. All 28 states and 8 UTs are scanned. Only states that pass a coverage scorecard are featured; the rest are kept in the data and shown as low coverage.

## Quickstart

```bash
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt

# only needed to fetch new data; the cached responses in data/raw are enough to rebuild everything
echo "NEWSAPI_KEY=your_key_here" > .env

python -m pipeline.run --offline     # rebuild all outputs from data/raw, no network
python -m pipeline.precision         # fold manual labels into the quality report (skips if none)
pytest                               # small test file in tests/
```

To fetch fresh data, run `python -m pipeline.run` without `--offline`. Add `--regions "Karnataka,Kerala"` to limit a fetch to some regions. Fetching is resumable: any query whose cache file exists is skipped.

To view the dashboard locally:

```bash
cd docs && python -m http.server 8000   # then open http://localhost:8000
```

## Pipeline stages

```
Google News RSS ──┐                                      data/raw/rss/      (288 files)
                  ├─ fetch.py ──> cached JSON ──────────> data/raw/newsapi/ (36 files)
NewsAPI ──────────┘
                      │
                      ▼
   normalize.py   clean text, assign state/UT, parse dates (IST), canonical URLs
                      │
                      ▼
   run.py         collapse identical articles (same article_id), keep every region that returned it
                      │
                      ▼
   classify.py    AI check, government-actor check, exclusions, category, sector, summary
                      │                          ──> data/processed/articles.csv, dropped.csv
                      ▼
   dedup.py       cluster articles into events (exact + near-duplicate)
                      │
                      ▼
   coverage.py    per-state metrics and tier (featured / low_coverage / insufficient)
                      │
                      ▼
   export.py      CSV, XLSX, quality report, samples, docs/data.json
                      │
                      ▼
   docs/index.html   static dashboard (vanilla JS + Chart.js from a CDN)
```

Thresholds, keyword lists, alias maps and outlet lists are all in `pipeline/config.py`.

## Output files

| File | Contents |
|---|---|
| `data/raw/rss/*.json` | One file per region, query group and quarter: query string, request URL, fetch time, item count, items |
| `data/raw/newsapi/*.json` | One file per region with the same fields |
| `data/processed/articles.csv` | Relevant unique articles (963), one row each, with state, basis, category, sector, summary, source |
| `data/processed/dropped.csv` | Every rejected article with its drop reasons |
| `data/processed/events_all_states.csv` | All events (777) with a `tier` column |
| `data/processed/events.csv`, `events.xlsx` | Events for featured states only. The workbook adds `state_coverage` and `column_definitions` sheets |
| `data/processed/state_coverage.csv` | Metrics, tier and failed thresholds for all 36 regions |
| `data/processed/quality_report.json` | Funnel, drop reasons, counts, largest clusters, precision |
| `data/processed/dedup_sample.csv` | 15 random multi-source events, one row per member article |
| `data/processed/dedup_calibration.csv` | Lowest-scoring merged pairs and highest-scoring unmerged pairs, used to set thresholds |
| `data/processed/relevance_sample.csv` | 3 random events per featured state for manual labelling |
| `data/labels/suggested_labels.csv` | Suggested relevant / not_relevant labels for that sample |
| `docs/data.json` | Everything the dashboard reads: events (with links to the other outlets), coverage, quality summary, data window |

### `events.csv` columns

| Column | Meaning |
|---|---|
| `event_id` | Short hash of the state and the normalised headline of the representative article |
| `state` | State or UT the event is about |
| `state_basis` | `title`, `description`, or `query` (only one region's search returned the article) |
| `title` | Headline of the representative article |
| `date` | Earliest day-precision publication date in the cluster, in IST. Blank if unknown |
| `date_precision` | `day`, `month` or `unknown` |
| `category` | `regulation_ethics`, `policy_mission`, `institution`, `partnership_mou`, `infrastructure`, `deployment`, `budget_funding`, `statement` or `other` |
| `sector` | Deployment events only: `education`, `health`, `agriculture`, `policing`, `citizen_services` or `other` |
| `summary` | First sentence of the description, up to 25 words, or the headline when there is no description |
| `source_name` | Publisher of the representative article |
| `source_url` | Link to the representative article |
| `source_count` | Distinct publishers covering the event |
| `other_sources` | Other publishers, pipe-separated |

## Inclusion and exclusion rules

An article is relevant when all of these hold:

1. It mentions AI. `AI` is matched case-sensitively as a word, plus "artificial intelligence", "GenAI", "generative AI" and "machine learning". AIADMK, AIIMS, AICTE, AIIB and Air India are removed first.
2. A state or UT government is the actor. This means a term such as government, CM, chief minister, minister, cabinet, department, police, collector, assembly, budget or MoU. For headline-only records, a state name followed within three words by an action verb (launches, signs, sets up and so on) also counts, unless the name follows an institute prefix such as IIT or University.
3. A state or UT is identified (see below).
4. None of these exclusions applies, listed in the order they are checked: 
   - `excluded_stock`: stock, share-price and market stories.
   - `excluded_opinion`: opinion, column, editorial or blog.
   - `corporate_launch`: product launches with no government actor.
   - `national_only`: MeitY, IndiaAI or Union budget items with no state.
   - `incident_not_policy`: deepfake, fake or AI-generated video stories with no policy action (ban, regulation, guidelines, law, action against, SOP).
   - `foreign_government`: a foreign country next to a government role ("UK's AI minister") with no Indian state government action.
   - `national_actor`: the Union government is the actor (Union Minister, Centre, MeitY, NITI Aayog) with no state-government signal.
   - `out_of_window`: the publication date is outside 15 Nov 2025 to 15 Nov 2026 (older stories re-published). 
   - `foreign_outlet`: Pakistani or Bangladeshi publishers. Punjab, Hyderabad (Sindh) and Bengal exist on both sides of the border, and a spot check found that all 3 sampled Punjab rows were Pakistani Punjab.

Every rejected article is written to `dropped.csv` with all the reasons it failed.

## Normalisation

**States.** Each of the 36 regions has an alias list: official names, old names (Orissa, Bombay, Madras, Bangalore), hyphen and space variants, major cities and civic bodies (Bengaluru, Hyderabad, BMC, GHMC and others). Matching is on word boundaries. Two-letter abbreviations (UP, TN, MH, KA, AP, TS, WB, MP, HP) count only in uppercase, within three words of a government term, and not in all-caps headlines. "New Delhi" is not matched as Delhi because it is mostly a national dateline. A state mentioned only as someone's origin ("Bihar-born", "native of") does not count. The headline wins over the description; within either, the most-mentioned state wins.

If no state is found and exactly one region's searches returned the article, that region is assigned and `state_basis` is `query`. Articles that look national are not assigned this way.

**Dates.** Converted to Asia/Kolkata before taking the date. Month-only input would be kept as `YYYY-MM` with precision `month`; anything unparseable is `unknown`. No date is ever guessed. All 963 relevant articles have a day-precision date.

**URLs.** For NewsAPI, hosts are lowercased and `utm_*` and other tracking parameters and fragments are removed. Google News links are redirect tokens, so they are used as they are.

## Deduplication

Two levels.

1. **Articles.** The same article returned by several searches shares an `article_id` (a hash of its URL). It is kept once, with every region that returned it stored in `query_regions`.
2. **Events.** Relevant articles are clustered with union-find:
   - Exact: the same canonical URL, or the same normalised headline within a state.
   - Near: same state, dates within 3 days, `token_set_ratio` of at least 80 and `token_sort_ratio` of at least 45. If either date is unknown the set ratio must be at least 95.
   - Numbers guard: if both headlines contain digit numbers and the sets are disjoint, they are not merged. This keeps "AI training from Class 6" apart from "from Class 9". Amounts such as "₹1,150 crore" are normalised to 1150.

The representative article is chosen by: a `.gov.in` source, then a national outlet, then a headline-based state label over a description or query one, then the longest summary, then the earliest date. The event date is the earliest day-precision date in the cluster, and its category is the representative's unless a strict majority of the cluster disagrees.

**Calibration.** Thresholds were set by reading `dedup_calibration.csv`. Lowering the sort ratio floor from 60 to 45 merged 26 more pairs (13 fewer events) and the 10 lowest-scoring merged pairs showed no new false merges. Dropping number words from the guard changed 7 pair decisions. The 10 lowest-scoring merged pairs are listed in that file; a few (for example two Punjab police and IIT Ropar headlines) are judgement calls.

## State selection scorecard

Per region, `state_coverage.csv` records: events, distinct categories (statement and other do not count), distinct publishers, active months, multi-source events, query-basis events and the query-basis share.

| Tier | Rule |
|---|---|
| featured | at least 15 events, 4 categories, 6 publishers and 4 active months, and query-basis share of at most 0.40 |
| low_coverage | at least 3 events, but fails one or more featured thresholds |
| insufficient | fewer than 3 events |

The `reason` column names every failed threshold. The query-share limit exists so that the state label comes mainly from article text and not from which search returned the article. Thresholds are in `pipeline/config.py`.

## Results

From `data/processed/quality_report.json`.

**Funnel**

| Stage | Records |
|---|---|
| Raw records (5,246 Google News, 350 NewsAPI) | 5,596 |
| Unique articles | 4,120 |
| Passed AI check | 2,532 |
| State assigned | 2,480 |
| Government actor | 1,062 |
| Not excluded | 968 |
| In data window (relevant articles) | 963 |
| Events after dedup | 777 |

186 duplicate reports were collapsed. Most first-failure drops were `not_ai` (1,588) and `no_gov_actor` (1,241). 5 articles were dropped as `out_of_window`.

**Events by category:** other 214 (27.5%), deployment 179, policy_mission 110, partnership_mou 100, infrastructure 62, institution 34, budget_funding 34, statement 26, regulation_ethics 18.

**Tiers**

| Tier | States | Events |
|---|---|---|
| featured | 16 | 631 |
| low_coverage | 14 | 142 |
| insufficient | 6 | 4 |

Featured: Karnataka, Tamil Nadu, Uttar Pradesh, Telangana, Maharashtra, Kerala, Andhra Pradesh, Gujarat, Bihar, Odisha, Delhi, Goa, Haryana, Jharkhand, Punjab, West Bengal. Andaman and Nicobar Islands, Dadra and Nagar Haveli and Daman and Diu, and Lakshadweep have no events.

**Precision.** From a manual sample of 3 random events per featured state (48 events). Strict uses `manual_label` as given. Lenient also counts rows with `manual_note` set to `statement` as relevant, since a leader's statement is in scope but has no action.

| | Strict | Lenient |
|---|---|---|
| 48-event sample | 64.6% (31/48) | 75.0% (36/48) |
| 45 sampled events still in output after the cross-border fix | 68.9% (31/45) | 80.0% (36/45) |

The 3 Punjab rows in the sample were Pakistani Punjab stories and were removed by the cross-border fix. Punjab's remaining 22 events have not been re-sampled.

## Known gaps

- Google News descriptions are only a link to the headline, so most events have no real summary. The summary falls back to the headline.
- Event links are Google News redirects. The publisher's own URL is not stored. `data.json` carries one link per other outlet; the CSVs list outlet names only.
- Categories come from keyword rules. 27% of events are `other`, and some are misfiled (for example a "framework" document under regulation).
- Only English-language sources are searched.
- NewsAPI's free plan covers about 29 days, so the last month draws on a second source and the earlier months on Google News alone.
- Low coverage can mean little reporting, not little activity. Small states and UTs are most affected.
- Known false-positive types: company-led MoUs that do not name the state, central bodies (Railways, IITs, SECI) located in a state, commentary and interviews, and local events with an incidental AI mention.
- Precision is measured on 48 events. Per-state figures rest on 3 events each and are indicative only.

## Next steps

- Use an LLM to classify and summarise events, and benchmark it against the rules above and the labelled sample before replacing them.
- Resolve Google News links to publisher URLs.
- Add regional-language sources.
- Run on a schedule and fetch incrementally, keeping the cached raw data.
- Re-sample after any rule change and label a larger sample, including the low-coverage states.
