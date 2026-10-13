Acceptance at the top of a long dependency chain repeatedly reloads upstream review records. The Blocked guard introduced in ADR-0021 ran outside a read scope, so a single decision accumulated quadratic review reads and building an Accepted chain accumulated cubic work.

Reuse `@read_scoped` around the existing guard. Its transaction, conditions, errors, and researcher Acceptance authority stay the same. The new regression accepts the top of 20- and 40-node chains and checks SQL/review-read growth through the public researcher decision path.

Validation: Standards and Spec audits found no issues. Independently reproduced the baseline regression (review reads 2166 -> 9126); the same test passes at this head. The production module AST is unchanged after removing the new decorator. Independent full suite: 1154 passed, 15 skipped; all three previously failing LaTeX tests passed in this run. Windows recovery remains for this PR's CI to verify. No model trial was run.

Related: #211 exposes the inherited Windows CI timeout; this PR contains the separate performance fix and does not change #211.
