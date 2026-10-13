Closes #202.

`proof reference edit <id> … --reason …` fixes a citation's bibliography in place (audit section 2).

- `edit_reference` (new `src/proof_cli/reference_edit.py`): a partial update of the `ReferenceRecord` under the same id, written with `store_reference` in one transaction. A field not given keeps its value. `id`, `created_by` and `created_at` never change.
- Editable: title, authors, year, source type, origin, bibliographic source, identifier, URL and notes.
- Each change is one `reference_edited` event naming the editor (`--by`, default `PROOF_AGENT_NAME`, else human), the reason and the old and new value of each changed field. An edit that changes nothing records nothing. A real change with no reason is refused with `REFERENCE_EDIT_REASON_REQUIRED`.
- Refused with `REFERENCE_FIELD_NOT_EDITABLE`:
  - An imported result's statement, `source_locator`, `source_version` and `reference_id`, since they are its mathematical interface (ADR-0005). The message says to cite another work or version as a new imported result. The CLI accepts these as hidden options only so that it can refuse them with the code.
  - Any field outside the bibliography (`id`, `created_by`, the legacy review fields).
- Also new: `REFERENCE_TITLE_REQUIRED`. `INVALID_SOURCE_TYPE` is reused.
- `get_reference` takes an optional `conn`.

## Acceptance

- [x] Partial edits keep the other fields, and the event records the old and new values and the reason: `test_a_partial_edit_keeps_the_other_fields…` and `test_the_cli_edits_in_place…`.
- [x] Editing a field of the mathematical interface is refused with an error code. Tested for each of the four fields through the CLI; neither the citation nor the node changes and no event is written.
- [x] A researcher's import meets a DOI rule once its identifier is added (its dependent goes from blocked to open) and stops meeting the rule when the DOI is removed: `test_a_researchers_import_meets_a_doi_rule…`.

ADR-0022's restriction to the researcher's own imports is not implemented on this branch (`trust_rules_of` does not check the node's `created_by`), so this PR adds no agent-import test. It belongs with the ADR-0022 change.

## Tests

- `tests/test_reference_edit.py`: 16 tests, all passing.
- With references, trust rules and the CLI contract: 108 passed.
- Full suite at `2f7c246`: 1123 passed, 15 skipped, 3 failed. The same 3 also fail on the base `b7f3943`: there is no local pdflatex, so the build uses Tectonic, which needs the network.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
