# Proof Guardian / Proof Rubric

This is NOT official evaluation.
This does not call external APIs.
This does not change default pipeline behavior.
This does not force proof answers into boxed numeric format.
This does not override final_answer in P16.

## 1. Purpose
Provide deterministic proof-quality preview metadata for hard-mode proof scenarios.
## 2. Scope
Only hard-mode proof preview metadata; no solver rewrite.
## 3. ProofRubricScore
Rule-based structure/completeness/risk score.
## 4. ProofGuardianDecision
Complete/partial/invalid decision for preview.
## 5. Runtime Plan
`proof_guardian_plan` metadata in hard-mode proof.
## 6. Proof Complete / Partial / Invalid
Complete: reasoning+conclusion+score>=0.65; Partial: [0.35,0.65); Invalid: contradiction/empty/too low.
## 7. Boxed Answer Policy
Proof answers are not forced into boxed numeric format.
## 8. CLI Examples
Use strict hard-mode proof question with `--no-trace` for smoke.
## 9. Trace Metadata
Includes `proof_guardian_plan` and `proof_guardian_effect=preview_only`.
## 10. Safety Boundaries
No `.env`, no external API, no official result output.
## 11. Limitations
Heuristic only; may misclassify nuanced formal proofs.
## 12. Next Steps
P17/P18 can consume preview evidence in dry-run/demo.

证明题不应被简单数值 formatter 误伤；boxed 可以为空或只放结论；visible proof/reasoning text 才是主体。
