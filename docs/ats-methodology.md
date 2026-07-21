# Carivyo Resume Diagnostic Methodology

## Product claim

Carivyo provides an independent, local-first resume diagnostic. It does not
claim to reproduce Enhancv's proprietary formula, predict hiring outcomes, or
represent every applicant tracking system. The analyzer runs against the exact
final PDF text and frozen job description used by a resume run. Its report is
hash-bound to those artifacts, and approval stops if any bound input changes.

The implementation targets observable report capability rather than numeric
score imitation. A vendor score is not a stable ground-truth label when its
weights, model, or test protocol are unpublished. Carivyo therefore treats
category evidence, issue detection, and safe actions as the useful output and
keeps third-party comparisons outside the product runtime.

## Analyzer contract

Version `carivyo-ats-1.1.0` evaluates 27 checks in seven categories:

| Category | Weight | Checks |
| --- | ---: | ---: |
| ATS essentials | 18 | 6 |
| Resume sections | 12 | 3 |
| Content | 20 | 5 |
| Job tailoring | 18 | 4 |
| Recruiter red flags | 12 | 4 |
| Bias and discrimination safety | 6 | 2 |
| Seniority and impact | 14 | 3 |

Every check returns an identifier, label, status, earned and available points,
evidence, and a safe suggested action. `not_applicable` checks contribute
neither earned nor available points. The displayed diagnostic is:

```text
overall = earned points / applicable available points × 100
```

The report separately exposes parse rate, category percentages, critical
failures, applicability, highest-value fixes, strengths, JD skill alignment,
interview probes, and listed-versus-demonstrated skill evidence. A critical
parse failure makes readiness `blocked` regardless of the aggregate number.

## Safety properties

- A missing JD term is a review cue, never permission to add a skill.
- Interview probes quote the resume evidence they refer to.
- Credibility review asks for measurement and ownership context; it does not
  decide whether a claim is true.
- Suggested fixes never create metrics, team sizes, dates, adoption, ownership,
  or protected-trait inferences.
- Age and other protected traits are not inferred from names, dates, education,
  language, or location. Only explicitly labeled optional sensitive fields are
  detected for removal review.
- No resume or JD is sent externally by default. Enhancv receives the exact
  current PDF and frozen JD only after the user selects that engine and confirms
  external processing. Credentials and temporary browser artifacts are never
  stored in a resume run.

## Research basis

The parse checks follow current official ATS guidance. Greenhouse documents
partial-parse risks from oversized or image-only files, graphics, tables,
headers/footers, text boxes, columns, unclear sections, and incomplete titles:
[Greenhouse unsuccessful resume parse](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse).

Workday describes modern ATS behavior as structured extraction of education,
skills, and work history followed by semantic comparison rather than simple
keyword counting, while still recommending simple headings, standard fonts,
and limited graphics or special characters:
[Workday ATS overview](https://www.workday.com/en-us/topics/hr/applicant-tracking-system.html).

Greenhouse's current Talent Matching documentation narrows matching inputs to
skills, job titles, experience duration, employment dates, company names, and
derived industry, and explicitly excludes special-category data:
[Greenhouse Talent Matching data processing](https://support.greenhouse.io/hc/en-us/articles/41131616864283-Talent-Matching-Data-Processing-FAQ).

For semantic matching, Carivyo follows the field-aware lesson from ConFit:
resume-job fit is a ranking and classification problem over structured resume
and job fields, and learned similarity requires validated datasets rather than
an invented universal threshold:
[ConFit paper](https://arxiv.org/abs/2401.16349).

Bias controls follow NIST's recommendation to document benchmark limitations,
test counterfactual behavior, and avoid proxy features that can encode protected
groups: [NIST AI RMF Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf).

## Optional Enhancv comparison

Enhancv publicly describes a two-tier report with 27 checks across ATS
essentials, sections, content, job tailoring, recruiter red flags,
bias/discrimination, and seniority/impact. Carivyo uses this public description
as a coverage reference without copying a proprietary formula or claiming
numeric equivalence:

- <https://enhancv.com/resources/resume-checker/>
- <https://enhancv.com/features/tailor-resume-to-job-description/>

An authorized live integration check on 2026-07-21 completed in JD-tailored
mode for an existing test PDF/JD and returned overall 26, generic 48, and a
tailoring category of 19. This proves the adapter captured a real tailored
report; it is not an ATS-quality benchmark or parity measurement. Only one
compact final report is retained after temporary HTML, screenshots, logs, and
generic intermediates are removed.

## Calibration and the 98% benchmark goal

“98% agreement with a premium ATS report” is a benchmark objective, not a
verified product claim. A comparison is valid only for reports obtained under
an authorized account and then anonymized and retained with permission. It must
not require copied proprietary code, access-control bypass, credential storage,
or private-data scraping.

For a corpus with independently mapped vendor outputs, the primary agreement
metric is defined before calibration:

```text
agreement =
  0.50 * issue_detection_F1
  + 0.25 * category_agreement
  + 0.15 * recommendation_rank_agreement
  + 0.10 * normalized_score_closeness
```

- `issue_detection_F1` is the macro F1 of normalized issue labels across the
  27-check taxonomy.
- `category_agreement` is the share of mapped category results within a
  predeclared ten-point tolerance after scale normalization.
- `recommendation_rank_agreement` is Spearman rank correlation rescaled from
  `[-1, 1]` to `[0, 1]` over comparable recommendations.
- `normalized_score_closeness` is `1 - abs(local - vendor) / 100`; it has the
  smallest weight because an opaque overall score is not ground truth.

The 98% goal also requires issue precision and recall of at least 95%, exact
deterministic repeatability of 100%, zero fabricated candidate facts, a minimum
of 100 diverse resume/JD pairs, and published false-positive/false-negative
analysis. A high composite score cannot waive any floor.

Current measurable release gates are:

1. 27/27 observable public checks represented with evidence and safe actions.
2. 100% of generated reports bound to the exact PDF, extracted text, JD, source,
   analyzer version, and canonical analysis hash.
3. No critical parser false pass in malformed, image-only, or tampered fixtures.
4. The composite and floor metrics above on a future authorized, labeled,
   anonymized calibration corpus.
5. Zero fabricated candidate facts in the evidence-constrained test suite.
6. Human review of recruiter-risk prompts and counterfactual bias cases before
   any claim of broader parity.

The repository currently proves items 1–3 and 5 on synthetic and regression
fixtures. The committed synthetic benchmark has two cases and 15 labeled
outcomes; its 1.0 precision/recall is a regression check, not general accuracy.
Vendor agreement is currently `null`. Item 4 requires a larger licensed or
user-consented anonymized corpus; item 6 remains a release process, not an
automated certification.
