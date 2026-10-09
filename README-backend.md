# Elimu Fund API

This workspace now includes a dependency-free Python API backed by SQLite. It is intended for local development and frontend integration—not deployment with real student identity information until it has received a security, privacy, and operational review.

## Run locally

Keep the existing static-site task running on `http://127.0.0.1:5173`, then start another terminal in the workspace and run:

```powershell
C:/Users/Administrator/.local/bin/python3.14.exe server.py
```

The API listens on `http://127.0.0.1:8000`. The SQLite database file `elimu_fund.sqlite3` is created automatically from [database/schema.sql](database/schema.sql) and is ignored by Git. The schema defines student accounts, hashed-token sessions, bursary cycles, applications, and application timeline events. Set `ELIMU_DB_PATH` to choose another database path. Tables and indexes are initialized idempotently whenever the API starts; no sample students or unconfirmed bursary cycles are inserted.

The frontend API client in `api.js` uses that API address by default. Before opening the HTML pages, serve the workspace over HTTP (rather than opening the files directly) so browser credentials and CORS behave consistently.

## Run backend tests

From the workspace root, run:

```powershell
C:/Users/Administrator/.local/bin/python3.14.exe -m unittest discover -s tests -v
```

The tests use temporary SQLite databases and an ephemeral local HTTP port. They cover account registration and duplicate handling, password sign-in, session expiration/logout, profile authorization and validation, cycle/application rules, timeline access ownership, malformed JSON, and disallowed browser origins.

## Endpoints

All request and response bodies are JSON. Authenticated routes use an HTTP-only, `SameSite=Lax` session cookie. The browser client sends credentials automatically.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/auth/register` | Create a student account and sign in |
| `POST` | `/api/auth/login` | Sign in using a Kenyan phone number or email |
| `POST` | `/api/auth/logout` | Revoke the current session |
| `GET` | `/api/me` | Read the current student's profile (identity number is masked) |
| `PATCH` | `/api/me/profile` | Update editable profile fields |
| `GET` | `/api/cycles` | List configured application cycles |
| `GET` | `/api/applications` | List the signed-in student's applications |
| `GET` | `/api/applications/{reference}` | Read an application and its timeline |
| `POST` | `/api/applications` | Submit an application for an open cycle |

Registration expects `firstName`, `lastName`, `idNumber`, `dateOfBirth` (`YYYY-MM-DD`), `phone`, optional `email`, `county`, `constituency`, `ward`, `village`, `institution`, `educationLevel`, `password`, and `consent: true`.

Application submission expects `cycleId` and `admissionNumber`. No cycles are seeded because the portal's displayed academic year and eligibility rules must be confirmed by the bursary administrator. Until valid cycle records are configured in the `cycles` table, the API will correctly refuse application submission. The current frontend does not yet have a bursary application form or staff cycle-management interface.

Profile updates accept the editable student properties from registration except `idNumber`. Unknown fields are ignored.

## Configuration

- `ELIMU_HOST`: bind address (defaults to `127.0.0.1`; avoid exposing the development server publicly).
- `ELIMU_PORT`: API port (defaults to `8000`).
- `ELIMU_DB_PATH`: SQLite database path (defaults to `elimu_fund.sqlite3` beside `server.py`).
- `ELIMU_FRONTEND_ORIGINS`: comma-separated allowed browser origins (defaults to localhost and 127.0.0.1 on port 5173).
- `ELIMU_COOKIE_SECURE=1`: mark session cookies Secure when running behind HTTPS.

## Security scope

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes; session tokens are random and only their hashes are stored. The API masks identity-document numbers, restricts browser origins, and limits request size. This is still a development foundation: before real use, add a production-grade deployment, HTTPS, rate limiting and lockout, phone verification, CSRF strategy for the actual deployment topology, audit/retention controls, backups, monitoring, admin authorization, and a Kenyan data-protection review. Do not populate the database with real student information until those controls are in place.
