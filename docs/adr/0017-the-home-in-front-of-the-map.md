# The Home: the researcher's projects, in front of each project's map

**Status**: accepted. Amends ADR-0011 point 1: the web app's first page is the Home, a list of the researcher's projects; a project's proof map page is reached from it. ADR-0011's one-origin-per-project model and everything on a project's page are unchanged.

## Context

ADR-0011 made the proof map web app the researcher's one entry, but its server is one project per process, bound to that project's own port, started with `proof map open` *inside the project's folder*. A researcher with several projects (a paper's main theorem, a side question, last year's notes) had no page that listed them, no way to move between them in the browser, and had to remember each folder and go to a terminal to open it. prism-local had such a Home with a port registry and a launcher; ADR-0011 left those out on the grounds that "proof-cli's own server and map do those jobs", which was true of one project and not of the researcher's shelf of them.

## Decision

1. **The web app opens on the Home.** `proof home` opens it (starting it in the background if need be; `--foreground` runs it in the terminal). It lists the researcher's projects as cards, each read live from its own database: its id and folder, its theorem, how many nodes, how many on the frontier, how many await the researcher, how many accepted, the open fog, whether its page is being served, when it was last opened. Opening a card serves that project's page and moves the browser there; the project page's sidebar links back to the Home.

2. **A project page keeps its own origin.** The Home is one more local server, on one fixed localhost port the same for every project (`home_origin()`), with the same Host and Origin checks as a project page. It does not serve project pages under a path prefix: each project's `ReviewServer` is still bound to the project's own port, derived from its instance id as before, so browser storage, the studio's locks and channels, and every existing route stay keyed by origin. The Home runs those servers inside its own process (`ProjectHub`), one per opened project, and uses a page already answering on the project's origin (a `proof map serve` in a terminal) as it is.

3. **The list is a user-level file, not a scan.** `projects.json` in the proof-cli config directory (`$PROOF_CLI_CONFIG_HOME`, else `$XDG_CONFIG_HOME/proof-cli`, else `~/.config/proof-cli`) holds one entry per project path, with when it was added and last opened; nothing about a project is copied there. A project is listed when `proof init` starts it, when its map is served or opened, and when it is added or created on the Home. The Home's **Add existing…** lists a folder that already holds a project and refuses one that doesn't; **New project…** starts one as `proof init` does (and opens it); **Forget** drops a folder from the list and never touches it. A folder that is gone, or no longer holds a project, is still listed, saying so, until it is forgotten. Nothing scans the disk.

4. **`proof map open` goes through the Home.** It lists the project, starts the Home if none answers, asks it to serve the project, then opens the browser at the project (or node) as before, so the page it opens has its way back to the Home. Without a Home (it couldn't start), the page runs on its own exactly as before, and shows no Home link. `proof map serve` is unchanged: one project, in the foreground, no Home.

5. **The Home writes nothing in any project.** Its writes are the list itself and `create`, which calls the same `ensure_project` as `proof init`. Opening, listing and reading cards make no Review decision and change no node; the Home is outside ADR-0004's and ADR-0007's permission split altogether. Listing a folder never starts a project in it (`read_only`).

## Consequences

- One more page and one more fixed port; one background process (`proof home --foreground`) that hosts the project pages. Closing it closes every page it served. A page started by `proof map serve` is independent of it.
- The researcher's mental model becomes: projects, then a project's map, then a node's studio. The project page's title and sidebar say which project they are in.
- The CLI's `--root` convention (ADR-0011 point 8) is untouched: agents still run `proof` in a project, and nothing on the Home is agent-reachable.
- Two Homes can't run at once (the port is fixed); a second `proof home` finds the first.
- `src/proof_cli/studio/README.md`'s "left out" note on prism-local's Home no longer means the job isn't done: proof-cli has its own Home, written for its own project model rather than taken from upstream.
