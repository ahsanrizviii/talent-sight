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
  answer analysis and assessment

Deleting a **job** deletes each of its candidates the same way, including their CV files.

Raw audio and video are never stored (Q&A 7), so there is nothing to delete for them.