# Letting a real candidate join from their own device

By default TalentSight runs at `http://localhost:8080`. That address means "this computer", so an
invite e-mail sent to a real person contains a link that can only work on the machine that sent it.
Opening it anywhere else shows nothing.

Three things have to be true before a candidate on another device can join:

| What | Why |
|---|---|
| A public address for the site | `localhost` is not reachable from anywhere else |
| `https`, not `http` | Browsers only give the camera and microphone to a secure page |
| A video server the candidate can reach | The browser connects straight to LiveKit, not through the API |

This page sets all three up. Nothing here costs money and neither service asks for a card.

---

## 1. Give the site a public address (Cloudflare Tunnel)

A tunnel hands your local site a temporary `https://something.trycloudflare.com` address. No account,
no domain, no card.

1. Download `cloudflared` for Windows from
   <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
   and put `cloudflared.exe` somewhere on your PATH.
2. Start TalentSight as usual: `docker compose up -d`
3. In a second PowerShell window, open the tunnel and leave the window running:

```powershell
cloudflared tunnel --url http://localhost:8080
```

It prints a line like `https://brave-salmon-xyz.trycloudflare.com`. That is your public address.

**Keep that window open.** The address stops working when you close it, and you get a different one
next time. Make the tunnel before you schedule the interview, not after.

---

## 2. Use a video server the candidate can reach

The LiveKit container in `docker-compose.yml` listens on `localhost:7880`, which has the same problem.
The free LiveKit Cloud plan replaces it:

1. Sign up at <https://cloud.livekit.io> and make a project. The **Build** plan is free, includes
   5,000 participant minutes a month and asks for no card.
2. In the project, open **Settings → Keys** and make an API key. You get three values: the project
   URL (`wss://your-project.livekit.cloud`), an API key and an API secret.

---

## 3. Put the four values in `.env`

```
PUBLIC_BASE_URL=https://brave-salmon-xyz.trycloudflare.com
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_SERVER_URL=https://your-project.livekit.cloud
LIVEKIT_API_KEY=the key from LiveKit Cloud
LIVEKIT_API_SECRET=the secret from LiveKit Cloud
```

`PUBLIC_BASE_URL` is what goes into the invite link. `LIVEKIT_URL` is what the browser connects to,
and `LIVEKIT_SERVER_URL` is what the API uses to make and close rooms.

Then restart the API so it reads them:

```powershell
docker compose up -d
```

`.env` is never committed. Do not paste these keys into a chat, an issue or a commit.

---

## 4. Check it

1. Open your `https://….trycloudflare.com` address in a browser and log in. The site should look
   exactly as it does on localhost.
2. Schedule an interview for a candidate whose e-mail address is one you can open on your phone.
3. The invite card on the candidate's page should no longer warn that the link is local only.
4. Open the e-mail on your phone, on mobile data rather than wi-fi, and press **Join your interview**.
   The camera and microphone permission prompt should appear.

If the page loads but the video never connects, `LIVEKIT_URL` is still pointing at localhost.
If the page does not load at all, the tunnel window has been closed.

---

## Back to local-only work

Delete those five lines from `.env`, or set `PUBLIC_BASE_URL=http://localhost:8080`, and run
`docker compose up -d` again. Everything goes back to the local LiveKit container. Invitation
e-mails still go out for real, but their links will only open on this computer.
