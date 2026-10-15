# Holiday calendar

Put the government's public holiday calendar PDF here (for example `Calendar_2026.pdf`), then rebuild:

```
docker compose up --build -d --remove-orphans
```

When the API starts it reads every PDF in this folder that it has not read before. It runs in the
background and takes about a minute for the Bangla calendar (OCR, then the AI lists the holidays).
Only public holidays are saved; optional ones are not. The interview planner never books a day on the list.
Saturday and Sunday are the weekend and are not taken from the PDF.

See what was found:

```
docker compose logs api | Select-String "holiday calendar"
```

A newer calendar for the same year replaces the older one's days. To read every file again:

```
docker compose exec api python -m scripts.reload_holidays
```
