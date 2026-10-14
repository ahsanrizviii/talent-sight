# Google Calendar for interviews

Once this is set up, scheduling an interview does three things on its own:

| Who | What they get |
|---|---|
| The hiring team | An entry on the company Google Calendar, with a link that opens the interview room. Moving the interview moves the entry; cancelling it removes the entry. |
| The candidate | The invitation e-mail carries a calendar invitation, so the interview appears in Gmail Calendar, Outlook or Apple Calendar on whatever device they use. A move or a cancellation updates it. |

The entry on the company calendar never contains the candidate's private link, because everyone who
can see that calendar could use it to join as the candidate. The candidate's link is only in the
candidate's own e-mail.

If Calendar fails (an expired token, no internet), the interview is still scheduled and the e-mail
still goes out. The interview card says what went wrong.

The calendar entry is switched on by one setting, so nothing here is needed to run TalentSight.

---

## 1. Give the Google token the calendar permission

The refresh token in `.env` (`GOOGLE_REFRESH_TOKEN`) was made for Blogger, Forms and Drive. Calendar is
a different permission, so the token has to be made again with all of them together.

1. Open <https://developers.google.com/oauthplayground>
2. Click the gear icon (top right). Tick **Use your own OAuth credentials** and paste your
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
3. In the Google Cloud console, open your OAuth client and add
   `https://developers.google.com/oauthplayground` to **Authorised redirect URIs**. Save.
4. In **Step 1**, paste these scopes (one per line) and press **Authorize APIs**. Sign in with the
   Google account whose calendar should hold the interviews:

```
https://www.googleapis.com/auth/blogger
https://www.googleapis.com/auth/forms.responses.readonly
https://www.googleapis.com/auth/drive.readonly
https://www.googleapis.com/auth/calendar.events
```

   If your existing token used different Blogger, Forms or Drive scopes, keep those and only add the
   last line. The point is: every scope the old token had, plus `calendar.events`.
5. In **Step 2**, press **Exchange authorization code for tokens** and copy the **Refresh token**.
6. Put it in `.env` as `GOOGLE_REFRESH_TOKEN=...`. Never paste it into a chat or commit it.

Also make sure **Google Calendar API** is enabled for the project: Cloud console, **APIs & Services**,
**Library**, search "Google Calendar API", **Enable**.

### Stop the token expiring every 7 days

If the OAuth consent screen says **Testing**, Google cancels the token after 7 days, and Blogger,
Forms, Drive and Calendar all stop at once. In the Cloud console open **Google Auth platform**,
**Audience**, and press **Publish app**. Google shows an "unverified app" warning when you sign in:
that is expected for an app only your own team uses. Make the token again after publishing, because a
token made while in Testing keeps its 7-day limit.

---

## 2. Switch it on

In `.env`:

```
GOOGLE_CALENDAR_ID=primary
INTERVIEW_MINUTES=60
```

`primary` means the calendar of the Google account you signed in with in step 1. To use a shared team
calendar instead, put its calendar ID there (Google Calendar, the calendar's settings, **Integrate
calendar**) and give that account permission to edit it.

Then:

```powershell
docker compose up -d
```

---

## 3. Check it

1. Open the account menu (top right), **Setup check**. **Google Calendar** should show a green tick
   and name the calendar.
2. Schedule an interview for a candidate whose e-mail address is one you can open.
3. The interview card says **Added to the company Google Calendar**, and the entry is in Google Calendar.
4. The candidate's e-mail has an **Add to calendar** card (Gmail) or an `invite.ics` file.
5. Reschedule the interview: both entries move. Cancel it: both disappear, and the candidate gets a
   cancellation e-mail.

| Message on the interview card | Meaning |
|---|---|
| "The Google token needs the calendar.events permission" | The token was made without it. Do step 1 again. |
| "Google Calendar was not found" | `GOOGLE_CALENDAR_ID` is wrong. |
| "Google sign-in failed. The refresh token may have expired." | See "Stop the token expiring". |
