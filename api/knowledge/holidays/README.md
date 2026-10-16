# Holiday list

`bangladesh-public-holidays-2026.pdf` lists the 2026 government public holidays (general and
executive-order holidays), with normal, selectable English text. The interview planner never
books a day on it. Saturday and Sunday are the weekend and are not listed.

When the API starts it reads every PDF (or .txt) here that it has not read before, in the
background: the text is stored in pieces with embeddings (RAG), the pieces about holiday dates go
to the AI, which lists the holidays, and plain code checks the list against every date written in
the file. A changed file is read again and replaces the days of its year.

For 2027, add a PDF the same way: one row per holiday with the full date (`21 October 2027`).

The government's Bangla wall calendar cannot be used directly: its text is in an old non-Unicode
font and the page is a poster, so reading it with OCR mixed the calendar grid into the holidays.

See what was read:

```
docker compose logs api | Select-String "holiday"
```

To read every file again: `docker compose exec api python -m scripts.reload_holidays`
