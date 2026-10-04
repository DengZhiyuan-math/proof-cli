"""proof-agents: the automated proving framework on a proof map node — the Proof agent's roles (Prover,
Typesetter, Numerics: brief, permissions and write scope, `proof_agent`) and the run that works a node
as those roles in turn, a state machine the researcher starts, pauses, redirects and releases (`agent_run`).
It depends on proof-cli's domain and runs its turns on whatever agent manager it is given (latex-agent's)."""
