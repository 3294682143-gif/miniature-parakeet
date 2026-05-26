# Controlled Weighted Voting / Verifier Scoring

This is NOT official evaluation.
This does not call external APIs by itself.
This does not enable final answer override by default.
This does not change default pipeline behavior.
This is a controlled preview layer for future hard-mode voting.

## Purpose
Preview scoring and voting metadata in hard-mode only.

## Scope
P15 metadata-only integration.

## Candidate Compatibility
Supports dict/CandidateAnswer/string.

## VerifierScore
Deterministic sub-scores with clamp [0,1].

## WeightedVoteDecision
Group by normalized answer and sum weights.

## Pipeline Preview Hook
Builds plan, scores, decision metadata.

## Why Preview Only
No final-answer override in P15.

## Trace Metadata
Adds weighted_voting_plan/effect/verifier_scores/weighted_vote_decision.

## Safety Boundaries
No API/.env/official_results.

## Limitations
Single-run candidate preview in pipeline.

## Next Steps
P16/P17 can decide controlled override policy.
