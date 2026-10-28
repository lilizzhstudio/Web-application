# Lilizzh Studio 6.0 — secure Python backend

Your website looks and works the same, but **passwords, payment details and business rules now live on a
Python server**. The browser only ever receives what the signed-in person is allowed to see.

## What changed (and why)

| Before (in the page source) | Now |
|---|---|
| Admin passwords, editor PINs and client passwords written in the HTML | Nothing secret in any file the browser downloads. Passwords are checked on the server and stored only as scrypt hashes |
| Login "hint" showed the editor's PIN; PIN was pre-filled in the form | Removed. Wrong logins get one generic message |
| Anyone could read/edit all orders (public database) | Each person gets only their own orders; every change is validated on the server |
| Clean 4K master link sent to every browser, "locked" by a CSS overlay | Link is sent only after the admin unlocks the order |
| Bank / UPI details in the HTML | Stored in `.env`; sent only to the signed-in client who owns an unpaid order |
| Logins saved in `localStorage` | Random session cookie, `HttpOnly`, never readable by page scripts |
| Unlimited password guessing | Lock-out after repeated failures (per account and per address) |

Also added: CSRF protection, upload type/size limits, security headers (CSP, nosniff, no-framing), and
Firebase removed entirely (uploads and chat now go through your own server).

## Start it (5 minutes)

```bash
pip install -r requirements.txt
python manage.py init        # creates .env, your admin login, random editor passcodes (shown once)
python manage.py run         # http://127.0.0.1:8000
```

`init` asks for your admin e-mail and a password you choose (12+ characters). It prints each editor's
passcode **once**; give each editor theirs. Reset any time with
`python manage.py set-editor-passcode ed-1 --random`.

Want the two sample clients/orders from the original design? `python manage.py seed-demo`.

## Important: your old passwords are burned

`lilizzh@7218`, `admin123`, `password123` and the editor PINs were visible to anyone who opened the site.
Do not reuse them anywhere (the server refuses `lilizzh@7218` and `admin123` outright). If those passwords
protect any other account (e-mail, UPI app, hosting), change them now.

## Going live

1. Host somewhere with HTTPS (Render, Railway, a VPS with Caddy/nginx…).
2. In `.env`: `APP_ENV=production`, keep `SECRET_KEY`, fill `PAY_*`, add `TRUST_PROXY=1` if behind a proxy.
3. Keep `data/` on a persistent disk and back it up (it holds the database and uploaded files).
4. Run `python manage.py check` — it lists anything still unsafe.

## Behaviour changes you may notice

* The public **rate card no longer shows "Editor Payout" and "Studio Profit"** (your margins). To show them
  again set `PUBLIC_RATE_CARD_SHOWS_MARGINS=1` in `.env`. Admin always sees them.
* Editors no longer see price-negotiation or payment messages in a project chat.
* UTR numbers can't be reused across orders; uploads accept video, audio, image, LUT, subtitle, PDF, ZIP.
* The "Direct Inquire" form now really saves the inquiry: `python manage.py inquiries`.

## Editing the website

The readable source is `frontend-src/app.jsx`; the browser runs the compiled `frontend/app.js`.
After editing: `npm install && npm run build`.

## Tests

`python -m unittest discover -s tests -v` (31 security tests: logins, permissions, forged fields, uploads…).

## Known limits

* Login lock-outs are kept in memory, so run a single server process (fine for this site's scale).
* The UPI QR image is still drawn by `api.qrserver.com` (as in your original), which sees the UPI ID
  and amount. Replace with a local QR generator if that matters to you.
* The page still loads Tailwind/Lucide from public CDNs; pin or self-host them for stricter control.
