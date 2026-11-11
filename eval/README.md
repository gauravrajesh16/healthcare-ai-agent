# Evaluation

`python -m eval.run --gate` runs the 40 supplied multi-turn cases against a fresh mock service and writes `eval/report.json`. The command exits nonzero if the pass rate is below 90%. The 90% threshold is a minimum regression bar: a change should not regress more than four cases out of forty, and release approval should also review safety failures separately. The current fixture has conflicting expected outcomes for EV-23, EV-25, EV-34, and EV-37; these are itemized in `NOTES.md` and must not be made to pass by crossing tenant boundaries or inventing source data.

The harness checks expected fact substrings, key behavior constraints, and that confirmed grievance cases result in exactly one gateway write. It records per-case latency and tool counts. The report contains responses for audit/debugging and is synthetic-pack-only; do not run the same report format with real PHI without adding data redaction and access controls.

The report separately compares sample p95 latency with 3,000 ms. The quality regression gate does not mask an NFR latency failure; the report marks latency status independently. This sample is not a concurrent load test.
