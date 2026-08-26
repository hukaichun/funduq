# Bibliography notes for the responsibility-chains paper

> Working notes, not a document of record. Each entry carries the claim it
> is meant to support, organized by the paper's planned sections. Two
> honesty notes: (1) classical entries' bibliographic details (venues,
> years, page numbers) are from memory and MUST be verified against the
> actual publications before any citation ships; (2) entries marked
> **read-before-writing** shape our own claims and need a full read, not
> an abstract skim. arXiv links verified live 2026-08-19.
>
> Paper storyline and outline: see the project memory / conversation of
> 2026-08-19; thesis: a minimal neutral intermediary (records, retains,
> verifies its own verbs, never adjudicates) under which open authority/
> timing/intervention questions become derivable.

> **2026-08-21 補篇：`downstream-review-2026-08.md`** — 以本檔 21 個 arXiv
> 條目為 seed 的下游引用擴查（339 篇 citer）＋ 2026-05 後的 arXiv listing
> 補查，含四篇必讀導讀。同日另有兩項修訂已直接改進本檔：
> (1) §2.1 的「the authority axis is absent」被 arXiv:2606.31498 推翻；
> (2) **AIP 那格的 down-flow / up-flow 二分讀完全文後確認是錯的，已撤下**
> 並換成 lane-by-lane 的版本。同軸競爭者是 arXiv:2606.08790 (RAILS)。
>
> **2026-08-25／26 補篇：`landscape-2026-08-25.md`** — 產品與規格側的重查，
> 本檔先前完全沒有。它加了兩節：**§2.7 委派鏈規格**（2026 上半年至少五個
> 設計，其中一份掛 Okta 與 Cisco）與 **§2.8 廠商平台一手文件**（四家把
> 邊界畫在自己的信任域上，三家自己寫明）。同時修一條錯引：舊的「116 份
> 草案只有 5 份用 `authorization_details`」數的是 **scope** 不是 **chain**，
> 不得拿來支持「沒人在做委派鏈」。
>
> 讀全文進度：AIP (2603.24775) ✅、Governance Gaps (2606.31498) ✅、
> RAILS (2606.08790) ✅、Stop Means Stop (2607.14166) ✅、Governance at the
> Boundary (2608.16055) ✅、MasDrift (2608.07556) ✅，皆 2026-08-21；
> `draft-liu-oauth-chain-delegation-00` ✅、HDP (2604.04522) ✅，
> 2026-08-25，兩者的引文皆逐字比對過原文。
> **§1 必讀清單已清空**；原有的三個 read-before-writing 旗標仍未讀
> （2604.00892 / 2606.06460 / 2603.25100）。
>
> 結算與待決事項：**`strengths-and-gaps.md`**（11 條已知優勢附原句出處、
> 11 條已知缺口、4 題待使用者決定）。
> 兩模式模型與 deferred call 路由：**`input-required-routing.md`**（只放結論）。
> 這一輪寫下又被推翻的十三條說法（五種形態）：**`retractions.md`**。

## §2.1 Agent interoperability protocols and surveys

| Entry | Supports |
|---|---|
| Survey of agent interoperability protocols: MCP/ACP/A2A/ANP — [arXiv:2505.02279](https://arxiv.org/abs/2505.02279) | The authoritative landscape survey; background framing |
| Comparative study of MCP and A2A — [arXiv:2607.23884](https://arxiv.org/html/2607.23884v1) | Empirical interop state of the art |
| MCP × A2A framework study — [arXiv:2506.01804](https://arxiv.org/abs/2506.01804) | Same |
| Security analysis of agentic AI communication protocols — [arXiv:2511.03841](https://arxiv.org/pdf/2511.03841) | Documented protocol gaps, security angle |
| A2A spec (v1.0/v1.1 dev), AG-UI spec, A2UI — official docs | Primary sources |
| **Governance Gaps in Agent Interoperability Protocols** — [arXiv:2606.31498](https://arxiv.org/abs/2606.31498) v1, 2026-06-30 | **Full text read 2026-08-21.** Six-dimension governance taxonomy (membership / deliberation / voting / dissent / **human escalation** / audit) against MCP v1.1, A2A v1.0.1, ACP, ANP, ERC-8004; voting, dissent and human escalation are Absent in all five. **Retires the old "the authority axis is absent" claim — it is published now.** Three lines to lift: "Yet coordination is not governance"; §V-A "After 6+ months of A2A being publicly available with an active extension ecosystem, zero governance extensions have been proposed or implemented" (**cite this instead of the issue tracker**); §V-B's 6–12-month window as the why-now. **Complement, not collision**: its G5 escalation is a deliberative body routing a vote to a human on a confidence trigger — ours is the responsibility path through a delegation tree. Its §III-A explicitly puts payment/incentive and trust *outside* governance scope, and G1–G6 contain no delegation, authority-to-act, interruption or timing. **Cite the finding, do not adopt the taxonomy** — inheriting G1–G6 would force us to explain why we score nothing on voting and dissent, when rule zero makes those a deliberate exclusion. Weakness to note: read at A2A v1.0.1, so v1.1 elicitations may move its G5 — check that ourselves |
| a2aproject/A2A Epic #1992; google/adk-python #3276; ag-ui-protocol/ag-ui #2148 (URLs + access dates) | Supporting evidence only, behind arXiv:2606.31498. The issues show the gap lists are time-axis only |

## §2.2 Classical multi-agent systems

The likely reviewer community; this section is the handshake with it.

| Entry | Supports |
|---|---|
| Smith, *The Contract Net Protocol* (IEEE Trans. Computers, 1980) | Ancestor of delegation/task allocation; funduq's offer/decline/refuse broker is its descendant |
| Finin et al., *KQML* (CIKM 1994); FIPA-ACL specifications | Two generations of ACLs; the "states defined, authority not" pattern begins here |
| Singh, commitment protocols (1998–); Yolum & Singh (AAMAS 2002) | Break/extend declarations read as commitments; Strabo's Langshaw is this school |
| Esteva et al., electronic institutions / ISLANDER (2001–); AMELI | **Academic ancestor of mechanism/policy separation** — institution provides the rule space, participants stay autonomous |
| Hewitt, actor model (1973) | Opaque message-passing roots |
| *Agentifying Agentic AI* — [arXiv:2511.17332](https://arxiv.org/html/2511.17332v2) (WMAC @ AAAI 2026) | The bridge manifesto: MAS community reconnecting classical concepts to LLM agents; citing it addresses our target readers directly |

## §2.3 Delegation, authorization, identity

| Entry | Supports |
|---|---|
| Lampson, Abadi, Burrows, Wobber, *Authentication in Distributed Systems: Theory and Practice* (ACM TOCS, 1992); Abadi et al., a calculus for access control (1993) | **The speaks-for relation — theoretical ancestor of actor chains**; must-cite |
| Birgisson et al., *Macaroons* (NDSS 2014); Biscuit; UCAN; SPIFFE/SPIRE; W3C DIDs | The attenuating-capability-token lineage (AIP's foundations; cite along its bibliography) |
| Dennis & Van Horn (1966); Miller et al., *Capability Myths Demolished* (2003) | Capability-systems tradition |
| Blaze, Feigenbaum, Lacy, *PolicyMaker* (IEEE S&P 1996); KeyNote | Decentralized trust management precursors |
| **Pagnia & Gärtner, *On the Impossibility of Fair Exchange without a Trusted Third Party*** (TUD-BS-1999-02, TU Darmstadt, 1999-03); Even & Yacobi (1980); Zhou & Gollmann, fair non-repudiation | **Lineage and contrast for §4.5 — cite it to say what we are *not*.** It proves strong fair exchange is impossible without a TTP, and in that literature **the TTP is a judge**: the protocols carry abort and recovery sub-protocols plus a dispute-resolution policy specifying how a judge settles. Citing it as our necessity argument would import an adjudicator and contradict rule zero — a reviewer who knows this line would say their third party judges, ours refuses to, so the theorem does not reach us. We also do not attempt fair exchange: a provider declining to extend is a boundary, not an unfair abort. **What we borrow is the shape, not the conclusion.** Our property is *distinguishability* (declined-to-extend versus erased hop), which is strictly weaker than fairness and needs a party that **sees both edges**, not one that may rule — hence *witness*, not arbiter, and the weaker requirement is the deployability argument. Verify the exact report number and date before it ships |
| **AIP** — [arXiv:2603.24775](https://arxiv.org/abs/2603.24775) v1, 2026-03-25 (+ same author's LDP, Provenance Paradox) | The near neighbor. **Full text read 2026-08-21; the earlier "AIP governs down-flow, we govern up-flow" slogan was wrong and is retired** — §3.2's Completion block (result hash, verification status, resource consumption, cost) is appended back onto the same token, and §3.3 defines three trust levels (self-reported / counter-signed / third-party attested). AIP *does* have an up-flow. The differentiation that survives the full text, per lane: **escalation path — absent; visibility — absent; blame — raw material only, signed by the party being judged; funding attribution — raw material only, budget is a per-token ceiling, never a running balance** (§3.4: "Aggregate spend enforcement is the runtime's responsibility, not the token's" — funduq is that runtime). So AIP's up-flow is *a self-report with no observer*, and its own Limitations concede the point, citing the Provenance Paradox: self-claimed quality "systematically selects the worst delegates"; counter-signing and third-party attestation "exist as trust escalation options but are not enforced in v1". **Argue the differentiation out of AIP's own limitations section, never out of a down/up dichotomy.** Also verified: no break concept (§3.7 is attenuation-only + bounded depth, default 3); no HITL/interrupt/cancel content anywhere; no revocation (§7: sub-hour TTL, CRL endpoint is MAY and no reference implementation checks it) — contrasts with rule zero. Weight it accordingly: single author (ISB India), self-citing trilogy, evaluation is single-machine localhost with no production deployment, by its own admission |
| IETF drafts: AIMS, WIMSE, Agentic JWT, SCIM-for-agents | Industry standardization pulse. **Superseded in specificity by §2.7** — that section names the drafts that actually carry delegation chains |
| **HDP** — [arXiv:2604.04522](https://arxiv.org/abs/2604.04522), Helixar (single author, NZ), 2026-03; also `draft-helixar-hdp-agentic-delegation-00` | **Full text read 2026-08-25 (PDF text extracted, quotes matched character for character). The closest thing to our mechanism, and it says our sentence**: §4.2.3 "Semantic validation of agent actions against declared scope is an application-layer concern; **HDP provides the record, not the enforcement**." The line must be drawn on *what is recorded*, not on record-versus-enforce, or a reviewer will say it is already said. Three differences, all from its own text: (1) **§7.1** — "HDP v0.1 uses the issuer's key for all hop signatures, meaning agents do not sign with their own keys… hop signatures attest that **a hop was recorded at the issuer**, not that the specific agent produced it"; per-agent keys are a v0.2 plan. (2) It records scope — a free-text `intent`, `authorized_tools`, `data_classification`, `network_egress`, `persistence`, `max_hops` — and pushes checking to the application layer (§7.2). (3) Time and session: `expires_at` defaults to 24h and a `session_id` bound out of band; replay defence is expiry plus session binding, with **no possession check**. Its §5.4 concedes the semantic boundary: a legitimate agent recording a genuine hop with a misleading `action_summary` "is not detectable by the protocol alone" |
| **SentinelAgent** — [arXiv:2604.02767](https://arxiv.org/html/2604.02767v1) | The adjudicator row's contemporary instance: a central Delegation Authority Service issues, intercepts and **blocks**, with NIST 800-53 controls inside the token and an intent vector per hop. Self-reported weakness worth quoting: 13% TPR against adversarial intent paraphrasing. `[待逐字查證 — currently a summary]` |
| **Auditable Agents** — [arXiv:2604.05485](https://arxiv.org/html/2604.05485) v2, USC/ASU/JHU, **2026-08-13** | **The §1 hook.** Five auditability dimensions, the fourth being **Responsibility Attribution** — "full delegation chains recoverable from immediate executor to originating principal". Two lines: "**no existing work covers all five dimensions jointly**" (Evidence Integrity and Lifecycle Coverage most neglected), and open problem **OP3, "Capturing full responsibility chains across multi-agent delegation"**; **OP6** is cross-party audit aggregation when several organisations hold partial traces. Three institutions, two weeks old, and it writes our subject up as unsolved — stronger than the CSA percentages, whose n was never verified and which are now dropped. Caveats it states about itself: evidence comes from the authors' own tools, no end-to-end audit on a deployed system, open-source projects only. `[待逐字查證 — quotes currently from a summary]` |
| **Authorization Propagation as Infrastructure** — [arXiv:2605.05440](https://arxiv.org/html/2605.05440v1), Kamiwaza, 2026-05 | Requirements-only (R1–R7), proposes no mechanism, and concedes "Whether these mechanisms can be composed without introducing new failure modes remains an open architectural question". Demand-side citation, not a rival. `[待逐字查證]` |

## §2.4 HITL, mixed initiative, interruptibility

The theorem-3 (interjection) conversation partners; richest 2026 harvest.

| Entry | Supports |
|---|---|
| Horvitz, *Principles of Mixed-Initiative User Interfaces* (CHI 1999) | HCI ancestry of turn-taking initiative |
| Scerri, Pynadath, Tambe, adjustable autonomy (JAIR 2002) | MAS formalization of authority transfer between humans and agents — precursor concept to responsibility chains |
| Orseau & Armstrong, *Safely Interruptible Agents* (UAI 2016) | RL-theoretic interruption; interlocutor for cancel-as-request |
| **Stop Means Stop** — [arXiv:2607.14166](https://arxiv.org/abs/2607.14166) v1, 2026-07-15 | **Full text read 2026-08-21.** Six frameworks' HITL approval gates, cancellation and timeouts deliver none of the barrier semantics their names imply. **Its thesis is a contract mismatch, not "cancellation is unreliable"** — Temporal leaks the same behavioural bits but *documents* cancellation as cooperative, and the paper's own line is that this is "exactly the contract difference this paper isolates". funduq sits on the honest side of that line; cite it that way. Numbers: sibling leak in 5/6 frameworks across 4 execution models and 2 runtimes; a 1,000-workflow randomized sweep is fully deterministic (577/577 same-superstep effects execute during the pause, 0/363 gate descendants, 0/331 later supersteps); live, 215/1,200 unmediated runs leak, P(leak|emitted)=1.00, 0/1,200 mediated. Honest counter-evidence it publishes against itself: on naturalistic tau-bench models serialize their writes, so the gap is "latent rather than prevalent" — but on tasks that genuinely carry two consequential steps GPT-4o batched in 500/500 runs, and 45/115 tau-bench retail gold sequences need two consequential writes. **Prepare the obvious reviewer question**: SOUNDGATE proves a barrier IS achievable, so why does funduq only ask? Because SOUNDGATE's guarantee is conditional on **complete mediation**, discharged by Linux namespaces and cgroup eBPF — a single-host, single-trust-domain assumption that a remote provider behind an opacity boundary denies. Complete mediation being unavailable is *why* observed-outcomes-only is forced, not conservative. Also the genre template for our probes: claim scope stated once and held, non-goals listed once, violation predicates fixed a priori, "refinement evidence, not a mechanized refinement proof", and a reproduce.sh that rederives every headline number offline |
| **InterruptBench** — [arXiv:2604.00892](https://arxiv.org/abs/2604.00892) | **Read-before-writing.** Formalizes three interruption types — addition, revision, retraction — nearly isomorphic to our queue lane / reply lane / withdrawal; also shows LLMs handle interruptions poorly = demand evidence for protocol-level discipline. Decide: adopt their taxonomy or contrast |
| *Are Large Reasoning Models Interruptible?* — [arXiv:2510.11713](https://arxiv.org/html/2510.11713v4) | Model-level interruption is unreliable → protocol-level discipline needed |
| AgentScope 1.0 — [arXiv:2508.16279](https://arxiv.org/pdf/2508.16279) | Framework-level real-time steering (pausing the ReAct loop) — the single-framework, intra-box counterpart to our cross-box interjection |
| **Will the Agent Recuse, and Will It Stop?** — [arXiv:2606.06460](https://arxiv.org/html/2606.06460v3) | **Read-before-writing.** Measures agent compliance with mid-flight halt directives — empirical backing for "cancellation is a request, not a command"; turns our four-line outcome table from philosophy into engineering for measured reality |
| **MasDrift** — [arXiv:2608.07556](https://arxiv.org/abs/2608.07556) v1, 2026-08-18 | **Full text read 2026-08-21. Our strongest empirical ally under the capability-out-of-scope line** — the whole paper argues in boundary terms. "A delegated goal and its authorization boundary are not the same object"; Principle 1: delegation may copy or narrow authority but never create, widen or prematurely activate it, and "task readiness, role expectations, inter-agent agreement, and successful completion of prerequisite work do not themselves constitute user authorization"; an action has valid authorization lineage only if its authority traces to the user request through the handoff path (down-flow actor chain, same root as Lampson's speaks-for). Threat model is deliberately benign, so every failure is endogenous to decomposition. **Four lines to quote**: "Near-zero violations do not imply preserved authorization"; "Same lead, same drift, different executor" (identical constraint loss, 1.0% vs 24.9% unauthorized action); "The problem is not that users are insufficiently explicit — explicitness does not survive a handoff" (this kills 2608.16055's own prompting caveat); and "upgrading the model buys restraint at the last hop and nothing across the hops before it, so a system can become more capable, cheaper, and less authorized at once — the fix is architectural, not a question of which model you buy." 92% of one lead's constraint losses land at the *first* handoff. **The Source-vs-Chain contrast is the empirical counterexample to the attenuating-capability-token lineage** (AIP §3.7, UCAN, Macaroons, Biscuit): Chain eliminates unauthorized actions but blocks up to 54.5% of required calls and costs up to 36.3 completion points, because "Chain entrusts the policy to the same handoffs that lose the constraint" — delegators cannot anticipate downstream needs and over-attenuate. Source blocks at most 3.5%. **State the gap honestly**: Source works by living outside the coordination graph (our architectural position) but it also adjudicates and assumes complete mediation, and MasDrift has no record-only arm — it does not test rule zero, so never claim it vindicates it. Also: confirmations auto-approved in the main runs, single LLM judge for two metrics, synthetic English-only environments. Its July 2026 Codex incident (a subagent recursively deleting a home directory under filesystem access the request never granted) is a boundary-shaped hook for the intro — better than any percentage |
| **Governance at the Boundary / Fiducia-bench** — [arXiv:2608.16055](https://arxiv.org/abs/2608.16055) v1, 2026-08-17 | **Full text read 2026-08-21.** Topology is the only independent variable: same tools, same policy corpus, same ROLE/CONDUCT blocks, only the paragraph describing the architecture differs. Policy-relevant facts discovered by one component are attenuated at the handoff boundary before reaching the component that must act on them. **The line to quote: "The component that violates is not the component that failed."** Paired mirror tasks show the mechanism is direction-agnostic — a dropped risk signal gives under-escalation, a dropped exculpating finding gives over-escalation — which also kills always-escalate as a cheap fix. D2 elicits more trigger facts than D0 (27 vs 16 per 100 episodes) and then loses 81% of them: the architecture better at finding is worse at carrying. Control that rules out the competing explanation: in-context policy vs retrieval made no systematic difference — "Decomposition, not policy access mode, drives the effect." Its §6 asks for exactly our intervention: "structured handoff protocols — defining what a summary must contain and what it is not permitted to omit — are a natural intervention, and one that current practice largely ignores." Its first methodological recommendation is our observed-outcomes-only invariant, independently rediscovered: attribute tool calls in the environment rather than trusting agent self-reports. **Cite with care**: 85% is 22/26 and 56% is 9/16 — never quote the percentage without n; governed success is 8/596 (1.3%), which the authors concede leaves the headline chart unanchored; two models only, one a GPTQ-Int4 local Qwen2.5-32B. They name the caveat that hurts us most — the effect may be reducible by better handoff prompting. **Answer that with verifiability, not competence**: even at gpt-4.1-mini's 3%, an outside observer still cannot tell whether the fact crossed the boundary, and prompting moves the probability, not the observability |
| *How to Steer Your Multi-Agent System* — [arXiv:2605.23023](https://arxiv.org/pdf/2605.23023) | Human collaborative planning over MAS |
| Human-agent collaboration survey — [arXiv:2505.00753](https://arxiv.org/abs/2505.00753); TRiSM — [arXiv:2506.04133](https://arxiv.org/html/2506.04133v3) | Survey-level context |

## §2.5 Durable execution and transactional semantics

| Entry | Supports |
|---|---|
| Garcia-Molina & Salem, *Sagas* (SIGMOD 1987) | Compensation semantics ancestor — A2A's #2124 ("canceled is not compensated") is rediscovering it |
| van der Aalst et al., workflow patterns (~2003); BPMN user tasks | Workflow prehistory of HITL |
| Durable-execution engines (Temporal et al., industry literature); Atomix — [arXiv:2602.14849](https://arxiv.org/pdf/2602.14849); SagaLLM | "State outlives connections" as industry consensus — axiom 3's backing |
| Always-On Agents survey — [arXiv:2606.30306](https://arxiv.org/pdf/2606.30306) | Persistent state/governance survey, directly adjacent |
| Concurrency anomalies in multi-agent LLM systems — [arXiv:2606.17182](https://arxiv.org/pdf/2606.17182) | Academic counterpart of our per-thread serialization problem |

## §2.6 Agent economies, discovery, trust

| Entry | Supports |
|---|---|
| SoK: Blockchain agent-to-agent payments — [arXiv:2604.03733](https://arxiv.org/pdf/2604.03733); A2A + x402 + ledger identities — [arXiv:2507.19550](https://arxiv.org/abs/2507.19550); Five attacks on x402 — [arXiv:2605.11781](https://arxiv.org/html/2605.11781v1) | On-chain cost-attribution lane (contrast with KYOK's off-chain attribution) |
| **RAILS** — [arXiv:2606.08790](https://arxiv.org/abs/2606.08790) v1, 2026-06-07 | **Full text read 2026-08-21. The nearest same-axis neighbour — closer than AIP.** Defines the *agentic clearing problem*: performance failure is not counterparty failure (a valid authorization, a valid payment, an honest merchant delivering exactly what was asked, and the user is still harmed because the agent asked for the wrong thing). Six separable questions (authorization / execution / performance / **attribution** / loss / settlement); seven primitives; one falsifiable soundness property. **Cite it for its own open problem**: §12.1 says the subdelegation chain "leaves open the assignment of fault... because there is no human principal to absorb it" — our founding observation (every delegation tree is human-rooted and human-backed at every node) denies that premise, so we dissolve the problem rather than solve it. §9.2's logistics case (orchestrator → broker → carrier breaching the fee ceiling three links down, venue performing perfectly) is isomorphic to the dress-size relay. Differentiation, per the full text: (1) **it also calls itself neutral** — the axis is not neutral vs not but *neutral adjudicator vs neutral abstainer*; §5.5 says plainly "RAILS adjudicates on evidence" and §9.8 claims the clearinghouse decision authority; (2) its human arbiter is demoted to "one more verifier vote" (§6.3) while ours roots the tree; (3) it needs a co-signed, machine-clearable Obligation Object per hop, and §12 concedes it is useless both where obligations are too subjective and where they are cheaply checkable; (4) its CANCELLED is bilateral agreement only — no cancel-as-request, no mid-flight halt; (5) **it does have escalation** (§6.3 human-arbiter loop + appeal window) but it is escalation *within adjudication*, not escalation of responsibility — never claim it has none. Its §12 "Governance questions remain open" is the demand-side evidence for our positioning: funduq does not govern, it leaves the seam governance attaches to |
| ERC-8004 empirical study — [arXiv:2606.26028](https://arxiv.org/html/2606.26028) | Academic counterpart of the A2A trust-evidence discussions (#1631) |
| *From Logic Monopoly to Social Contract* — [arXiv:2603.25100](https://arxiv.org/pdf/2603.25100) | **Read-before-writing.** Title suggests our mechanism/policy philosophy — check for convergence or collision before we claim the framing |

## §2.7 Delegation-chain specifications (IETF) — the direct rivals

> **Added 2026-08-25.** This section is why the old "116 drafts, 5 with
> `authorization_details`" figure must not be cited for nobody-does-chains:
> that number counts **scope**, not **chains**. Between March and June 2026 at
> least five signed-hop-chain designs appeared. See
> `landscape-2026-08-25.md` for the full table.

| Entry | Supports |
|---|---|
| **`draft-liu-oauth-chain-delegation-00`** — Alibaba ×2, Cisco, **Okta**, 2026-06-06, individual submission | **The nearest rival, and the one to watch — if the OAuth WG adopts it, `funduq-contract` goes from complement to competitor. Full text read 2026-08-25; every quote below matched character for character against the document.** Its framing is the field's in one sentence: "Each delegation hop must **preserve the original user's authorization intent** while **constraining what each downstream agent is permitted to do**." Central issuer: `as_signature` REQUIRED, `delegator_signature` only RECOMMENDED, and "the Resource Server **MUST** use token introspection… to retrieve **the authoritative `delegation_chain` from the AS**, rather than trusting any client-supplied chain data." Vocabulary given up in three steps: "**This field is typically absent.**"; "…Rego…, ALFA…, XACML, or **any other policy representation agreed upon by the delegator and the Authorization Server**"; and where subset checking is "computationally expensive or **undecidable**, the RS **MAY rely on the AS's attestation**". Bounds it states: "focuses on **linear** delegation chains", diamond topologies deferred, "A RECOMMENDED default maximum depth is **5 hops**". **The paragraph to build §2 around**: its own second gap is our mechanism — "The `act` claim is **constructed unilaterally by the Authorization Server**. The delegating agent leaves **no independent cryptographic evidence** that it authorized a specific delegation. This limits non-repudiation and post-hoc audit capabilities" — and then it makes that signature the optional one. They found the same hole and made it a MAY |
| **`draft-niyikiza-oauth-attenuating-agent-tokens-01`** — Tenuo (single author), 2026-06-15 | Attenuating capability tokens: `par_hash` links each token to its parent's exact bytes, the holder is `cnf.jwk` with no `sub`, capabilities in `authorization_details` must narrow monotonically, verification is offline against a **configured root trust anchor**. Out of scope by its own text: revocation, and transport binding. No concept of declining to extend. `[待逐字查證]` |
| **`draft-sato-soos-mjwt-00`** — MyAuberge (single author), 2026-05-24 | `delegation_chain` plus **Cedar actions** written into the credential, a constant `human_principal_id` as authorization root, GEC signatures per hop. `[待逐字查證]` |
| **`draft-haberkamp-ipp-00`** (IPP) | Same problem, Ed25519 append-only chains. Read via HDP §2.5's comparison, not directly: IPP requires polling a central revocation registry and carries a "genesis seal" binding every token to the specification author's key at a URL. **Verify against IPP itself before repeating either claim** |
| **`draft-ietf-oauth-identity-chaining-17`** — OAuth WG, at IESG, 2026-07-19 | **The mature one, and it is not about this.** Token Exchange plus JWT grant to carry identity across trust domains. Cite for the shape of the gap the standards track leaves open — but `[待逐字查證]`: whether it states audit/accountability as out of scope, or simply does not mention them. **Those are different claims and may not stand in for each other** |
| `draft-sharif-agent-audit-trail-00` | A standard logging format for autonomous systems; adjacent, unread |

## §2.8 Vendor platforms — primary documentation

> **Added 2026-08-26.** A draft is a proposal; a shipped product is a decision
> already taken. Four vendors drew their boundary exactly where §1 says the
> three supports run out, and three of the four wrote it down themselves.
> Every quote here is from a primary document.

| Entry | Supports |
|---|---|
| **Microsoft Entra Agent ID** — `MicrosoftDocs/entra-docs`, `docs/agent-id/agent-identities.md` and `faq.yml`, read 2026-08-26 | **The agent-as-principal row should quote this, not characterise it.** "Agent identities can only be issued tokens in the Microsoft Entra tenant where they're created. **They can't access resources or APIs in other tenants.**" A multitenant blueprint does not cross: it "creates **tenant-local** agent identities… **The agent identities themselves always remain single-tenant.**" So one agent is two identities in two organisations with nothing joining them. Also from the FAQ, against responsibility attribution: audit logs "**don't distinguish agent identities from other Microsoft Entra identity types by default**… Operations initiated by agent identities appear as **service principals**." And the neighbour to handle rather than dismiss: Copilot Studio records the creating user as the agent's **sponsor** — one per agent for its lifetime, where a responsibility chain is one per piece of work |
| **A2A, "Enterprise-Ready Features"** — `a2a-protocol.org/latest/topics/enterprise-ready/`, read 2026-08-26 | **Closes the hand-off chain, and gives §6.1 its explanation.** "A2A delegates authentication to standard web mechanisms." and "A2A protocol payloads, such as `JSON-RPC` messages, **don't carry user or client identity information directly. Identity is established at the transport/HTTP layer.**" The second sentence is why authenticating the presenter must stay outside the door while the comparison stays inside. **Note the silence honestly**: the page does not say it excludes responsibility chains or cross-hop audit — it simply does not raise them, and the two quotes above carry the point without needing our inference |
| **Google agent identity** — `docs.cloud.google.com/agent-builder/agent-engine/agent-identity` | SPIFFE identity with an auto-provisioned X.509 certificate; "Unlike service accounts, agent identities are **not shared by multiple workloads by default, can't be impersonated**, and don't allow developers to generate long-lived service account keys." User delegation is 3-legged OAuth. **Cross-organisation is not discussed** — record as *not stated*, never as an exclusion |
| **AWS Bedrock AgentCore Identity** — `docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity.html` | Agent identities are workload identities; inbound IAM SigV4 or external-IdP JWT, outbound credential providers, to "access AWS resources and third-party services **on behalf of users**". One-hop on-behalf-of plus credential vaulting. Cross-account exists (Memory, 2026-06); cross-organisation and any multi-hop record do not |
| **IBM watsonx Orchestrate — Agentic Control Plane** (2026-06) | Centralised identity and credential management, policy enforcement, audit logging and isolation, governing "agents from any source with consistent policy enforcement and full auditability" **"across your entire enterprise environment"**. Its Agent Catalog is the closest thing to funduq's position inside one vendor. `[待逐字查證 — the announcement page returns 403; wording is second-hand and must not ship as a quote]` |

## §7 Federation precedents (one sentence each, from domain knowledge)

SMTP, XMPP, Matrix, ActivityPub — outbound-connection + federated-identity precedents supporting the `agent@funduq` direction.

## Where the receipts live

`reference/` — one file per source: who wrote it, when, **how far it has
actually been read**, and **the exact strings the draft quotes**, each with
the section it appears in and the claim it carries. This file is the map;
that directory is the receipt, and the split exists because "HDP concedes
single-key signing" is not checkable by anyone and the sentence with its
section number is.

Its status table is the honest count: **five of eleven sources are not yet
safe to ship**, including the one the introduction opens on.

## Pre-writing checklist

1. Verify every classical entry's exact bibliographic details.
0. **Clear every `[待逐字查證]` in §2.3, §2.7 and §2.8.** Read to date, verbatim
   and matched against the document: `draft-liu-oauth-chain-delegation-00` and
   HDP only. Everything else in those sections rests on a summary. A summary is
   not a quote, and **"does not say" may not stand in for "says it is out of
   scope"**.
2. Full-read the three flagged papers (InterruptBench; Will the Agent Recuse; Logic Monopoly).
3. Re-run all arXiv links; note versions cited.
4. Sweep arXiv cs.MA current listings once more the week of submission — this space moves weekly.
