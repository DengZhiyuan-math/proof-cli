# T8 real-provider result

The primary trial ended automatically after 87.6 minutes and 40 provider turns, including three structure turns. The fixed limits were 60 turns and 120 minutes. All 40 provider processes returned exit 0. The actual model was `claude-opus-5-5`. No researcher input followed Start.

The project loop reports `done`. Its Theorem result is `stuck`: nothing left to work without the researcher: sobolev-embedding-general, sobolev-embedding-cuspidal, sobolev-embedding-residual rest(s) on what no run will settle (parked: main-theorem, height-vs-distance).

The Reader created 18 nodes. The final map has 24 nodes: ten imports, one Theorem, seven Lemmas, and six Claims. It has 15 unfixed Definitions, 12 open Fog items, and nine open Standing questions. Seven proof nodes are Provisional. All 24 nodes remain unreviewed, and all ten imports await Reference review.

## Recorded proof state

A Verifier pass records the model's check. It does not establish researcher Acceptance. The decomposition Lemma's older pass is withheld from Provisional status after its structure changed.

| Node | Kind | Latest Verifier verdict | Provisional | Current status |
|---|---|---|---|---|
| complementary-series-model | claim | passed | yes | Blocked |
| cuspidal-exceptional-finite | claim | — | no | Parked |
| exceptional-cuspidal-finite-per-level | claim | passed | yes | Awaiting review |
| height-vs-distance | lemma | — | no | Parked |
| hilbert-space-decomposition | lemma | passed (before resplit) | no | Blocked |
| main-theorem | theorem | — | no | Parked |
| matrix-coefficient-decay-p | lemma | passed | yes | Blocked |
| matrix-coefficient-decay-product | lemma | passed | yes | Blocked |
| real-complementary-decay | claim | passed | yes | Awaiting review |
| real-unitary-dual-ktypes | claim | passed | yes | Awaiting review |
| smooth-vector-exceptional-support-finite | claim | passed | yes | Blocked |
| sobolev-embedding-cuspidal | lemma | — | no | Blocked |
| sobolev-embedding-general | lemma | — | no | Blocked |
| sobolev-embedding-residual | lemma | — | no | Blocked |

The complementary-series proof failed its first verification on three points. Prover and Typesetter revised it. Verifier then passed it. Both verdicts remain in the work log.

## Parked reasons

These are model-reported objections, preserved for researcher review. They are not independent mathematical conclusions.

**cuspidal-exceptional-finite**

needs-human: The claim cannot be proved with known mathematics. For irreducible Gamma (the only reading the setting allows) it is equivalent to finiteness of exceptional Maass cusp forms across the p-power level tower, which is open; Selberg's conjecture would imply it. For reducible Gamma it is false. The researcher must choose what this node states: (a) the provable uniform gap sup_{Z^0_+} s <= 1/2+7/64 (Kim-Sarnak), (b) an explicit hypothesis on Gamma, or (c) conditional on Selberg's conjecture. Details are in scratch/proof-draft.md.

**height-vs-distance**

needs-human: The node statement is false as written, not ambiguous (scratch/proof-draft.md). (1) Gamma=SL_2(Z[1/p]), g_p=1, admissible bounded p-adic metric min(d_p,1): d_X((diag(p^k,p^-k),1),x_0) stays bounded while ht>=p^{2k}. (2) Doubling both metrics doubles d_X, so at most one metric scaling can satisfy it. (3) Conjugating Gamma by (h_inf,1) makes ht identically +inf. The researcher needs to choose a corrected statement. Proposal R2, proved in the draft: Gamma=SL_2(Z[1/p]), K_p=SL_2(Z_p); ht(Gamma(g_inf,g_p)) = y(delta_inf g_inf i) ≍ exp(hyperbolic distance in SL_2(Z)\H), i.e. d_X replaced by the fibre distance with g_p frozen. This is also what the Sobolev-embedding use and fog-2 need. Alternatively, restrict Gamma and fix specific metrics, but then the exponent only matches for one tuned normalisation.

**main-theorem**

needs-human: No split. The statement is false as written: its p-adic factor nu_p(B_p(p^n))^{-1/2} Xi_p(a_n)^{kappa_p} is beaten by an L^2 lower bound (fog-10). For Gamma=SL_2(Z[1/p]), W=K_p, f a lifted Hecke-Maass form and T fixed, ||A_B f||_2 >> nu_p^{-1/2} infinitely often in n, while the claim forces an extra Xi_p(a_n)^{kappa_p}. The researcher must choose the intended p-adic factor. Likely intended: B_p(p^{2n}) with factor Xi_p(a_n)^{kappa_p}, proved by thickening. A split for that reading is drafted in scratch/decomposer/notes.md.

## Queue, refresh, and restart

The 68 queue entries contain 39 unfixed statements/Definitions, three parked nodes, ten imported results, seven Provisional nodes, and nine Standing questions. Parked node entries come first in dependency depth order. Other node entries follow in dependency depth order. An unfixed Definition may precede the first node that names it.

The complete queue and Reader departures were identical after refresh and after the separate server restart. All stored nodes, Definitions, Fog, questions, work logs, and proof marks were identical. No additional provider calls occurred. The node studio retained enabled `Start agent` and single-role `Start` controls. The completed global view had `can_pursue=false` before and after restart.

Live `run` overlays for the three parked nodes disappear on restart. The coordinator view becomes idle with counters at zero; historical stop reasons and counters remain in the work log and primary snapshots. This report does not claim identical live-controller views.

## Resource evidence

Backend totals: 21,472,006 input tokens (including cache creation/read counts), 569,653 output tokens. No price is inferred. `real-provider-events.jsonl` contains every init and completion. The failed first-profile attempt is recorded separately and is excluded from these totals.

See `real-trial-summary.json`, `real-reader-map.json`, `reader-comparison.md`, `real-project-details-before-restart.json`, `real-map.json`, `real-queue.json`, and the browser captures. The source and hand-script hashes are in `real-trial-preflight.json`.
