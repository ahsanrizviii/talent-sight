# Candidate data and privacy

This is the privacy and data-handling note (BID P2.7): which outside services receive candidate data,
what is stored and for how long, how a candidate is deleted, and the known fairness limits.

## Which outside services receive candidate data (N18)

| Service | What it receives | Why |
|---|---|---|
| Groq (language model) | CV text, job text, transcript text and the prompts built from them | All AI analysis and writing |
| AssemblyAI | The live audio of the interview, one stream per speaker | Transcription. Its own data retention applies |
| Google (Blogger, Calendar, Forms) | The job post (public); the interview time and candidate name for the calendar entry; CVs sent through the linked Form | Publishing, scheduling and import. Optional |
| Mail server (SMTP) | The candidate's e-mail address, interview time and join link | Invitations. Optional |
| LiveKit | Runs inside the Docker Compose stack. Video goes from the browsers to it and is not recorded | The video call |

Face matching (OpenCV) and the text embeddings (fastembed) run inside the API container. No face
picture and no CV text is sent anywhere for them.

## What is stored, and for how long (N16, N17)

| Data | Where | Kept until |
|---|---|---|
| CV file | `cv_uploads` volume | The candidate or the job is deleted |
| CV text, profile, verdicts, scores | Database | The candidate or the job is deleted |
| Transcript lines (text and times) | Database | The candidate is deleted |
| Analysis, assessment, claim check, interview score and quality, Litmus checks | Database | The candidate is deleted |
| Face templates (128 numbers each, no picture), at most three per interview, only with consent | Database | 60 days (`BIOMETRIC_RETENTION_DAYS`), or earlier when the candidate is deleted |
| Raw audio and video | Never stored | — |

Expired face templates are deleted each time the API starts. Everything else is kept until a person
deletes it: there is no automatic retention period, so a real deployment would need one.


## Deleting a candidate (N19)

A candidate and everything about them can be deleted in three ways. All three use the same code
(`api/app/privacy.py`), so they remove exactly the same things.

1. **In the app:** open the candidate and press **Delete candidate** at the bottom of the page.
2. **Through the API:** `DELETE /api/candidates/{id}` (interviewer login required).
3. **From the command line**, for an administrator without the web app:

```
   docker compose exec api python -m scripts.delete_candidate 12
   docker compose exec api python -m scripts.delete_candidate 12 --yes
```

   Without `--yes` it only lists what would be deleted. With `--yes` it deletes.

What is removed:

- the CV file on the `cv_uploads` volume
- the Google Calendar entry of each of their interviews (it carries the candidate's name)
- the candidate's row, and with it (ON DELETE CASCADE) their requirement verdicts, CV score,
  interviews, participant times, transcript lines, calendar records, invitation deliveries,
  answer analysis, assessment, CV claim check, Interview Assistant chat, interview quality and score, identity records, face templates,
  onboarding check, Litmus checks, round and hiring decisions, and the e-mails sent to them

Deleting a **job** deletes each of its candidates the same way, including their CV files.

Raw audio and video are never stored (Q&A 7), so there is nothing to delete for them.


## Logs (N22)

The API writes one JSON line per event. Only a fixed list of fields can appear in a line
(`SAFE_FIELDS` in `api/app/logging_setup.py`): event names, ids, counts, times and error types.
Names, e-mail addresses, CV text, transcript text, prompts and error messages are never written;
for an error only its type and the code line are kept.

Invite links are a candidate's private key to their interview, so their token is shown as `***`
everywhere a path is logged: in the API's own lines, in the web server lines of uvicorn, and in the
nginx access log (`/join/***`, `/api/invite/***/join`, `/api/ws/invite/***/audio`).
Known limit: when the API is down, nginx's *error* log can still print the full request line.

## Inputs and errors (N8, N12)

- Every request body is checked by a Pydantic model with lengths, ranges and allowed values;
  list filters accept only their known values. A wrong value gets a 422 with a plain message.
- CV uploads are checked before anything else: PDF or DOCX only, the file must really be one
  (its first bytes are checked), not empty, at most `CV_MAX_MB`; never more than that is read.
- Any unexpected error returns only "Something went wrong. Please try again." No stack trace,
  file path, setting or prompt reaches the browser.

## Secrets (N7, N14)

All keys and passwords come from `.env`, which git ignores. `.env.example` holds placeholders
only. `.gitignore` also keeps CV uploads, database dumps and audio files out of the repository.

## Fairness limits (N20)

- Scores use four job-relevant dimensions with the job's own weights. Age, gender, ethnicity,
  nationality, religion and marital status are never scoring inputs.
- The AI still reads the whole CV, which can contain such cues, and no model can be proved to ignore
  them. So every score shows its reasons, a person makes every decision, and Litmus tests the scorer.
  A steady Litmus result means no effect was found for its changes, not that the scorer is proven fair.
- The only automatic rule is the must-have check. An excluded candidate and the reason stay visible.
- The Interview Assistant and the quality review block personal questions (age, family, religion and
  similar) in plain code, not only in the prompt.
- Face matching is less accurate for some groups and in poor light, so anything other than a match goes
  to a person and is never called fraud.
