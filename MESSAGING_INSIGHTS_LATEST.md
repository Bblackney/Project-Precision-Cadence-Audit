# Messaging Insights — Latest Run

Generated 2026-09-02T15:43:56 by `build_messaging_insights.py`. Reply rate is the outcome; open rate is shown but never used for a claim.

Scope: 14 cadences, 119 email steps with sends, 56 in the analysis pool. 31,638 sends, 758 replies, 656 bounces.

Floors: pool entry 100 sends/step, finding 500 sends and 3+ cadences per cell, rewrite advice 500 sends.


## Overall, by model

BDR and SDR are never pooled.


### BDR — 0.82% [0.70-0.96] n=18,355 rep=150

| Step band | Reply rate | Open (untrusted) | Bounce |
|---|---|---|---|
| early (1-2) | 1.18% [0.97-1.44] n=8,296 rep=98 | 30.7% | 5.1% |
| mid (3-6) | 0.58% [0.41-0.80] n=5,907 rep=34 | 33.4% | 0.8% |
| late (7+) | 0.43% [0.27-0.68] n=4,152 rep=18 | 31.4% | 0.5% |

**BDR feature findings** (survived band control and the 3-cadence rule)

| Band | Feature | Value | Rate | Cadences |
|---|---|---|---|---|
| early (1-2) | body_word_band | 60-79w | 1.80% [1.35-2.41] n=2,438 rep=44 | 4 |
| mid (3-6) | body_word_band | 40-59w | 1.28% [0.84-1.95] n=1,644 rep=21 | 4 |
| mid (3-6) | body_word_band | 60-79w | 0.30% [0.18-0.52] n=4,263 rep=13 | 3 |
| mid (3-6) | subject_word_band | 3-4w | 1.76% [1.13-2.74] n=1,077 rep=19 | 3 |
| mid (3-6) | subject_word_band | 1-2w | 0.31% [0.19-0.51] n=4,830 rep=15 | 4 |

**Do not generalise these BDR features** — they fail the cross-band consistency check:

- `body_word_band`: value(s) ['60-79w'] are above baseline in one band and below in another. Do not generalise; these cells reflect specific steps, not the feature.


Consistent across bands: `subject_word_band`


4 cell(s) suppressed as cadence-confounded (fewer than 3 cadences). These are NOT feature effects.


### SDR — 4.95% [4.57-5.36] n=11,724 rep=580

| Step band | Reply rate | Open (untrusted) | Bounce |
|---|---|---|---|
| early (1-2) | 6.41% [5.55-7.40] n=2,699 rep=173 | 46.3% | 2.4% |
| mid (3-6) | 6.55% [5.79-7.40] n=3,648 rep=239 | 38.6% | 1.9% |
| late (7+) | 3.12% [2.69-3.62] n=5,377 rep=168 | 34.3% | 0.4% |

**SDR feature findings** (survived band control and the 3-cadence rule)

| Band | Feature | Value | Rate | Cadences |
|---|---|---|---|---|
| late (7+) | body_word_band | 40-59w | 4.21% [3.38-5.22] n=1,855 rep=78 | 4 |
| late (7+) | body_word_band | <40w | 1.84% [1.30-2.58] n=1,741 rep=32 | 3 |
| late (7+) | subject_word_band | 5w+ | 7.02% [5.41-9.07] n=755 rep=53 | 3 |
| late (7+) | subject_word_band | 1-2w | 0.73% [0.34-1.59] n=819 rep=6 | 3 |

Consistent across bands: `body_word_band`, `subject_word_band`


7 cell(s) suppressed as cadence-confounded (fewer than 3 cadences). These are NOT feature effects.


## Themes — what the emails are about

Theme labels are curated in `template_themes.json`.

**Read the per-band tables, not the pooled one.** Themes are not spread evenly across a cadence, so a pooled theme rate is mostly the step-position gradient. Any theme with 90%+ of its sends in one band is marked POSITION-LOCKED: its theme effect cannot be separated from its position, at any volume.


### BDR themes, controlled for step position


**early (1-2)** — band baseline 1.17% [0.95-1.43] n=7,868 rep=92

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| workflow_shift | 1.20% [0.98-1.47] n=7,578 rep=91 | +0.03pp | 5 | 5 | HYPOTHESIS |
| cost_of_inaction | 0.34% [0.06-1.93] n=290 rep=1 | -0.82pp | 1 | 1 | CONFOUNDED |

**mid (3-6)** — band baseline 0.59% [0.42-0.83] n=5,737 rep=34

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| peer_proof | 1.76% [1.13-2.74] n=1,077 rep=19 | +1.17pp | 3 | 3 | FINDING |
| cost_of_inaction | 0.35% [0.10-1.28] n=567 rep=2 | -0.24pp | 1 | 1 | CONFOUNDED |
| risk_trust | 0.32% [0.19-0.54] n=4,093 rep=13 | -0.28pp | 2 | 2 | CONFOUNDED |

**late (7+)** — band baseline 0.44% [0.26-0.75] n=2,961 rep=13

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| peer_proof | 0.59% [0.31-1.12] n=1,524 rep=9 | +0.15pp | 2 | 2 | CONFOUNDED |
| cost_of_inaction | 0.33% [0.11-0.96] n=915 rep=3 | -0.11pp | 1 | 1 | CONFOUNDED |
| other | 0.19% [0.03-1.08] n=522 rep=1 | -0.25pp | 1 | 1 | CONFOUNDED |

<details><summary>BDR pooled across all steps (uncontrolled — kept only to show the distortion)</summary>

| Theme | Pooled rate | Band split (early/mid/late) | Status |
|---|---|---|---|
| workflow_shift | 1.20% n=7,578 | 100/0/0 | POSITION-LOCKED |
| peer_proof | 1.08% n=2,601 | 0/41/59 | HYPOTHESIS |
| cost_of_inaction | 0.34% n=1,772 | 16/32/52 | FINDING |
| risk_trust | 0.32% n=4,093 | 0/100/0 | POSITION-LOCKED |
| other | 0.19% n=522 | 0/0/100 | POSITION-LOCKED |

</details>


10 step(s) unlabeled (1,291 sends), excluded from theme analysis.


### SDR themes, controlled for step position


**early (1-2)** — band baseline 6.41% [5.55-7.40] n=2,699 rep=173

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| inbound_ack | 6.41% [5.55-7.40] n=2,699 rep=173 | +0.00pp | 4 | 4 | HYPOTHESIS |

**mid (3-6)** — band baseline 6.74% [5.96-7.62] n=3,517 rep=237

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| soft_close | 9.16% [6.69-12.42] n=393 rep=36 | +2.42pp | 1 | 1 | CONFOUNDED |
| inbound_ack | 8.32% [6.93-9.96] n=1,274 rep=106 | +1.58pp | 1 | 1 | CONFOUNDED |
| status_menu | 6.28% [3.84-10.10] n=239 rep=15 | -0.46pp | 1 | 1 | CONFOUNDED |
| logistics_followup | 6.08% [4.84-7.61] n=1,151 rep=70 | -0.66pp | 3 | 3 | HYPOTHESIS |
| cost_of_inaction | 2.17% [1.19-3.96] n=460 rep=10 | -4.57pp | 1 | 1 | CONFOUNDED |

**late (7+)** — band baseline 3.20% [2.73-3.75] n=4,593 rep=147

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| status_menu | 4.10% [3.07-5.46] n=1,072 rep=44 | +0.90pp | 2 | 2 | CONFOUNDED |
| soft_close | 3.58% [2.64-4.84] n=1,117 rep=40 | +0.38pp | 4 | 3 | HYPOTHESIS |
| logistics_followup | 3.40% [2.30-5.01] n=705 rep=24 | +0.20pp | 1 | 1 | CONFOUNDED |
| check_in | 2.93% [2.14-4.00] n=1,296 rep=38 | -0.27pp | 2 | 1 | CONFOUNDED |
| cost_of_inaction | 0.25% [0.04-1.39] n=403 rep=1 | -2.95pp | 2 | 2 | CONFOUNDED |

<details><summary>SDR pooled across all steps (uncontrolled — kept only to show the distortion)</summary>

| Theme | Pooled rate | Band split (early/mid/late) | Status |
|---|---|---|---|
| inbound_ack | 7.02% n=3,973 | 68/32/0 | FINDING |
| logistics_followup | 5.07% n=1,856 | 0/62/38 | HYPOTHESIS |
| soft_close | 5.03% n=1,510 | 0/26/74 | HYPOTHESIS |
| status_menu | 4.50% n=1,311 | 0/18/82 | HYPOTHESIS |
| check_in | 2.93% n=1,296 | 0/0/100 | POSITION-LOCKED |
| cost_of_inaction | 1.27% n=863 | 0/53/47 | CONFOUNDED |

</details>


5 step(s) unlabeled (721 sends), excluded from theme analysis.


### Templates needing a theme label

Add these to `template_themes.json` so they enter the theme analysis.

| Template ID | Sends | Replies | Subject |
|---|---|---|---|
| 361335527 | 186 | 0 | `Stepping back` |
| 359188237 | 170 | 2 | `Where you fit` |
| 361363353 | 170 | 0 | `Page 200` |
| 361339261 | 166 | 2 | `Feedback` |
| 359162396 | 157 | 0 | `Where you fit` |
| 359379025 | 156 | 16 | `Thanks for putting up with me` |
| 359457937 | 132 | 1 | `Firms your size` |
| 359418607 | 131 | 2 | `Where you fit` |
| 359918741 | 110 | 1 | `Depositions, in minutes` |
| 374633304 | 109 | 0 | `Your practice` |
| 359408873 | 107 | 3 | `No rush` |
| 361340462 | 106 | 1 | `Matter review` |
| 359432436 | 105 | 0 | `The 20-minute deal` |
| 359460326 | 105 | 0 | `Growing without hiring` |
| 361349909 | 102 | 0 | `Feedback` |

## By segment

| Segment | Reply rate | Steps | Cadences | Reportable |
|---|---|---|---|---|
| BDR-Velocity | 0.65% [0.53-0.79] n=14,845 rep=96 | 16 | 4 | full |
| SDR | 4.95% [4.57-5.36] n=11,724 rep=580 | 28 | 5 | full |
| BDR-Strategic | 1.54% [1.18-2.00] n=3,510 rep=54 | 12 | 3 | full |

### BDR-Velocity

| Step band | Reply rate |
|---|---|
| early (1-2) | 0.98% [0.77-1.25] n=6,711 rep=66 |
| mid (3-6) | 0.31% [0.19-0.51] n=4,830 rep=15 |
| late (7+) | 0.45% [0.28-0.75] n=3,304 rep=15 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| your practice | 0.97% [0.75-1.25] n=6,102 rep=59 | 2 |
| passed on it | 0.61% [0.31-1.20] n=1,307 rep=8 | 1 |
| document review | 0.35% [0.10-1.28] n=567 rep=2 | 1 |
| quick question | 0.33% [0.11-0.96] n=915 rep=3 | 1 |
| client confidentiality | 0.32% [0.19-0.54] n=4,093 rep=13 | 2 |
| free cle | 0.19% [0.03-1.08] n=522 rep=1 | 1 |

### SDR

| Step band | Reply rate |
|---|---|
| early (1-2) | 6.41% [5.55-7.40] n=2,699 rep=173 |
| mid (3-6) | 6.55% [5.79-7.40] n=3,648 rep=239 |
| late (7+) | 3.12% [2.69-3.62] n=5,377 rep=168 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| your demo request | 10.54% [7.81-14.09] n=370 rep=39 | 1 |
| your clio demonstration | 8.32% [6.93-9.96] n=1,274 rep=106 | 1 |
| thanks for putting up with me | 7.75% [6.34-9.44] n=1,148 rep=89 | 4 |
| re: your demo | 6.26% [4.91-7.94] n=991 rep=62 | 2 |
| the full picture | 5.92% [4.36-7.99] n=659 rep=39 | 1 |
| your clio trial | 5.52% [4.46-6.82] n=1,449 rep=80 | 1 |

### BDR-Strategic

| Step band | Reply rate |
|---|---|
| early (1-2) | 2.02% [1.43-2.84] n=1,585 rep=32 |
| mid (3-6) | 1.76% [1.13-2.74] n=1,077 rep=19 |
| late (7+) | 0.35% [0.12-1.03] n=848 rep=3 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| what's changing | 1.95% [1.12-3.38] n=615 rep=12 | 1 |
| firms your size | 1.76% [1.13-2.74] n=1,077 rep=19 | 3 |
| quick note | 1.61% [0.90-2.86] n=684 rep=11 | 1 |
| the 20-minute deal | 0.31% [0.06-1.74] n=322 rep=1 | 2 |

## Defects — copy that reached prospects as something other than a message

12 steps, 1,124 sends. No volume floor applies: these are bugs.

Valid merge fields such as `{{first_name}}` are excluded, since they render at send time. Flagged here are human-typed placeholders that never got filled in, rep-facing instructions, and empty subjects.

| Sends | Replies | Subject as sent | Defect | Cadence |
|---|---|---|---|---|
| 319 | 6 | `*Insert their practice area as subject* (Exs` | rep instruction as subject | BDR - Velocity - Outbound - en-US - CN |
| 194 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - MANAGE TRIAL - en-US - CNV - TRI |
| 179 | 0 | `Depositions, in minutes` | rep instruction in body | BDR - Strategic - WebSights INTENT - e |
| 132 | 1 | `Firms your size` | rep instruction in body | BDR - Strategic - NMQL - en-US - CNV |
| 110 | 1 | `Depositions, in minutes` | rep instruction in body | BDR - Strategic - OB - CL INTENT - en- |
| 91 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - DEMO-REQ - en-US - CNV - PREDEMO |
| 54 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - WEB-PRICING-en-US-CNV |
| 20 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - Software Advice -en-US-CNV |
| 11 | 0 | `*Insert their practice area as subject* (Exs` | rep instruction as subject | BDR - Velocity - Outbound - en-US - CN |
| 8 | 0 | `Firms your size` | rep instruction in body | BDR - Strategic - OB - NMQL INTENT - e |
| 3 | 0 | `` | empty subject | SDR - DEMO-REQ - en-US - CNV - PREDEMO |
| 3 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - DEMO-REQ-WEBINAR - en-US - CNV - |

## Rewrite queue

Ranked defects first, then by sends x gap to the band baseline.

| # | Cadence | Step | Subject | Rate | vs band | n | Why |
|---|---|---|---|---|---|---|---|
| 1 | BDR - Velocity - AQL / NMQL -  | 2 | `Your practice` | 0.91% | 1.17% | 5,140 | below its band, but the interval overlaps |
| 2 | SDR - MANAGE TRIAL - en-US - C | 2: A | `Your Clio trial` | 5.52% | 6.41% | 1,449 | below its band, but the interval overlaps |
| 3 | BDR - Velocity - AQL / NMQL -  | 4 | `Client confidentiality` | 0.35% | 0.57% | 3,760 | below its band, but the interval overlaps |
| 4 | SDR - DEMO-REQ - en-US - CNV - | 6 | `RE: your demo` | 5.40% | 6.55% | 704 | below its band, but the interval overlaps |
| 5 | SDR - WEB-PRICING-en-US-CNV | 2 | `The full picture` | 5.92% | 6.41% | 659 | below its band, but the interval overlaps |
| 6 | BDR - Velocity - AQL / NMQL -  | 11 | `Quick question` | 0.33% | 0.52% | 915 | below its band, but the interval overlaps |
| 7 | BDR - Velocity - AQL / NMQL -  | 13 | `Free CLE` | 0.19% | 0.52% | 522 | below its band, but the interval overlaps |
| 8 | BDR - Velocity - Closed Lost A | 4 | `Document review` | 0.35% | 0.57% | 567 | below its band, but the interval overlaps |
