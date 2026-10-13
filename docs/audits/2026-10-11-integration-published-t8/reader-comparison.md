# Reader map versus the saved hand map

This compares the Reader's completion snapshot in `real-reader-map.json` with the exact saved `setup-tier3-horo.sh`. The input and script hashes are in `real-trial-preflight.json`. It describes choices and scope; it does not validate either map's mathematics.

| Aspect | Hand map | Real Reader map |
|---|---|---|
| Nodes | 6: one Theorem, two Lemmas, three imports | 18: one Theorem, seven Lemmas, ten imports |
| Definitions | 6 | 15 |
| Fog | 5 items | 9 items |
| Lattice | Fixes SL₂(Z[1/p]) | Uses an irreducible non-cocompact lattice in SL₂(R) × SL₂(Qp) |
| Main target | Separates the real pointwise bound from a p-adic L² gain; the real bound uses the maximum height over the p-adic averaging ball | States one combined pointwise bound with a p-adic decay factor; the Reader records that this factor is not derived and the starting-point/height control is open |
| Auxiliary structure | Height and arithmetic fibre identification | Hilbert-space decomposition, height comparison, three Sobolev lemmas, and two matrix-coefficient lemmas |
| Imports | Strömbergsson effective equidistribution, property τ decay, SL₂ reduction surjectivity | Ten source/background nodes for spectral structure, real Sobolev bounds, Burger operators, p-adic representation theory, CHH, and EMMV |
| Source qualification | Requires researcher Reference review | All ten Reader imports remain unreviewed; the Reader says only EMMV was read from the work itself |

The Reader completion took about 9.2 minutes in one Reader turn. The CLI reports 2,426,998 input tokens (including cache tokens as counted by the backend) and 54,253 output tokens. The model is `claude-opus-5-5`.

The source's main theorem has an empty statement. The Reader supplied one from the proof's concluding estimates. Its departures record explicitly lists these changes: corrected the height; added irreducibility and mean zero; chose the averaging normalization and index meaning; changed the p-adic exponent; dropped a nondecaying `1+` term; and converted two attributed S-adic statements into local lemmas over imported real/single-place results. The nine fog entries retain the unresolved p-adic gain, height motion, initial-point conditions, spectral decomposition, source qualifications, and the absent first proof.

The Reader preserved a general setting rather than adopting the hand map's arithmetic specialization. The hand map's fibre lemma and reduction-surjectivity import therefore have no direct counterpart. The Reader's larger map follows more of the draft's representation-theoretic proof outline.

These choices remain unfixed and unaccepted. The Reader's own source-read claims in `scratch/reader/departures.md` are provenance, not a researcher Reference review. Mathematical assessment of the supplied main statement, its extra assumptions, and the imported statements remains with the researcher.
