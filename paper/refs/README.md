# Sources

**One folder per source the draft leans on**, holding the source itself and
our notes on it:

```
refs/<slug>/
  notes.md          our receipt — always present
  <arxiv-id>.pdf    the paper, when we have the full text locally
```

Keeping the paper next to the notes is the point: a quote is checkable
without leaving the folder, and "we have not obtained the full text" is
visible as a missing file rather than as a word in a table.

This directory answers a different question from `../bibliography-notes.md`,
and the split is deliberate:

- **`bibliography-notes.md`** — *what a source supports*, and where it sits
  in the argument. Organised by the paper's sections. It is a map.
- **`refs/`** — *the source itself*: who wrote it, when, where it lives,
  **how far we have actually read it**, and **the exact strings we quote**.
  Organised one folder per source. It is the receipt.

## Why the receipts are separate

Every quote in the draft has to be checkable by someone who is not the person
who found it — including the author, three weeks later. A note saying "HDP
concedes single-key signing" is not checkable; the sentence, with its section
number and the date it was read, is.

The rule this enforces is in `../retractions.md` and the pre-submission
checklist: **a summary is not a quote**, and **"does not say" may not stand
in for "says it is out of scope"**. Both of those are easy to violate while
paraphrasing and impossible to violate while copying.

## Notes format (`notes.md`)

```
# <short name>

- **id** — arXiv id / draft name / report number
- **who** — authors and affiliation
- **when** — date of the version read
- **where** — URL, and the local PDF filename if we have it
- **status** — one of:
  - `verbatim` — full text obtained, quotes matched character for character
  - `summary` — read through a fetch summary; quotes are NOT safe to ship
  - `unread` — listed for completeness
- **read on** — date

## What it is
One paragraph.

## Quotes we use
> the sentence, exactly

**Where** — §n of the draft. **Why** — the claim it carries.

## Cautions
Anything that would make a reviewer right and us wrong.
```

## Status at a glance

| Source | Status | Full text here | Quotes in the draft |
|---|---|---|---|
| `chain-verifiability/` | **verbatim** | ✅ PDF | §4.2, §5 (and see `../strengths-and-gaps.md` B7) |
| `delegation-chain-claim/` | **verbatim** | — | §1, §2.1, §2.2, §2.4 |
| `hdp/` | **verbatim** | — | §2.1, §2.2 |
| `masdrift/` | verbatim (earlier round) | — | §1 |
| `rails/` | verbatim (earlier round) | — | §2.3 |
| `auditable-agents/` | summary | — | §1 (the hook) |
| `aat/` | summary | — | §2.2 |
| `mjwt/` | summary | — | §2.2 |
| `sentinelagent/` | summary | — | §2.1, §2.3 |
| `oauth-identity-chaining/` | summary | — | §2.4 |
| `fair-exchange/` | unread | — | §5 |
| `eu-ai-act/` | unread | — | §1 |

**Seven of twelve are not safe to ship** — five `summary` plus two `unread`.
(An earlier version of this table said five, counting only the summaries;
`unread` is not safer than `summary`, it is worse.) That is the work between
here and submission, and it is why this table exists rather than a feeling
that the citations are probably fine.

The heaviest three, because the draft leans on them where it cannot afford
to: `auditable-agents/` carries the whole §1 hook, `fair-exchange/` carries
§5's necessity argument and has not been read at all, and `sentinelagent/`
carries the adjudicator row in §2.1 and §2.3.
