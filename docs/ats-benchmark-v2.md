# ATS v2 anonymized PDF benchmark

The committed `anonymized-pdf-v2` regression corpus contains 100 resume/JD
pairs across ten role families: backend, frontend, full-stack, AI, ML, data,
platform, security automation, SDET, and technology analyst. Every case is
rendered to an actual PDF, parsed back with `pypdf`, and evaluated twice for
deterministic repeatability. Identities and employers are fictional.

Run:

```bash
.venv/bin/python scripts/benchmark_ats.py
```

Results for `carivyo-ats-2.0.0`:

- Cases and valid PDF artifacts: 100/100.
- Role families: 10.
- Labeled check decisions: 800.
- Repeatability: 1.0000.
- Issue precision: 1.0000 (zero false positives).
- Issue recall: 0.9857 (two false negatives).
- Confusion matrix: TP 138, FP 0, FN 2, TN 660.

## False-positive and false-negative analysis

There were no labeled false positives. Both false negatives were in the ML
role family (`05-ml-06` and `05-ml-07`) on `hard_skills`. The adversarial
resumes listed the target tools but intentionally supplied weak delivery
evidence. The analyzer passed because “ML Engineer” and three target entities
were interpreted as demonstrated outside the Skills field. This is a known
field-boundary weakness; release claims must use the measured 0.9857 recall,
not round it to 100%.

This corpus is a transparent regression benchmark, not a licensed sample of
real applicants and not evidence of parity with any vendor. The PDFs are real
artifacts generated from reviewed, anonymized cases so they can be safely
committed and reproduced. Vendor agreement remains `null` until a licensed or
user-consented corpus exists.
