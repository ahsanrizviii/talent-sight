# WBS: planned and actual (P2.5)

**Planned** is the original WBS in [`WBS - TalentSight_30219_Ahsan_Rizvi.xlsx`](WBS%20-%20TalentSight_30219_Ahsan_Rizvi.xlsx) (sheet *WBS*), written in Phase 1: 160 hours over 20 days. **Actual** is the time logged in Redmine against each task. The same table, task by task, is in the sheet *Actual vs Planned* of that workbook.

## Summary

| | Hours |
|---|---|
| Planned (original WBS) | 160 |
| Actual on the planned tasks | 165 |
| Actual on tasks added during the project | 25 |
| **Actual total** | **190** |

The planned tasks took 165 hours against 160 planned. The 25 added hours are almost all the four stretch features F7 to F10, which were not in the plan. The release task (15.5) is not yet logged.

## Module by module

| Module | Planned (h) | Actual (h) | Added tasks (h) | What changed |
|---|---|---|---|---|
| 1 Requirements and WBS | 24 | 24 | — | As planned |
| 2 Foundation and setup | 8 | 11 | — | Speech to text moved from Google to AssemblyAI after Google asked for a payment card (Risk 02). The interview-round tables were added to the schema later and logged under 2.4 |
| 3 Authentication | 4 | 4 | — | Company sign-up with a company code and allowed e-mail domains was added |
| 4 Job profile and JD assistant | 14 | 16.5 | — | Job posts are published through an MCP server to Blogger. The Library page was logged under 4.6 and later job-post changes under 4.7 |
| 5 CV screening (F1) | 13 | 13 | 1 | Google Form import was added as its own task (5.1.3) |
| 6 Scoring (F2) | 6 | 6 | — | As planned |
| 7 Video interview (F3) | 15 | 16 | — | The invite e-mail took longer than planned (Mailpit locally, SMTP for real e-mail) |
| 8 Transcription (F4) | 14 | 14 | — | As planned, with AssemblyAI streaming instead of Google |
| 9 Answer analysis (F5) | 14 | 12 | — | Seven planned tasks were done as five Redmine tasks: segmentation with small-talk classification, and mapping with scoring, were each built as one task |
| 10 Assessment (F6) | 8 | 8 | — | The background run and API were split out of the agent task |
| 11 Privacy and non-functional | 2 | 2 | — | Split into deletion (11.1.1) and validation and log review (11.1.2) |
| 12 Innovation feature (F11): Litmus | 10 | 10.5 | — | Built after the stretch features instead of before them |
| 13 Stretch features | 8 | 8 | 24 | The plan had one stretch item, the live question chat (built as planned). The four stretch features F7 to F10 were built as added tasks |
| 14 UI/UX refinement | 8 | 9 | — | The reference design took longer than planned |
| 15 Testing, documentation, release | 12 | 11 | — | The rehearsal was taken out of the presentation task. The release task (15.5) is done last |
| **Total** | **160** | **165** | **25** | |

## Tasks added during the project

| Module | Redmine task | Task | Actual (h) |
|---|---|---|---|
| 5 | 5.1.3 | Google Form applications and Drive import | 1 |
| 13 | 13.1.1 | F8 claim check agent and API | 3 |
| 13 | 13.1.2 | F8 CV claims tab | 2 |
| 13 | 13.3.1 | F10 interview quality agent and API | 4 |
| 13 | 13.3.2 | F10 interview quality card | 2 |
| 13 | 13.4.1 | F9 interview scoring agent and API | 4 |
| 13 | 13.4.2 | F9 interview score card | 1.5 |
| 13 | 13.5.1 | F7 consent, identity record and face matching | 4 |
| 13 | 13.5.2 | F7 identity check in the interview room | 2 |
| 13 | 13.5.3 | F7 onboarding check | 1.5 |

## Why the plan changed

- **Stretch features.** The plan had one stretch item, the live question chat, which was built as planned. All four stretch features of the BID (F7 to F10) were then built as new tasks added in Redmine (24 h).
- **Order of the work.** The plan built the innovation feature (module 12) before the stretch features (module 13). The stretch features were built first (19 and 20 October) and Litmus after them (23 October), because Litmus tests the finished screening agent.
- **Speech to text.** Google Speech-to-Text asked for a payment card, so the transcription tasks were done with AssemblyAI (Risk 02).
- **Later changes to finished modules.** The Library page, the interview rounds and the job-post changes were logged under the task they extend (4.6, 2.4 and 4.7).
- **Presentation.** The rehearsal was taken out of task 15.4; the deck and the demo script stayed.
