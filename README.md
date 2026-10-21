# TalentSight

**TalentSight helps hiring teams find the right candidate faster by screening CVs, capturing interviews and turning both into one evidence-backed assessment.**

Recruitment Intelligence Platform for Candidate Screening and Interview Assessment.

Product name, positioning and rationale: [docs/TalentSight — Product Name & Positioning.pdf](docs/TalentSight%20%E2%80%94%20Product%20Name%20%26%20Positioning.pdf)

## What it does

TalentSight follows one candidate through the whole hiring process and keeps the evidence for every decision.

| Stage | What happens |
|---|---|
| Before the interview | The hiring team writes a job with an AI assistant (checked against company hiring policies), uploads CVs or imports them from a Google Form, and each CV is read against every requirement, scored out of 100 and ranked. The top candidates are invited in bulk with AI-written e-mails, holiday-aware times and Google Calendar entries. |
| During the interview | A browser video call (the candidate joins from an e-mailed link, no account), a live transcript with the interviewer and candidate kept apart, a side panel with the candidate's profile and score, and a question chat that helps the interviewer. |
| After the interview | The answers are analysed against the job requirements, and one consolidated assessment is built from the CV and the interview, with the evidence behind every conclusion, a PDF export and a side-by-side comparison of candidates. |

## Features

**Core (all six)**

| # | Feature |
|---|---|
| F1 | CV screening and requirement-based ranking: a verdict (met, partly met, unmet) with the CV line it rests on for each requirement; candidates missing a must-have are excluded with the reason shown |
| F2 | AI-based candidate scoring: four job-relevant dimensions with the job's own weights, a written reason for each, and the total worked out by plain arithmetic |
| F3 | AI-powered video interview: browser video room, session lifecycle, invite link for the candidate |
| F4 | Real-time speech recognition: live transcript, speaker-separated, timestamped, saved with the interview |
| F5 | Question and answer analysis: exchanges split from the transcript, scored on relevance, accuracy, completeness and articulation, and mapped to each requirement (explored, weak, not explored) |
| F6 | Consolidated assessment: one report with strengths, weaknesses, gaps and follow-up questions, each pointing to its evidence; PDF export and candidate comparison |

**Stretch (all four attempted)**

| # | Feature |
|---|---|
| F7 | Candidate identification and real-time profile overview: the profile side panel in the interview room, and a consent-based identity check (photo ID checked by a person, face templates from the call, a head-turn check on onboarding day). See [docs/README.md](docs/README.md) |
| F8 | CV claim verification: CV claims checked against the interview, shown as follow-up prompts for a person, never as accusations |
| F9 | Comprehensive interview scoring: one score in six weighted parts, each with a reason and the answer it rests on |
| F10 | Interview quality assessment: talk time, question types, follow-ups and requirement coverage, with recommendations that point to moments in the transcript |

Also built: a live question chat for the interviewer, a dashboard, candidate and interview lists with search, company sign-up with a company code, and candidate deletion.

**Innovation feature (F11)**

TODO-F11: name the feature, say what problem it solves and where to find it in the app (this section is required by the brief and must be written when the feature is built). The rationale document goes in `docs/`.

## Architecture

```mermaid
flowchart LR
  subgraph browser["Browser"]
    HR["Hiring team (React app)"]
    CAND["Candidate (join link, no login)"]
  end
  subgraph compose["Docker Compose"]
    WEB["web: nginx + React"]
    API["api: FastAPI + LangGraph agents"]
    DB[("db: PostgreSQL + pgvector")]
    LK["livekit: video server"]
  end
  HR --> WEB
  CAND --> WEB
  WEB --> API
  API --> DB
  HR -. video .-> LK
  CAND -. video .-> LK
  API --> GROQ["Groq (language model)"]
  API --> AAI["AssemblyAI (speech to text)"]
  API --> GOOGLE["Google: Blogger, Calendar, Forms"]
  API --> SMTP["Mail server (SMTP)"]
```

- **Eight LangGraph agents** do the AI work: job writing, CV screening, answer analysis, assessment, claim check, question chat, interview quality and interview scoring. In each one the AI proposes and plain code checks: scores are added up by code, every conclusion must name evidence that exists, and a failed check goes back to the AI once. Details and graphs: [docs/architecture.md](docs/architecture.md).
- **Long jobs run in the background** and show their progress (screening, answer analysis, assessment and the other reviews). A restart marks a half-finished run as interrupted instead of leaving it stuck.
- **Access is separated.** The hiring team logs in. A candidate only has their private interview link, which reaches nothing but their own join page; scores, rankings and assessments are never sent to a candidate.

## Technology stack

| Part | Choice | Why |
|---|---|---|
| API | FastAPI, SQLAlchemy | Required stack; typed requests, automatic API docs at `/api/docs` |
| Agents | LangGraph | Required stack; explicit steps, loops and a pause for human approval |
| Language model | Groq, `openai/gpt-oss-120b` | Free tier, fast, structured answers; temperature 0 and a fixed seed for repeatable results |
| Database | PostgreSQL with pgvector | One database for records, vectors and LangGraph checkpoints, with no extra service |
| Embeddings | fastembed (`bge-small-en-v1.5`) | Runs locally on the CPU; no candidate text leaves the machine for matching |
| Video | LiveKit (self-hosted in Compose) | Open-source WebRTC; nothing is recorded |
| Speech to text | AssemblyAI streaming | Free tier without a card; Google Speech-to-Text asked for one |
| CV reading | pypdfium2, python-docx, Tesseract OCR | Text PDFs, Word files and scanned CVs |
| Face matching | OpenCV YuNet and SFace (Apache 2.0) | Local; only numbers are kept, no pictures |
| Web | React 19, TypeScript, Vite, nginx | Typed UI, one small static container |
| Job posts | MCP server for Blogger | Keeps the Google publishing call outside the agent |
| Containers | Docker Compose | Single-command start |

## Prerequisites

- Docker Desktop (or Docker Engine with Compose v2) and Git
- Internet access for the first build (images, packages and two small face-model files are downloaded)
- A free Groq API key and a free AssemblyAI API key
- Optional: a Google OAuth refresh token (blog posts, calendar entries, Form import) and an SMTP account (invitation e-mails)

## Set up and run

```powershell
git clone https://github.com/rizvibjit/talent-sight.git
cd talent-sight
copy .env.example .env
```

On macOS or Linux use `cp .env.example .env`. Open `.env` and set at least the values marked **required** in the table below, then:

```powershell
docker compose up --build -d
```

Open <http://localhost:8080> and log in with `SEED_INTERVIEWER_EMAIL` and `SEED_INTERVIEWER_PASSWORD` from your `.env`. The API documentation is at <http://localhost:8080/api/docs>.

| Task | Command |
|---|---|
| Start (build first) | `docker compose up --build -d` |
| See the logs | `docker compose logs -f api` |
| Stop (data is kept) | `docker compose down` |
| Reset (**deletes all data**) | `docker compose down -v` |
| Run the tests | `docker compose exec api pytest -q` |
| Make 20 fictional sample CVs | `docker compose exec api python -m scripts.make_sample_cvs /data/cv_uploads/samples` then `docker compose cp api:/data/cv_uploads/samples ./sample-cvs` |
| Delete a candidate and all their data | `docker compose exec api python -m scripts.delete_candidate <id> --yes` |

Data lives in named volumes (`pgdata`, `cv_uploads`) and survives `docker compose down` and a restart.

### Letting a candidate join from another device

`http://localhost:8080` means "this computer" on any other device. For a candidate elsewhere you need a public `https` address for the app (browsers only give the camera and microphone to a secure page), `PUBLIC_BASE_URL` set to it, and a video server address the browser can reach (`LIVEKIT_URL`). For a demo on one computer, use two browser windows.

## Configuration reference

All settings come from `.env`. `.env.example` lists them with placeholders; the real `.env` is never committed.

| Setting | Needed | Meaning |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | **required** | Database account and name |
| `JWT_SECRET`, `JWT_MINUTES` | **required** | Login token secret (use a long random string) and how long a login lasts |
| `SEED_INTERVIEWER_EMAIL`, `SEED_INTERVIEWER_PASSWORD` | **required** | The first hiring-team account, created at startup |
| `GROQ_API_KEY`, `LLM_MODEL` | **required** | Language model key and model name |
| `SCREENING_MODEL` | optional | A different Groq model for CV screening only |
| `ASSEMBLYAI_API_KEY`, `STT_MODEL` | **required** | Live transcription |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | **required** | Video server keys (secret: 32+ random characters) |
| `LIVEKIT_URL`, `LIVEKIT_SERVER_URL` | **required** | Video address used by the browser, and by the API container |
| `PUBLIC_BASE_URL` | **required** | The address candidates open (default `http://localhost:8080`) |
| `COMPANY_NAME`, `SIGNUP_CODE`, `SIGNUP_EMAIL_DOMAINS` | optional | Company name in e-mails, and who may sign up |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | optional | Invitation e-mails; leave `SMTP_HOST` empty to copy links by hand |
| `AI_MAIL` | optional | `true` lets the AI word invitation e-mails; `false` uses fixed wording |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | optional | Google access for the features below |
| `BLOGGER_BLOG_ID`, `BLOGGER_BLOG_URL` | optional | Publishing job posts to a blog |
| `GOOGLE_CALENDAR_ID` | optional | Calendar for interview entries; empty = off |
| `GOOGLE_FORM_ID`, `GOOGLE_FORM_URL`, `GOOGLE_FORM_JOB_FIELD` | optional | Importing CVs from a Google Form |
| `INTERVIEW_MINUTES`, `INTERVIEW_GAP_MINUTES`, `INTERVIEW_WINDOWS`, `WORK_DAYS` | optional | Interview length, gap and working hours; holidays come from the PDF in `api/knowledge/holidays/` |
| `CV_MAX_MB` | optional | Largest CV file (default 5) |
| `BIOMETRIC_RETENTION_DAYS` | optional | How long face templates are kept (default 60) |
| `CAREERS_EMAIL` | optional | Address shown on public job posts |

## Using it

1. Log in. Press **Write a job with AI**, describe the role, answer the AI's questions if it asks, and approve the draft. Or press **New job** and fill the form yourself.
2. Publish the job. Add CVs on the job page (PDF or DOCX) or import them from the Google Form.
3. Press **Screen the new CVs**. The progress bar shows how far it is. The **Shortlist** tab lists passing candidates by score; **Excluded** shows who missed a must-have and why.
4. Open a candidate to see the score and its reasons, each requirement with its evidence, and the CV.
5. Press **Invite top candidates**. Each invitation has a private link for the candidate.
6. Both sides open the interview room. The transcript appears as people speak. The interviewer sees the profile panel and the question chat.
7. End the interview. On the candidate page, open **Interview** and run the answer analysis, the quality review and the interview score.
8. Open **Assessment** to build the consolidated report and export it as a PDF. Use **Compare candidates** on the job page to see assessed candidates side by side. **CV claims** shows what to follow up.
9. For a new hire, open **Onboarding** to run the identity check.

## Privacy

Details are in [docs/privacy.md](docs/privacy.md) and, for face data, [docs/README.md](docs/README.md).

- **Data used:** only the fictional sample CVs and mock interviews. No real candidate data is in the repository (`cv_uploads/`, recordings and database dumps are git-ignored).
- **Deletion (N19):** a candidate and everything about them can be deleted in the app, through `DELETE /api/candidates/{id}`, or with `scripts.delete_candidate`.
- **Minimisation:** raw audio and video are never stored. Face matching keeps at most three templates (numbers, no pictures) per interview, only with consent, for 60 days at most.
- **Logs (N22):** one JSON line per event with a fixed list of safe fields. Names, e-mail addresses, CV text, transcripts and prompts are never logged; invite tokens show as `***`.
- **Errors (N12):** an unexpected error shows a plain message, never a stack trace, path or prompt.

### Who receives candidate data (N18)

| Service | What it receives | Why |
|---|---|---|
| Groq (language model) | CV text, job text, transcript text and the prompts built from them | All AI analysis and writing |
| AssemblyAI | The live audio of the interview (both speakers) | Transcription. Check their data retention before using real interviews |
| Google (Blogger, Calendar, Forms) | The job post text (public); interview time and candidate name for the calendar entry; CVs submitted through the linked Form | Publishing, scheduling, import. Optional |
| Mail server (SMTP) | The candidate's address, interview time and link | Invitations. Optional |
| Hugging Face | Nothing about candidates. Two face-model files are downloaded when the image is built | Face matching |
| LiveKit | Runs in your own Compose stack. Video goes from the browsers to it and is not recorded | The video call |

### Fairness (N20)

- Scores come from four job-relevant dimensions weighted by the job's own settings. Age, gender, ethnicity, nationality, religion and marital status are not scoring inputs.
- The AI reads the whole CV, which can still contain such cues, and no model can be proved to ignore them. That is why every AI score shows its reasons and a person makes each decision.
- The only automatic rule is the must-have check, and the excluded candidate and the reason stay visible and can be reviewed.
- The interview chat and quality review block personal questions (age, family, religion and similar) with plain code, not only with the prompt.
- Face-matching accuracy varies between groups of people and with light and camera quality, so a result other than a match is sent to a person and never called fraud.

## Known limitations

- AI output is imperfect. The system is built for transparency: evidence, checks and a human decision, not for benchmark accuracy.
- Interviews and transcription are English only. Streaming transcription does not support Bengali.
- The Groq and AssemblyAI free tiers have per-minute limits. A large CV batch is slower when they are reached, and the free AssemblyAI tier allows 5 new streams a minute.
- One interview at a time was tested; the app is meant for local use through Docker.
- The candidate page shows the newest interview. Older interviews stay in the database but are not listed yet.
- The head-turn check stops a held-up photo or a replayed video. It does not stop a live face swap. The photo-ID check by a person is the main safeguard.
- Video for a candidate on another device needs the public setup described above.

## Measured performance (N1)

20 sample CVs were parsed, screened, scored and ranked in **<MEASURED> seconds** on `<date>` (Groq free tier, `openai/gpt-oss-120b`, `<machine>`). TODO: read the figure from "took N s" under the screening progress bar after a full run of the 20 sample CVs.

## Repository layout

```
api/        FastAPI app (app/), LangGraph agents (app/agents/), tests, helper scripts, knowledge PDFs
web/        React app and nginx config
livekit/    Video server config
docs/       Positioning, WBS, architecture, test plan, privacy, demo script
```

Documents: [architecture and agent design](docs/architecture.md) · [test plan and results](docs/test-plan.md) · [WBS actual vs planned](docs/wbs-actual-vs-planned.md) · [demo script](docs/demo-script.md)