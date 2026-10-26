# WBS: planned and actual

The full plan is in `WBS - TalentSight_30219_Ahsan_Rizvi.xlsx`: 160 hours over 20 days (24 hours in Phase 1, 136 hours in the 17 development days). This page compares that plan with what happened.

The **actual** column comes from the commit history: the dates on which each module's work was committed and the number of commits. Hours spent per task are logged in Redmine.

## Module by module

| Module | Planned (h) | Planned (days) | Actual: committed on | Commits | What changed |
|---|---|---|---|---|---|
| 1 Requirements and WBS | 24 | 3 | 1 – 5 Oct | 6 | As planned (24 h logged in Redmine). The architecture and LangGraph diagrams were committed on 5 Oct, at the start of development |
| 2 Foundation and setup | 8 | 1 | 5 – 7 Oct | 13 | Speech to text moved from Google to AssemblyAI after Google asked for a payment card (Risk 02). Tables for interview rounds were added on 25 Oct |
| 3 Authentication | 4 | 0.5 | 7 Oct | 2 | Company sign-up with a company code and allowed e-mail domains was added |
| 4 Job profile and JD assistant | 14 | 1.75 | 7 – 9 Oct | 16 | Job posts are published through an MCP server to Blogger; hiring policies are matched with RAG. Later: the Library page (23 Oct) and the hiring process in the JD chat (25 Oct) |
| 5 CV screening (F1) | 13 | 1.625 | 8 Oct | 10 | Scanned CVs read with OCR; Google Form import added. On 25 Oct a failed re-screen was changed to keep the earlier result |
| 6 Scoring (F2) | 6 | 0.75 | 8 – 9 Oct | 7 | As planned |
| 7 Video interview (F3) | 15 | 1.875 | 12 – 14 Oct | 19 | Added Google Calendar entries, a setup-check page, e-mail invitations and the profile side panel. Interview rounds and round-aware e-mails were added on 25 Oct |
| 8 Transcription (F4) | 14 | 1.75 | 13 Oct | 6 | As planned, with AssemblyAI streaming |
| 9 Answer analysis (F5) | 14 | 1.75 | 16 Oct | 6 | As planned; a skills reference knowledge base added |
| 10 Assessment (F6) | 8 | 1 | 16 – 17 Oct | 7 | PDF export and candidate comparison included. On 25 Oct the assessment was changed to use every interview round and to judge HR rounds on HR topics |
| 11 Privacy and non-functional | 2 | 0.25 | 19 Oct | 3 | Deletion, log hygiene and input validation completed |
| 12 Innovation feature (F11) | 10 | 1.25 | 23 Oct | 7 | Litmus: a check that a CV score rests on the CV, not on who the candidate is. Built after the stretch features instead of before them |
| 13 Stretch features | 8 | 1 | 19 – 20 Oct | 14 | Grew from one chat feature to F7, F8, F9, F10 and the Interview Assistant chat. Re-planned in Redmine at 43 h. The onboarding check was simplified on 23 Oct |
| 14 UI/UX refinement | 8 | 1 | 21 – 25 Oct | 9 | Loading and error states, wording and the product name as planned. The job page was rebuilt around five stages, with Results and Identity check screens |
| 15 Testing, documentation, release | 12 | 1.5 | 21 – 26 Oct | 4 | 582 tests pass. 20 CVs screened in 13 minutes (N1). Started on a second machine. The rehearsal was taken out of the presentation task and is done separately. The `v1.0-final` tag is the last step |
| **Total** | **160** | **20** | **1 – 26 Oct** | **129** | |

Another 9 commits belong to the added work listed below (6 for the visual redesigns, 3 for the hiring-flow upgrades). The 2 commits of 27 Sep only created the empty repository and are not counted.

## Order of the work

The plan built the innovation feature (module 12) before the stretch features (module 13). In practice the stretch features were built first, on 19 and 20 October, because the Core features were finished early and the innovation idea was chosen only after the whole platform could be seen working. Litmus was then built on top of the finished screening agent, which it tests.

## Work added during the project that was not in the WBS

- Hiring-flow upgrades (15 and 16 Oct): bulk invitations, AI-written invitation e-mails, a holiday calendar read with RAG, and interview settings
- Interview rounds (25 Oct): a hiring process per job, Technical and HR rounds, closing a round by pass mark or top N, next-round invitations, rejection and "interview not held" e-mails, and document checks at onboarding
- A workspace view across all jobs: dashboard, candidate list with search and CSV export, interview list
- Three visual redesigns before the final theme (7, 13 and 18 Oct)
- Candidate deletion for a whole job, and an administrator script

## Why the plan changed

The Core features came in under their estimates. That left time for all four stretch features. The hiring-flow and round work was added because an interview needs real invitations and a real hiring process to be demonstrable.
