# Candidate data and privacy

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
  answer analysis, assessment and CV claim check

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