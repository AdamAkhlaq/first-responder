# Architecture Decision Records

These record the decisions that shape first-responder — the context, the choice, and the consequences — so the reasoning survives even when the conclusion looks obvious in hindsight. Format follows Michael Nygard's lightweight ADR style.

| #                                       | Decision                                              | Status   |
| --------------------------------------- | ----------------------------------------------------- | -------- |
| [001](001-synthetic-fault-injection.md) | Synthetic fault injection as the ground-truth source  | Accepted |
| [002](002-tools-as-contract.md)         | Tools layer as the sole agent–world contract          | Accepted |
| [003](003-single-agent.md)              | A single agent, not a multi-agent architecture        | Accepted |
| [004](004-evaluation-methodology.md)    | Evaluating a non-deterministic agent: N-trial scoring | Accepted |

New decisions get the next number and never edit an accepted record — they supersede it with a new one, so the history stays intact.
