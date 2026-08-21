# Messaging Insights — Latest Run

Generated 2026-08-21T16:08:24 by `build_messaging_insights.py`. Reply rate is the outcome; open rate is shown but never used for a claim.

Scope: 15 cadences, 102 email steps with sends, 45 in the analysis pool. 22,094 sends, 557 replies, 467 bounces.

Floors: pool entry 100 sends/step, finding 500 sends and 3+ cadences per cell, rewrite advice 500 sends.


## Overall, by model

BDR and SDR are never pooled.


### BDR — 0.93% [0.78-1.12] n=12,555 rep=117

| Step band | Reply rate | Open (untrusted) | Bounce |
|---|---|---|---|
| early (1-2) | 1.23% [0.99-1.53] n=6,507 rep=80 | 31.4% | 4.9% |
| mid (3-6) | 0.61% [0.41-0.90] n=4,105 rep=25 | 33.9% | 0.6% |
| late (7+) | 0.62% [0.35-1.08] n=1,943 rep=12 | 31.3% | 0.5% |

**BDR feature findings** (survived band control and the 3-cadence rule)

| Band | Feature | Value | Rate | Cadences |
|---|---|---|---|---|
| early (1-2) | body_word_band | 60-79w | 1.90% [1.43-2.54] n=2,364 rep=45 | 5 |
| mid (3-6) | body_word_band | 40-59w | 1.21% [0.78-1.88] n=1,570 rep=19 | 5 |
| mid (3-6) | subject_word_band | 3-4w | 1.43% [0.89-2.28] n=1,190 rep=17 | 4 |
| mid (3-6) | subject_word_band | 1-2w | 0.27% [0.14-0.54] n=2,915 rep=8 | 3 |

**Do not generalise these BDR features** — they fail the cross-band consistency check:

- `body_word_band`: different values win in different bands (['40-59w', '60-79w']). No single direction holds across step positions.


Consistent across bands: `subject_word_band`


5 cell(s) suppressed as cadence-confounded (fewer than 3 cadences). These are NOT feature effects.


### SDR — 5.22% [4.75-5.73] n=7,988 rep=417

| Step band | Reply rate | Open (untrusted) | Bounce |
|---|---|---|---|
| early (1-2) | 6.57% [5.59-7.70] n=2,131 rep=140 | 45.9% | 2.0% |
| mid (3-6) | 6.68% [5.79-7.69] n=2,680 rep=179 | 38.3% | 1.7% |
| late (7+) | 3.08% [2.54-3.75] n=3,177 rep=98 | 35.0% | 0.4% |

**SDR feature findings** (survived band control and the 3-cadence rule)

| Band | Feature | Value | Rate | Cadences |
|---|---|---|---|---|
| late (7+) | body_word_band | <40w | 1.79% [1.16-2.75] n=1,115 rep=20 | 3 |

10 cell(s) suppressed as cadence-confounded (fewer than 3 cadences). These are NOT feature effects.


## Themes — what the emails are about

Theme labels are curated in `template_themes.json`.

**Read the per-band tables, not the pooled one.** Themes are not spread evenly across a cadence, so a pooled theme rate is mostly the step-position gradient. Any theme with 90%+ of its sends in one band is marked POSITION-LOCKED: its theme effect cannot be separated from its position, at any volume.


### BDR themes, controlled for step position


**early (1-2)** — band baseline 1.20% [0.96-1.50] n=6,257 rep=75

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| workflow_shift | 1.24% [0.99-1.55] n=6,051 rep=75 | +0.04pp | 6 | 6 | HYPOTHESIS |
| cost_of_inaction | 0.00% [0.00-1.83] n=206 rep=0 | -1.20pp | 1 | 1 | CONFOUNDED |

**mid (3-6)** — band baseline 0.61% [0.41-0.90] n=4,105 rep=25

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| peer_proof | 1.43% [0.89-2.28] n=1,190 rep=17 | +0.82pp | 4 | 4 | FINDING |
| cost_of_inaction | 0.53% [0.14-1.90] n=380 rep=2 | -0.08pp | 1 | 1 | CONFOUNDED |
| risk_trust | 0.24% [0.11-0.52] n=2,535 rep=6 | -0.37pp | 2 | 2 | CONFOUNDED |

**late (7+)** — band baseline 0.45% [0.22-0.93] n=1,542 rep=7

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| peer_proof | 0.66% [0.30-1.43] n=913 rep=6 | +0.20pp | 3 | 3 | HYPOTHESIS |
| cost_of_inaction | 0.23% [0.04-1.27] n=443 rep=1 | -0.23pp | 1 | 1 | CONFOUNDED |

<details><summary>BDR pooled across all steps (uncontrolled — kept only to show the distortion)</summary>

| Theme | Pooled rate | Band split (early/mid/late) | Status |
|---|---|---|---|
| workflow_shift | 1.24% n=6,051 | 100/0/0 | POSITION-LOCKED |
| peer_proof | 1.09% n=2,103 | 0/57/43 | HYPOTHESIS |
| cost_of_inaction | 0.29% n=1,029 | 20/37/43 | FINDING |
| risk_trust | 0.24% n=2,535 | 0/100/0 | POSITION-LOCKED |
| other | 0.00% n=186 | 0/0/100 | POSITION-LOCKED |

</details>


1 step(s) unlabeled (101 sends), excluded from theme analysis.


### SDR themes, controlled for step position


**early (1-2)** — band baseline 6.57% [5.59-7.70] n=2,131 rep=140

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| inbound_ack | 6.57% [5.59-7.70] n=2,131 rep=140 | +0.00pp | 4 | 4 | HYPOTHESIS |

**mid (3-6)** — band baseline 6.68% [5.79-7.69] n=2,680 rep=179

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| soft_close | 9.72% [6.81-13.69] n=288 rep=28 | +3.04pp | 1 | 1 | CONFOUNDED |
| inbound_ack | 8.56% [6.96-10.48] n=970 rep=83 | +1.88pp | 1 | 1 | CONFOUNDED |
| logistics_followup | 5.91% [4.56-7.63] n=914 rep=54 | -0.77pp | 3 | 3 | HYPOTHESIS |
| cost_of_inaction | 1.49% [0.64-3.45] n=335 rep=5 | -5.19pp | 1 | 1 | CONFOUNDED |

**late (7+)** — band baseline 3.19% [2.62-3.87] n=3,072 rep=98

| Theme | Reply rate | vs band | Steps | Cadences | Status |
|---|---|---|---|---|---|
| status_menu | 4.44% [3.19-6.14] n=766 rep=34 | +1.25pp | 2 | 2 | CONFOUNDED |
| logistics_followup | 3.08% [1.91-4.95] n=519 rep=16 | -0.11pp | 1 | 1 | CONFOUNDED |
| soft_close | 2.93% [1.93-4.44] n=716 rep=21 | -0.26pp | 4 | 3 | HYPOTHESIS |
| check_in | 2.79% [1.91-4.06] n=932 rep=26 | -0.40pp | 2 | 1 | CONFOUNDED |

<details><summary>SDR pooled across all steps (uncontrolled — kept only to show the distortion)</summary>

| Theme | Pooled rate | Band split (early/mid/late) | Status |
|---|---|---|---|
| inbound_ack | 7.19% n=3,101 | 69/31/0 | FINDING |
| logistics_followup | 4.88% n=1,433 | 0/64/36 | HYPOTHESIS |
| soft_close | 4.88% n=1,004 | 0/29/71 | HYPOTHESIS |
| status_menu | 4.58% n=939 | 0/18/82 | HYPOTHESIS |
| check_in | 2.79% n=932 | 0/0/100 | POSITION-LOCKED |
| cost_of_inaction | 1.27% n=474 | 0/71/29 | CONFOUNDED |

</details>


### Templates needing a theme label

Add these to `template_themes.json` so they enter the theme analysis.

| Template ID | Sends | Replies | Subject |
|---|---|---|---|
| 359457937 | 101 | 1 | `Firms your size` |

## By segment

| Segment | Reply rate | Steps | Cadences | Reportable |
|---|---|---|---|---|
| BDR-Velocity | 0.67% [0.52-0.86] n=8,952 rep=60 | 10 | 4 | full |
| SDR | 5.22% [4.75-5.73] n=7,988 rep=417 | 22 | 5 | full |
| BDR-Strategic | 1.58% [1.22-2.04] n=3,603 rep=57 | 13 | 4 | full |

### BDR-Velocity

| Step band | Reply rate |
|---|---|
| early (1-2) | 0.97% [0.73-1.29] n=4,752 rep=46 |
| mid (3-6) | 0.27% [0.14-0.54] n=2,915 rep=8 |
| late (7+) | 0.47% [0.21-1.01] n=1,285 rep=6 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| your practice | 0.95% [0.70-1.29] n=4,296 rep=41 | 2 |
| passed on it | 0.76% [0.33-1.77] n=656 rep=5 | 1 |
| document review | 0.53% [0.14-1.90] n=380 rep=2 | 1 |
| client confidentiality | 0.24% [0.11-0.52] n=2,535 rep=6 | 2 |
| quick question | 0.23% [0.04-1.27] n=443 rep=1 | 1 |

### SDR

| Step band | Reply rate |
|---|---|
| early (1-2) | 6.57% [5.59-7.70] n=2,131 rep=140 |
| mid (3-6) | 6.68% [5.79-7.69] n=2,680 rep=179 |
| late (7+) | 3.08% [2.54-3.75] n=3,177 rep=98 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| your demo request | 10.80% [8.00-14.43] n=361 rep=39 | 1 |
| your clio demonstration | 8.56% [6.96-10.48] n=970 rep=83 | 1 |
| thanks for putting up with me | 7.11% [5.39-9.33] n=661 rep=47 | 3 |
| re: your demo | 6.38% [4.89-8.29] n=799 rep=51 | 2 |
| the full picture | 6.00% [4.21-8.49] n=483 rep=29 | 1 |
| your clio trial | 5.35% [4.18-6.83] n=1,121 rep=60 | 1 |

### BDR-Strategic

| Step band | Reply rate |
|---|---|
| early (1-2) | 1.94% [1.39-2.69] n=1,755 rep=34 |
| mid (3-6) | 1.43% [0.89-2.28] n=1,190 rep=17 |
| late (7+) | 0.91% [0.42-1.98] n=658 rep=6 |

Top subject lines (300+ sends)

| Subject | Rate | Cadences |
|---|---|---|
| what's changing | 2.23% [1.18-4.19] n=403 rep=9 | 1 |
| quick note | 1.52% [0.95-2.43] n=1,115 rep=17 | 2 |
| firms your size | 1.43% [0.89-2.28] n=1,190 rep=17 | 4 |

## Defects — copy that reached prospects as something other than a message

11 steps, 890 sends. No volume floor applies: these are bugs.

Valid merge fields such as `{{first_name}}` are excluded, since they render at send time. Flagged here are human-typed placeholders that never got filled in, rep-facing instructions, and empty subjects.

| Sends | Replies | Subject as sent | Defect | Cadence |
|---|---|---|---|---|
| 250 | 5 | `*Insert their practice area as subject* (Exs` | rep instruction as subject | BDR - Velocity - Outbound - en-US - CN |
| 175 | 4 | `Depositions, in minutes` | rep instruction in body | BDR - Strategic - AQLs Excl Draft  - e |
| 125 | 0 | `Depositions, in minutes` | rep instruction in body | BDR - Strategic - WebSights INTENT - e |
| 105 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - MANAGE TRIAL - en-US - CNV - TRI |
| 101 | 1 | `Firms your size` | rep instruction in body | BDR - Strategic - NMQL - en-US - CNV |
| 87 | 0 | `Depositions, in minutes` | rep instruction in body | BDR - Strategic - OB - CL INTENT - en- |
| 20 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - DEMO-REQ - en-US - CNV - PREDEMO |
| 16 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - WEB-PRICING-en-US-CNV |
| 5 | 0 | `{{account_name_or_company}}` | rep instruction in body | SDR - Software Advice -en-US-CNV |
| 4 | 0 | `Firms your size` | rep instruction in body | BDR - Strategic - OB - NMQL INTENT - e |
| 2 | 0 | `` | empty subject | SDR - DEMO-REQ - en-US - CNV - PREDEMO |

## Rewrite queue

Ranked defects first, then by sends x gap to the band baseline.

| # | Cadence | Step | Subject | Rate | vs band | n | Why |
|---|---|---|---|---|---|---|---|
| 1 | BDR - Velocity - AQL / NMQL -  | 2 | `Your practice` | 0.81% | 1.22% | 3,687 | clearly below its band |
| 2 | SDR - MANAGE TRIAL - en-US - C | 2: A | `Your Clio trial` | 5.35% | 6.57% | 1,121 | below its band, but the interval overlaps |
| 3 | BDR - Velocity - AQL / NMQL -  | 4 | `Client confidentiality` | 0.25% | 0.59% | 2,374 | clearly below its band |
| 4 | SDR - DEMO-REQ - en-US - CNV - | 6 | `RE: your demo` | 5.78% | 6.53% | 536 | below its band, but the interval overlaps |
| 5 | BDR - Velocity - AQL / NMQL -  | 9 | `Passed on it` | 0.76% | 0.81% | 656 | below its band, but the interval overlaps |
