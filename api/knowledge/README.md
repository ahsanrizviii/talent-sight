# Knowledge for the AI

`bjit-hiring-policies.pdf` holds the hiring policies the JD Agent follows (Module 4).
They are **demo policies** written for this training project, modelled on how BJIT is
likely to hire. They are not BJIT's official hiring policy.

How the PDF is read: every numbered heading ("1. Job levels and experience", "2. ...")
starts a new section, and each section becomes one searchable chunk. Text before
section 1 (title, version, note) is skipped. Keep this numbering when you edit the PDF.

After replacing the PDF, rebuild the image and reload the policies:

```
docker compose up --build -d api
docker compose exec api python -m scripts.reload_policies
```

Why policies at all: the change request asks the JD Agent to follow company hiring rules.
Keeping them in one document means you can show the exact rules, change one, and watch the
next draft change. The fair-hiring section also supports N20 (no protected characteristics).

## Skills reference documents (Module 9)

`skills/` holds short reference notes on the skills our jobs ask for (Python, SQL and PostgreSQL,
REST APIs and web frameworks, Docker, Git, data engineering, testing). The Evaluation Agent
compares a candidate's technical answers with them, so an accuracy score rests on written
documentation and not only on the AI's memory (Q&A 10). Each note was written for this project
from the official documentation named on its `Sources:` line.

Format: `# Skill` on the first line, a `Sources:` line, then `## Section` headings. Every section
becomes one searchable chunk. Add a file for a new skill area and rebuild; the table is matched to
the folder at every start. To force a full reload:

```
docker compose up --build -d api
docker compose exec api python -m scripts.reload_references
```
