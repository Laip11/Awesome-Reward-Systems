# Contributing

Thanks for helping keep this list useful. `papers.yaml` is the only data source, and `README.md` is generated from it.

## Add a code link or a short note to a paper

Edit the paper's entry in `papers.yaml` and set the fields people maintain by hand:

```yaml
- key: cui2025prime
  ...
  code: https://github.com/PRIME-RL/PRIME
  note: implicit PRM trained from outcome labels
```

Then run `python scripts/render.py` and commit both files.

## Move a paper to another section

Set `primary_override` to a category `id` from `taxonomy.yaml`:

```yaml
  primary_override: judge-generative
```

## Add a paper that the survey does not cite yet

Append an entry by hand with `key`, `title`, `venue`, `year`, `link`, and `primary_override` (a category `id` from `taxonomy.yaml`). `bib2yaml.py` keeps entries whose key is not in the survey's bibliography unchanged. Please also mention the paper in your PR so that it can be considered for the next version of the survey.

## Checks

- `python scripts/render.py --check` must pass (CI runs it).
- Links should point to the paper's landing page (arXiv abstract, OpenReview, ACL Anthology, or the publisher), not a PDF.
