# Fair exchange, and why the TTP there is a judge

- **id** — TUD-BS-1999-02
- **who** — Henning Pagnia, Felix Gärtner, Darmstadt University of Technology
- **when** — March 1999
- **where** — technical report; abstract at
  http://lpdwww.epfl.ch/fgaertner/pubs/TUD-BS-1999-02.abstract.html
- **status** — `unread` — **cited in §5 and not yet read**
- **read on** — never; identified 2026-08-26 from search results

## What it is

The proof that **strong fair exchange is impossible without a trusted third
party**. With it: Even & Yacobi (1980), and the fair non-repudiation line
(Zhou & Gollmann and after).

## How the draft uses it — as contrast, not as support

§5 cites it to say **what this paper is not**. In that literature the third
party is a **judge**: the protocols carry abort and recovery sub-protocols
plus a dispute-resolution policy specifying how a judge settles, and the
whole point is fairness — neither party gains by quitting early.

This paper's property is strictly weaker: **distinguishability**, not
fairness. Telling "declined to extend" from "erased a hop" needs a party that
**sees both edges**, not one entitled to rule on either. Hence *witness*, not
arbiter — and the weaker requirement is the deployability argument.

## Cautions

- **Citing it as our necessity argument would import an adjudicator** and
  contradict rule zero. A reviewer who knows this line will say: their third
  party judges, yours refuses to, so the theorem does not reach you. The
  draft must use it as lineage and contrast, and say so in the sentence.
- This paper also does not attempt fair exchange at all: a provider declining
  to extend is a **boundary**, not an unfair abort.
- **Verify the report number, date and institution against the report
  itself** before it ships. Everything above came from search results.
