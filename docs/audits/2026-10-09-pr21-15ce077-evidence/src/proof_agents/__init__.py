"""proof-agents: the automated proving framework on a proof map node — the Proof agent's roles (Prover,
Typesetter, Numerics: brief, permissions and write scope, `proof_agent`) and the run that works a node
as those roles in turn, a state machine the researcher starts, pauses, redirects and releases (`agent_run`);
the briefing every turn begins with (`briefing`), the patterns the record repeats (`patterns`), and the
Coordinator that works a Theorem's subtree through several runs (`coordinator`, ADR-0019 points 18–19).
It depends on proof-cli's domain and runs its turns on whatever agent manager it is given (latex-agent's)."""
