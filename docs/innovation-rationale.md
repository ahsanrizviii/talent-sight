# Innovation Feature (F11): Litmus — Rationale

## The problem

TalentSight ranks people with a language model. The model reads a CV and gives four scores, and those
scores decide who is shortlisted and who is invited. The BID asks us to keep personal attributes away
from the AI (N20), and the screening prompt tells the model to ignore them. But a rule in a prompt is a
promise, not a proof. Nobody in the hiring team can see whether the score of a candidate would have been
different if only their name, their contact details or their university had been different.

So today the platform can say "we told the AI to be fair", but it cannot show it.

## What Litmus does

Litmus tests the scorer the way a test suite tests code. For one candidate it:

1. Scores the unchanged profile twice, to measure how much the model's own scores move by chance (the noise band).
2. Makes controlled copies of the profile in plain code, each with exactly one identity detail changed:
   contact details removed, two different names, and university names removed.
3. Scores every copy with the same screening steps the real screening uses.
4. Compares the results in plain code. A copy is flagged only when a score moves by more than the noise band
   plus one 5-point step, or when the must-have check gives a different answer.
5. Puts every flagged result in front of a person, who must read it and acknowledge it with a note.
   Litmus never changes a score.

Every check is kept as its own record with the model, the prompt version, the number of AI calls, the tokens
used and the cost, so the team always knows what a check cost and what it was run against.

## Who benefits

- **Hiring managers** get evidence, per candidate and per job, that the shortlist rests on skills and
  experience. They can defend a decision with numbers instead of trust.
- **Candidates** are protected from being ranked lower for who they are.
- **The company** lowers its legal and reputation risk, and can show an auditor how the AI is checked.

## Why this over the alternatives

| Idea | Why it was not chosen |
|---|---|
| A short quiz during the interview | The platform already assesses the candidate in four ways (F5, F6, F8, F9). Another test of the candidate adds little. |
| Requirement Reality Check (which requirement excludes most strong people) | Useful, but it improves the job description, not the trust in the AI's judgement. |
| Talent-pool rediscovery | It is candidate sourcing (out of scope in the BID) and keeps candidate data longer (against N16). |
| Blind scoring for everyone | It hides the problem without measuring it. Litmus measures it. |

Litmus was chosen because it closes the one gap the other features cannot: every other feature
produces AI judgements, and Litmus is the only one that checks them. Its main limit:
a steady result means no effect was found for these changes, not that the scorer is proven fair.
