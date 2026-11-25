# Knowledge base (KB)

Version-controlled rules, policies and guidelines that the agents may cite as
evidence (`[KB-1]`, `[KB-2]`, ... in prompts). Each item is one Markdown file
with YAML front-matter:

```yaml
---
id: KB-POL-LOAN-001          # stable ID, unique per item (versions share it)
title: Retail loan credit policy
type: policy                 # regulation | policy | security_standard | re_guideline | sdlc_rule | template
source: SAMPLE internal policy   # publisher; must be in config.KB_ALLOWED_SOURCES to be used as evidence
jurisdiction: SAMPLE
effective_date: 2026-01-01
version: "2.0"
applicability: [loan_processing]   # loan_processing | kyc | payments | all
status: active               # active | superseded
---
```

Rules:
- Only `status: active` items whose `type` is in `config.KB_EVIDENCE_TYPES` and whose
  `source` is in `config.KB_ALLOWED_SOURCES` are retrieved as evidence.
- `##` headings split an item into sections; each section is indexed separately.
- Files are re-indexed only when their content hash changes.
- This README (no front-matter) is not indexed.

> **Every item shipped here is SAMPLE content – illustrative, not authoritative.**
> It does not quote or summarise any real law or regulator. Replace it with
> text approved by your compliance team before relying on it.
