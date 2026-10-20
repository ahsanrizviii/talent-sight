## Identity check and face data (F7)

**What it stops:** one person sitting the interview and another turning up for the job.

**How it works**
- At the interview, the interviewer looks at the candidate's photo ID on camera and ticks "ID checked" and "the name matches the CV". This human check is the real anchor.
- With the candidate's consent only (asked on the join page, with an equal "continue without it" choice), three face templates are made from camera frames during the call: about 20 seconds, 3 minutes and 6 minutes in. A template is 128 numbers from OpenCV's SFace model (the face is found with OpenCV's YuNet). Both models are Apache 2.0. **No photo or video is ever stored**: pictures are read in memory and thrown away.
- On onboarding day, HR checks the original photo ID first. The new hire then looks at the camera and turns their head in a random direction (left or right), and a fresh picture is compared with the templates. The result is one of: match, low confidence, or no templates on file.
- Anything but a match pauses for a person: HR reviews and records "confirmed" or "not confirmed" with a note. **Nothing is ever called fraud automatically.**

**What is stored, for how long, and who sees it**
- Stored: the photo-ID ticks (who checked and when), the consent answer, at most three templates per interview, and the onboarding result. No images.
- Kept until the first of: the onboarding check (on a match, or when HR records a decision), `BIOMETRIC_RETENTION_DAYS` (default 60, set in `.env`), "Delete face data now" on the candidate page, or deleting the candidate (N19).
- Seen by the hiring team only (logged-in interviewers). The candidate sees only their own consent choice (N9). Logs never contain pictures or templates (N22).

**Limits (N17, N20)**
- Face matching accuracy varies between groups of people (skin tone, age, gender) and with light and camera quality. That is why the result is advice only and a person always decides.
- The head-turn challenge stops a held-up photo or a replayed video. It does **not** stop a live face swap (a real-time deepfake). The photo-ID check by a person remains the main safeguard.
- Voice, fingerprints and outside identity-verification services are out of scope.