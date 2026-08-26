# Sources

One file per source the draft leans on. This directory answers a different
question from `../bibliography-notes.md`, and the split is deliberate:

- **`bibliography-notes.md`** — *what a source supports*, and where it sits
  in the argument. Organised by the paper's sections. It is a map.
- **`reference/`** — *the source itself*: who wrote it, when, where it lives,
  **how far we have actually read it**, and **the exact strings we quote**.
  Organised one file per source. It is the receipt.

## Why the receipts are separate

Every quote in the draft has to be checkable by someone who is not the person
who found it — including the author, three weeks later. A note saying "HDP
concedes single-key signing" is not checkable; the sentence, with its section
number and the date it was read, is.

The rule this enforces is in `../retractions.md` and the pre-submission
checklist: **a summary is not a quote**, and **"does not say" may not stand
in for "says it is out of scope"**. Both of those are easy to violate while
paraphrasing and impossible to violate while copying.

## File format

```
# <short name>

- **id** — arXiv id / draft name / report number
- **who** — authors and affiliation
- **when** — date of the version read
- **where** — URL
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

| Source | Status | Quotes in the draft |
|---|---|---|
| `delegation-chain-claim.md` | **verbatim** | §1, §2.1, §2.2, §2.4 |
| `hdp.md` | **verbatim** | §2.1, §2.2 |
| `auditable-agents.md` | summary | §1 (the hook) |
| `masdrift.md` | verbatim (earlier round) | §1 |
| `aat.md` | summary | §2.2 |
| `mjwt.md` | summary | §2.2 |
| `sentinelagent.md` | summary | §2.1, §2.3 |
| `rails.md` | verbatim (earlier round) | §2.3 |
| `oauth-identity-chaining.md` | summary | §2.4 |
| `fair-exchange.md` | unread | §5 |
| `eu-ai-act.md` | unread | §1 |

**Five of eleven are not safe to ship.** That is the work between here and
submission, and it is why this table exists rather than a feeling that the
citations are probably fine.
