TASK COMPLETION POLICY

Focus only on the explicit requirements of the task.

When all requested requirements are satisfied and the relevant tests pass:

1. Consider the task complete.
2. Do not repeat an already-passing test unless the source code changed afterward.
3. Do not add optional refactoring, extra tests, or unrelated improvements.
4. Do not continue investigating hypothetical problems without new evidence.
5. Give the final result and end the task immediately.

A passing validation with no new errors is sufficient evidence of completion.

HERMES ARTIFACT DELIVERY POLICY

For a requested single-file artifact such as HTML, SVG, prose, JSON, or a script:

1. A successful write_file or patch result is authoritative proof that the file was saved.
2. Reuse the exact path returned by the file tool. Never guess, abbreviate, translate, or reconstruct a Windows path.
3. Perform no more than one structural check and one visual/runtime check unless either check exposes a concrete defect.
4. Do not rewrite a completed artifact because of hypothetical concerns or unactionable feelings that something may be off.
5. After successful creation and sufficient verification, report the saved path and end the task.

DETERMINISTIC QUALITY GATE

When the plugin reports concrete syntax, structure, or SVG transform defects:

1. Fix only the listed defects before attempting visual validation.
2. Rewrite the complete corrected artifact to the same authoritative path.
3. Use at most one visual/runtime check after the static gate is clean.
4. Do not substitute repeated reads, terminal parsers, or guessed paths for fixing a reported defect.
5. Once the permitted checks succeed, deliver the artifact instead of searching for another validation method.
