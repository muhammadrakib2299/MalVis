# Writing a research paper based on MalVis

A working document — return to it as the paper takes shape.

## 0. Should you write a paper at all?

Yes, but be honest about what kind. For a German DS Master's application (Aug 2026 deadline, today is 2026-05-05 ≈ 3 months out), the realistic targets are:

| Outcome | Time-to-evidence | Application value |
|---|---|---|
| **arXiv preprint** | 2–4 weeks of focused work | "submitted, under review" evidence — strong |
| **Workshop paper** (AISec, DLS, CAMLIS) | 8–12 weeks incl. peer review | Stronger; many summer/autumn deadlines |
| **Open-access journal** (IEEE Access, Computers & Security) | 3–6 months review cycle | Submitted-but-unreviewed is fine for the application |
| **Top-tier conference** (CCS, S&P, USENIX Security) | 6+ months, multiple rounds, ~80% reject rate | Don't aim here for a first paper |

**The honest plan:** target an arXiv preprint by July 2026 + simultaneously submit to a workshop or open-access journal. The application can cite "preprint at arXiv:XXXX, under review at YYY" — that's a credible signal even if acceptance lands after applications close.

---

## 1. Paper-angle options

Five candidates, ranked by fit-to-MalVis. Each has: title, 2-line pitch, what's novel, dataset, suggested venue, effort.

### Option A (recommended) — Adversarial robustness of SHAP explanations

> **"How Stable Are SHAP Explanations for Malware Classifiers? An Adversarial Perturbation Study"**

- **Pitch.** SHAP is the dominant explainability tool for tree-based malware detectors. But are its attributions *stable* — would a small adversarial change to the input flip the *explanation* without flipping the *prediction*? If yes, "explainable malware detection" is more fragile than the literature claims.
- **Novelty.** SHAP-for-malware is well-studied; SHAP-*under-attack* is much less so. The MalVis perturbation simulator generates the experimental data directly: for each input, sweep N single-feature perturbations bounded by ε, measure (a) prediction-flip rate and (b) top-N feature-rank Spearman correlation between baseline and perturbed explanations.
- **Dataset.** EMBER 2018 features (1.1M samples, pre-extracted features). Or a smaller curated subset (10–30k) for a workshop-scope paper.
- **Venue.** AISec (co-located with CCS, summer/autumn submission), DLS (co-located with IEEE S&P, winter), CAMLIS (rolling), or arXiv + IEEE Access journal.
- **Effort.** ~6–8 weeks. Feasible.

### Option B — Disagreement mining

> **"Disagreement as Signal: Using Multi-Model Inconsistency to Triage Malware Verdicts"**

- **Pitch.** When RF and XGBoost (or any pair of independent classifiers) disagree on a sample, that disagreement is itself information — it correlates with packed binaries, novel families, and adversarial inputs. We propose surfacing disagreement as a first-class triage signal and measure its hit rate against a labelled out-of-distribution test set.
- **Novelty.** Ensemble methods *average* models; this paper argues that *raw disagreement* (the variance, not the mean) is the actionable signal. Most ensemble literature optimizes accuracy; this optimizes *triage prioritization*.
- **Dataset.** EMBER 2018 + a held-out OOD set (BODMAS, or labels-flipped EMBER samples).
- **Venue.** AISec, RAID workshop track, or Journal of Computer Virology and Hacking Techniques.
- **Effort.** ~4–6 weeks. Smaller than A.

### Option C — Header-only feature comparison

> **"Header-Only PE Feature Sets for Malware Detection: A Cross-Schema Comparative Study"**

- **Pitch.** Different header-only feature sets (the paper's, EMBER's, BODMAS's) claim similar detection capacity. We unify them under a common evaluation harness and report per-schema F1, training cost, adversarial susceptibility, and explainability quality.
- **Novelty.** Schema-A-vs-schema-B comparisons exist but rarely include adversarial+explainability axes. The MalVis pipeline (extract → train → SHAP → perturb) is the harness.
- **Dataset.** EMBER 2018, BODMAS, plus the MalVis schema as a third arm.
- **Venue.** Computers & Security journal, IEEE Access, ESORICS workshop.
- **Effort.** ~10–14 weeks. Bigger because three schemas means three pipelines.

### Option D — Reproducibility / system paper

> **"Schema-Version-Pinned Pipelines for Reproducible Malware Detection: Lessons from MalVis"**

- **Pitch.** ML reproducibility is a known crisis. We document a pattern — feature-schema-as-contract, SHA-pinned model loading, manifest-driven training — that turns "this model works" into "this exact pipeline produces this exact prediction" across deploys.
- **Novelty.** Reproducibility patterns are written about generally; malware-detection-specific patterns less so. The contribution is methodological, not empirical.
- **Dataset.** Whatever you used elsewhere — this paper isn't about the data, it's about the contract.
- **Venue.** Empirical Software Engineering, Journal of Open Source Software, or a workshop like SecDev.
- **Effort.** ~3–5 weeks. Shortest.

### Option E — System-demo paper

> **"MalVis: An Interactive Dashboard for Explainable Malware Detection"**

- **Pitch.** The dashboard itself as the contribution. Demo paper — "here's the system, here's what it does, here's why it matters."
- **Novelty.** Lowest. System papers are accepted on novelty of *integration*, not novelty of components.
- **Dataset.** N/A.
- **Venue.** ACM CCS demo track, IEEE S&P demo track (very competitive), RAID demos, conference *poster* tracks, ACSAC posters.
- **Effort.** ~2–3 weeks. Quickest.

### My recommendation: **Option A**, with **D** as a co-submitted short companion if time allows.

A is the highest-leverage paper that's still feasible in 8 weeks. The MalVis perturbation simulator is *exactly* the experimental apparatus the paper needs. Option D is a 5-page methods note that can ride alongside.

---

## 2. Step-by-step process: idea → publication

### Step 1 — Literature review (Week 1–2)

Goal: understand what's been done, what hasn't, and where your contribution fits.

**Tools:**
- **Google Scholar** (`scholar.google.com`) — broad coverage, citation counts
- **Semantic Scholar** (`semanticscholar.org`) — AI-assisted search, "influential citations" filter
- **arXiv** (`arxiv.org/list/cs.CR/recent`) — preprints, fastest signal
- **DBLP** (`dblp.org`) — venue-by-venue computer science bibliography
- **Connected Papers** (`connectedpapers.com`) — visual graph of related work

**Search terms (paper A):**

```
"SHAP" "malware detection"
"explainability" "robustness" "adversarial"
"feature attribution" "stability"
"PE" "static analysis" "explanation"
"tree explainer" "perturbation" "robustness"
```

For each search, set a date filter for **last 5 years** (most ML-explainability work post-dates 2018). Read the title + abstract of the top 30, save the 10 that are clearly relevant.

**Reading pattern:**
1. **Pass 1 (skim).** Title, abstract, figures, conclusion. ~5 min/paper. Decide: relevant / not / unclear.
2. **Pass 2 (read).** Intro + related work + experiment setup of the relevant ones. ~30 min/paper. Build a one-paragraph summary.
3. **Pass 3 (depth).** Methods + results of the 3–5 most-cited / most-relevant. ~2 hours/paper. These are the ones you'll cite + compare against.

**Capture tool:** [Zotero](https://www.zotero.org/) — free, syncs across devices, BibTeX export. Tag every paper by topic; one-line note in the "Abstract" field summarizing your take.

### Step 2 — Find the gap (Week 2)

The "gap" is what makes a paper worth publishing — what does the literature *not* answer that yours does?

**Where gaps hide:**

- **Future-work sections.** Authors often list things they didn't do. Read these last — many become someone else's paper.
- **Limitations sections.** Stated weaknesses are *exactly* the kind of thing a follow-up paper closes.
- **Survey papers.** A 2023–2024 survey on "explainable malware detection" will list open problems explicitly. Find the most-recent survey first; it does a lot of the gap-identification work for you.
- **Workshop CFPs.** Many CFPs list "topics of interest" that are basically a list of underexplored areas. AISec, DLS, CAMLIS CFPs are gold mines.
- **Reviewer rejections.** Paper acceptance forums sometimes publish reviewer comments — those name specific weaknesses.

**For Option A specifically, the gap is roughly:**

> Most SHAP-for-malware papers measure detection accuracy and ignore explanation stability. The few that *do* study stability use synthetic perturbations bounded in pixel space (image classifiers), not feature-vector adversarial budgets relevant to PE files. There is no published study of feature-rank correlation under bounded adversarial perturbation for tree-based PE classifiers.

Verify this gap by reading 3–5 closely-related recent papers (2022–2024). If someone's already done it, pivot to a sub-gap (specific feature subsets, specific attack budgets, etc.).

### Step 3 — Refine the contribution (Week 2)

Write down the paper's **one-sentence claim** before any experiments. This is the answer to: "what would I say in a 30-second elevator pitch?"

For Option A:
> *"Bounded adversarial perturbations on PE feature vectors can preserve a malicious verdict while drastically rearranging which features SHAP attributes the verdict to — undermining the operational use of SHAP-based explanations in malware triage."*

Test the claim by asking:
- **Falsifiable?** Yes — experiments could show stable explanations.
- **Specific?** Yes — names the model class (tree, via SHAP), the perturbation budget (bounded), and the failure mode (rank rearrangement).
- **Surprising-if-true?** Yes — the explainability literature largely treats SHAP as ground truth.

If the answer to any of the three is "no", refine until they're "yes".

### Step 4 — Dataset acquisition (Week 2–3)

| Dataset | Size | License | What you get |
|---|---|---|---|
| **[EMBER 2018](https://github.com/elastic/ember)** | 1.1M PE samples | Apache 2.0 | Pre-extracted 2381-dim feature vectors + labels. **Recommended starting point.** |
| **[BODMAS](https://whyisyoung.github.io/BODMAS/)** | 134k PE samples | Research-only (request form) | Pre-extracted features + family labels — useful for OOD validation. |
| **[SOREL-20M](https://github.com/sophos-ai/SOREL-20M)** | 20M samples | Apache 2.0 | Largest open PE dataset; features only, no binaries. |
| **[MalwareBazaar](https://bazaar.abuse.ch/)** | ~1M+ binaries | Free; for security researchers | **Raw binaries** — needed if your paper extracts custom features. Authentication required. |
| **[VirusShare](https://virusshare.com/)** | tens of millions | Vetted-researcher access | Raw binaries; longer onboarding. |

**Practical recipe for Option A:**
1. Download EMBER 2018 (~9.5 GB) — already feature-extracted, saves you the most painful step.
2. Train RF + XGBoost on EMBER's training split. Sanity-check against the published EMBER baselines (F1 ≈ 0.97).
3. Use the MalVis perturbation logic to generate ε-bounded perturbations on the *feature vectors* — no binaries needed for this paper.
4. Optional: BODMAS as an out-of-distribution test set in §5 of the paper.

**License gotchas:**
- EMBER is Apache 2.0 — fine to redistribute features and trained models with attribution.
- BODMAS is gated behind a research-use form. You can publish *results* but not redistribute the dataset.
- MalwareBazaar binaries: *never* commit binaries to git, ever. Reference by SHA-256 only.
- VirusTotal API: free tier exists for researchers but rate-limited. Don't depend on it for reproducibility.

### Step 5 — Experimental design (Week 3)

Write the **experiment section** of the paper *before* running experiments. This catches design flaws cheaply.

Sections to plan in advance:
- **Models trained.** Which? On what split? What hyperparameters? (Pin them.)
- **Perturbation budgets.** What ε values? How many features per perturbation?
- **Metrics.** Prediction-flip rate. Top-N feature rank Spearman correlation. Wall-clock cost.
- **Baseline comparisons.** Random perturbations vs. adversarial. Single-feature vs. multi-feature.
- **Failure-case curation.** What happens when SHAP says feature X drives the verdict but feature Y is the actual flip? Document, don't hide.

Pre-register the experiment plan in a Markdown file *before* running it. After running, anything you'd change retrospectively is a red flag — either a paper finding or a paper limitation.

### Step 6 — Implementation (Week 3–5)

Reuse MalVis where you can:
- `app/services/pe_features.py::FEATURE_VECTOR_ORDER` — the feature schema.
- `app/services/perturb.py::apply_perturbations` — already implements set/delta/scale/toggle.
- `training/train.py` — replace `_build_synthetic_dataset` with an EMBER loader. The rest of the pipeline (model_registry-compatible artifacts + manifest) is reusable.
- `app/services/explain.py` — `_explain_real` + `shap.TreeExplainer` is your SHAP path.

What's *new* code:
- An EMBER loader that yields `(X, y)` matching `FEATURE_VECTOR_ORDER` (or augment `FEATURE_VECTOR_ORDER` to include EMBER's richer schema — bump the schema version).
- A perturbation-search loop that enumerates ε-bounded budgets and records (baseline-prediction, perturbed-prediction, baseline-SHAP, perturbed-SHAP).
- Analysis notebooks: rank correlation plots, perturbation-budget vs. flip-rate curves, per-feature attribution-shift histograms.

**Reproducibility guardrails:**
- Pin random seeds.
- Pin all dependency versions (you already do this).
- Commit the trained artifacts' SHA-256 in the paper's appendix.
- Publish a Zenodo or Hugging Face record of the trained artifacts so reviewers can re-run.

### Step 7 — Writing the draft (Week 5–7)

**Section structure (workshop scope, ~10 pages):**

1. **Abstract** (~150 words). One sentence per IMRAD layer: motivation, method, result, implication.
2. **Introduction** (~1.5 pages). The *story*: SHAP is widely used for malware explainability → if SHAP is unstable under attack, "explainable" is misleading → we measure stability empirically → here's what we found.
3. **Background** (~1 page). PE features, RF, XGBoost, SHAP/TreeExplainer. Brief.
4. **Related work** (~1 page). 5–10 most relevant papers, organized by sub-topic (SHAP for security, adversarial ML on tree models, explanation stability).
5. **Threat model and method** (~2 pages). Adversary capability (feature-vector access, bounded budget). Perturbation algorithm. Metrics.
6. **Experiments** (~3 pages). Setup, results, ablations.
7. **Discussion** (~1 page). What this means for ops use of SHAP, limitations, future work.
8. **Conclusion** (~0.25 page).

**Tools:**
- **Overleaf** ([overleaf.com](https://overleaf.com)). Browser-based LaTeX, free for solo work, has every venue's template.
- **Templates:** ACM `acmart.cls`, IEEE `IEEEtran.cls`, Springer `llncs.cls` — pick the one your venue requires.
- **Zotero → BibTeX export** for citations.
- **TikZ or matplotlib → PDF** for figures. Avoid raster images for charts.
- **Grammarly or LanguageTool** for the final polish.

**Writing discipline:**
- Draft section 5 (Method) and section 6 (Experiments) *first*. Those are the load-bearing sections; the others are framing.
- Then write 1 (Introduction). The intro is the hardest section to write — write it last, when you actually know what the paper says.
- Get a peer review on the draft from someone who's published in CS before *and* someone who's not in your field. The first catches technical issues; the second catches "you assume the reader knows X" issues.

### Step 8 — Pre-submission checklist (Week 7)

- [ ] Title is specific and search-friendly.
- [ ] Abstract states the contribution in one sentence.
- [ ] All claims in the abstract are supported by the experiments.
- [ ] All figures are readable in greyscale.
- [ ] All figures have axis labels with units.
- [ ] All cited works are in the bib and rendered correctly.
- [ ] Spelling, grammar, hyphenation pass.
- [ ] Anonymized for double-blind venues (some are, some aren't — read the CFP).
- [ ] Page limit and format match the venue template exactly.
- [ ] Reproducibility appendix: data source, code repo URL, trained-artifact hashes.
- [ ] arXiv preprint posted (if not double-blind). Cite the arXiv ID in your CV.

### Step 9 — Submit (Week 8)

**Submission portals:**
- Most venues: **HotCRP** or **EasyChair**.
- arXiv: register an account, get an endorsement (someone who's already published cs.CR can endorse you), upload PDF + LaTeX source.
- Journals: submit through the publisher's portal (Elsevier, Springer, IEEE Xplore each have their own).

**After submission:**
- Workshop reviews come back in 4–8 weeks.
- Journal reviews can take 3–6 months. Don't sit idle — start the next paper or apply for the Master's program with a "submitted to X" line.

### Step 10 — Revise and resubmit

If accepted with revisions ("major revision" / "minor revision"), respond point-by-point to every reviewer comment in a separate response document. Reviewers love a clear response letter.

If rejected, the reviews are still useful — almost always the paper improves with revision. Submit to a different venue. **First paper rejection is normal.**

---

## 3. Reading list to start the literature review (Option A)

The 8–12 papers any related-work section on explanation stability should cite. Read the abstracts first, then prioritize.

1. **Lundberg & Lee, "A Unified Approach to Interpreting Model Predictions"** (NIPS 2017). The original SHAP paper.
2. **Anders et al., "Fairwashing Explanations with Off-Manifold Detergent"** (ICML 2020). SHAP can be manipulated.
3. **Slack et al., "Fooling LIME and SHAP: Adversarial Attacks on Post Hoc Explanation Methods"** (AIES 2020). Closest precedent.
4. **Ghorbani et al., "Interpretation of Neural Networks is Fragile"** (AAAI 2019). Explanation fragility for NNs.
5. **Anderson & Roth, "EMBER: An Open Dataset for Training Static PE Malware Machine Learning Models"** (arXiv 2018). The dataset.
6. **Demetrio et al., "Adversarial EXEmples: A Survey and Experimental Evaluation"** (TrustComm 2021 or extended journal version). Adversarial PE work.
7. **Ceschin et al., "The Need for Speed: An Analysis of Brazilian Malware Classifiers"** (Computers & Security 2018). Tree-based malware classification.
8. A 2023–2024 survey on **"explainable malware detection"** — search Scholar; pick the most-cited one in the last 18 months.

After reading these, you'll know the precise sub-gap to claim. The paper's relate-work section becomes 5–7 of these plus 3–5 more you find through their citation graphs.

---

## 4. Realistic timeline (anchored to 2026-08 application deadline)

| Week | Calendar (approx) | Milestone |
|---|---|---|
| 1 | 2026-05-12 | Literature review pass 1 (skim 30 papers, save 10). |
| 2 | 2026-05-19 | Pass 2 + gap statement. Pre-register experiment design. |
| 3 | 2026-05-26 | EMBER download, MalVis loader swap, baseline RF+XGBoost. |
| 4 | 2026-06-02 | Perturbation pipeline, SHAP attribution capture. |
| 5 | 2026-06-09 | Run main experiments, plot results. |
| 6 | 2026-06-16 | Draft methods + experiments + results. |
| 7 | 2026-06-23 | Draft intro + related work + discussion + abstract. |
| 8 | 2026-06-30 | Polish, peer review, fix. |
| 9 | 2026-07-07 | arXiv submission. |
| 10 | 2026-07-14 | Workshop / journal submission. |
| 11–12 | 2026-07-28 | Application material updates ("preprint at arXiv:..., submitted to..."). |
| Aug | 2026-08-XX | German DS Master's applications. |

There is no slack in this plan. Build slack by:
- Cutting the experiment scope (one model family instead of two — defer the comparison to future work).
- Using EMBER's pre-extracted features verbatim instead of re-extracting via MalVis (saves a week).
- Writing the methods + experiments section *while running experiments*, not after.

---

## 5. Useful resources

- **How-to-write-a-paper guides:**
  - Simon Peyton Jones, *How to write a great research paper* — [PDF + video](https://www.microsoft.com/en-us/research/academic-program/write-great-research-paper/).
  - Mike Ashby, *How to Write a Paper* — short, free, classic.
- **LaTeX:**
  - Overleaf's "Templates" gallery, filtered by venue.
  - **TikZ** for diagrams: `texample.net` has copy-pasteable examples.
- **Reference management:**
  - Zotero + the Better BibTeX plugin for stable citation keys.
- **Plagiarism / similarity check (free):**
  - iThenticate (free for many universities), Grammarly's plagiarism check, Turnitin if your university provides it.
- **English-language editing (if needed):**
  - Many journals offer Wiley Editing / Springer Nature Author Services. Paid but useful for non-native speakers polishing the final draft.

---

## 6. Common first-time-author mistakes (avoid these)

1. **Writing the introduction first.** Wait until you know what the paper says. Section 1 is hardest precisely because it summarizes everything else.
2. **Citing only papers you've read fully.** It's normal — and expected — to cite a paper based on its abstract and a careful read of its method section. You do not have to read every cited work cover to cover.
3. **Burying the contribution.** The reader should know your one-sentence claim by the end of paragraph 2 of the introduction. Not paragraph 8.
4. **Hiding negative results.** If SHAP turns out to be *more* stable than you expected, that's still a publishable finding. "We found the opposite of what we hypothesized" is a fine story.
5. **Submitting to the wrong venue.** Read three accepted papers from your target venue *before* submitting. If yours doesn't look like them in scope and tone, you're submitting to the wrong place.
6. **Ignoring the page limit.** If the venue says 10 pages, plan for 9 + buffer. Trying to cram an 11-page paper into 10 in the final week is a desk-reject risk.
7. **Skipping the response letter on revisions.** Reviewers reject papers when they can't tell if the authors heard them. A point-by-point response letter is the single highest-ROI deliverable in the revision cycle.

---

## 7. After publication

For the German DS Master's application:
- List the paper under "Publications" with full citation, arXiv ID, and a one-line description.
- Mention it in the motivation letter as evidence of "research-to-product" capability.
- Link the MalVis repo from the paper and the paper from the MalVis README — closes the loop.
- Apply for the **DAAD Research Grant** or **Deutschlandstipendium** scholarships citing both the paper and the project.

For the field:
- A first paper opens the door to follow-ups. Drafts B (disagreement mining) and C (cross-schema comparison) build directly on A's pipeline.
- A first paper also opens the door to *being asked* for reviewer/PC duties — accept those when they fit; they're how you build the network.

---

## Appendix A — Title brainstorm

Keep these as alternatives until the paper's findings are clear; the title should match what the paper actually proves.

- *Stable Predictions, Shifting Reasons: Adversarial Robustness of SHAP for PE Malware Classifiers*
- *When Trees Disagree: Multi-Model Inconsistency as a Triage Signal in Static Malware Detection*
- *Bounded Adversarial Perturbations Preserve Verdicts but Rewrite Explanations*
- *Reproducibility-First Pipelines for Static PE Malware Detection*
- *MalVis: Interactive Explainability Tooling for Multi-Model Malware Classifiers* (system-paper title)

---

## Appendix B — Workshop / venue calendar (verify before submitting)

Approximate cadence — always check the venue's current CFP for exact dates.

| Venue | Co-located with | Typical submission deadline | Typical notification | Page limit |
|---|---|---|---|---|
| **AISec** | ACM CCS | mid-July | mid-Aug | 10 pages |
| **DLS** | IEEE S&P | early Feb | mid-Apr | 10 pages |
| **CAMLIS** | standalone | rolling | rolling | flexible |
| **WOOT** | USENIX Security | early Apr | ~6 weeks later | 8 pages |
| **SecDev** | standalone | summer | autumn | 8 pages |
| **IEEE Access** | journal | rolling | ~6 weeks first decision | flexible |
| **Computers & Security (Elsevier)** | journal | rolling | 2–4 months | flexible |

---

## Appendix C — Where this document goes from here

This file is a *plan*, not a deliverable. Update it as the paper takes shape:
- Replace "Recommended pick" with the actual chosen angle once decided.
- Replace the timeline with real dates as milestones land.
- Add a "Submitted to" section with submission IDs, reviewer comments, response letters.
- After publication, add the citation and a reflection of what worked / what didn't.

This document is paired with:
- [`README.md`](./README.md) — the project overview the paper points readers at.
- [`docs/ADR-001-feature-set.md`](./docs/ADR-001-feature-set.md) — the schema-version-as-contract pattern (relevant to Option D).
- [`lessons.md`](./lessons.md) — engineering decisions and rationale; the paper's "Discussion" section can mine this.
- [`SECURITY.md`](./SECURITY.md) — the threat model the paper's adversary section may build on.
