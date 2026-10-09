"""Elimu Fund's small, dependency-free development API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import string
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("ELIMU_DB_PATH", ROOT / "elimu_fund.sqlite3"))
SCHEMA_PATH = ROOT / "database" / "schema.sql"
FRONTEND_ORIGINS = {
    value.strip().rstrip("/")
    for value in os.environ.get(
        "ELIMU_FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(",")
    if value.strip()
}
COOKIE_SECURE = os.environ.get("ELIMU_COOKIE_SECURE", "0") == "1"
SESSION_COOKIE = "elimu_session"
SESSION_DAYS = 7
PASSWORD_ITERATIONS = 310_000
MAX_BODY_BYTES = 1_000_000


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect_db() as db:
        db.executescript(schema)


def normalize_phone(value: str) -> str:
    if not re.fullmatch(r"[+0-9()\-\s]+", value):
        raise ValueError("Enter a valid Kenyan phone number, such as +254712345678.")
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("7") and len(digits) == 9:
        digits = "254" + digits
    if not digits.startswith("254") or len(digits) != 12:
        raise ValueError("Enter a valid Kenyan phone number, such as +254712345678.")
    return "+" + digits


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, PASSWORD_ITERATIONS
    )
    return digest.hex(), actual_salt.hex()


def public_student(row: sqlite3.Row) -> dict[str, Any]:
    id_number = row["id_number"]
    return {
        "id": row["id"],
        "firstName": row["first_name"],
        "lastName": row["last_name"],
        "idNumberMasked": "•" * max(0, len(id_number) - 3) + id_number[-3:],
        "dateOfBirth": row["date_of_birth"],
        "phone": row["phone"],
        "email": row["email"],
        "county": row["county"],
        "constituency": row["constituency"],
        "ward": row["ward"],
        "village": row["village"],
        "institution": row["institution"],
        "educationLevel": row["education_level"],
        "createdAt": row["created_at"],
    }


class APIHandler(BaseHTTPRequestHandler):
    server_version = "ElimuFundAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep request data out of logs; identity and session information is sensitive.
        print(f"{self.log_date_time_string()} {self.address_string()} {format % args}")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin in FRONTEND_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request body.") from error
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def _origin_is_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin.rstrip("/") in FRONTEND_ORIGINS

    def _session_student(self) -> sqlite3.Row | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None
        token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
        with connect_db() as db:
            return db.execute(
                """SELECT students.* FROM sessions
                   JOIN students ON students.id = sessions.student_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (token_hash, timestamp()),
            ).fetchone()

    def _set_session(self, student_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expires = timestamp(utc_now() + timedelta(days=SESSION_DAYS))
        with connect_db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (timestamp(),))
            db.execute(
                "INSERT INTO sessions(token_hash, student_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), student_id, expires, timestamp()),
            )
        return token

    def _cookie_header(self, token: str, clear: bool = False) -> str:
        parts = [f"{SESSION_COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if COOKIE_SECURE:
            parts.append("Secure")
        if clear:
            parts.append("Max-Age=0")
        else:
            parts.append(f"Max-Age={SESSION_DAYS * 24 * 60 * 60}")
        return "; ".join(parts)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin not in FRONTEND_ORIGINS:
            self._error(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if route == "/api/cycles":
            with connect_db() as db:
                cycles = db.execute(
                    "SELECT id, academic_year, opens_at, closes_at, status FROM cycles ORDER BY opens_at DESC"
                ).fetchall()
            self._send_json(HTTPStatus.OK, {"cycles": [dict(cycle) for cycle in cycles]})
            return
        if route == "/api/me":
            student = self._session_student()
            if student is None:
                self._error(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
                return
            self._send_json(HTTPStatus.OK, {"user": public_student(student)})
            return
        if route == "/api/applications":
            student = self._session_student()
            if student is None:
                self._error(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
                return
            with connect_db() as db:
                rows = db.execute(
                    """SELECT applications.*, cycles.academic_year FROM applications
                       JOIN cycles ON cycles.id = applications.cycle_id
                       WHERE applications.student_id = ? ORDER BY applications.submitted_at DESC""",
                    (student["id"],),
                ).fetchall()
            self._send_json(HTTPStatus.OK, {"applications": [self._application_json(row) for row in rows]})
            return
        if route.startswith("/api/applications/"):
            reference = route.rsplit("/", 1)[-1]
            student = self._session_student()
            if student is None:
                self._error(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
                return
            with connect_db() as db:
                row = db.execute(
                    """SELECT applications.*, cycles.academic_year FROM applications
                       JOIN cycles ON cycles.id = applications.cycle_id
                       WHERE applications.reference = ? AND applications.student_id = ?""",
                    (reference, student["id"]),
                ).fetchone()
                if row is None:
                    self._error(HTTPStatus.NOT_FOUND, "Application not found.")
                    return
                events = db.execute(
                    "SELECT title, description, occurred_at FROM application_events WHERE application_id = ? ORDER BY occurred_at",
                    (row["id"],),
                ).fetchall()
            result = self._application_json(row)
            result["timeline"] = [dict(event) for event in events]
            self._send_json(HTTPStatus.OK, {"application": result})
            return
        self._error(HTTPStatus.NOT_FOUND, "Endpoint not found.")

    @staticmethod
    def _application_json(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "reference": row["reference"],
            "cycle": row["academic_year"],
            "admissionNumber": row["admission_number"],
            "status": row["status"],
            "awardAmount": row["award_amount"],
            "submittedAt": row["submitted_at"],
        }

    def do_POST(self) -> None:
        if not self._origin_is_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            return
        route = urlparse(self.path).path.rstrip("/") or "/"
        try:
            data = self._read_json()
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if route == "/api/auth/register":
            self._register(data)
        elif route == "/api/auth/login":
            self._login(data)
        elif route == "/api/auth/logout":
            self._logout()
        elif route == "/api/applications":
            self._create_application(data)
        else:
            self._error(HTTPStatus.NOT_FOUND, "Endpoint not found.")

    def _register(self, data: dict[str, Any]) -> None:
        fields = {
            "firstName": "first_name", "lastName": "last_name", "idNumber": "id_number",
            "dateOfBirth": "date_of_birth", "phone": "phone", "email": "email",
            "county": "county", "constituency": "constituency", "ward": "ward",
            "village": "village", "institution": "institution", "educationLevel": "education_level",
        }
        values = {key: str(data.get(key, "")).strip() for key in fields}
        password = data.get("password")
        if any(not values[key] for key in fields if key != "email"):
            self._error(HTTPStatus.BAD_REQUEST, "Complete all required registration fields.")
            return
        if not isinstance(password, str) or len(password) < 8 or len(password) > 1024 or not re.search(r"\d", password):
            self._error(HTTPStatus.BAD_REQUEST, "Password must be at least 8 characters and include a number.")
            return
        if data.get("consent") is not True:
            self._error(HTTPStatus.BAD_REQUEST, "Consent is required to create an account.")
            return
        if len(values["idNumber"]) > 64 or len(values["phone"]) > 40:
            self._error(HTTPStatus.BAD_REQUEST, "A registration field is too long.")
            return
        if values["email"] and (len(values["email"]) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"])):
            self._error(HTTPStatus.BAD_REQUEST, "Enter a valid email address.")
            return
        values["email"] = values["email"].lower()
        try:
            values["phone"] = normalize_phone(values["phone"])
            birth_date = datetime.strptime(values["dateOfBirth"], "%Y-%m-%d").date()
            if birth_date >= utc_now().date():
                raise ValueError("Date of birth must be in the past.")
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error) or "Enter a valid date of birth.")
            return
        password_hash, salt = hash_password(password)
        columns = ", ".join(fields.values()) + ", password_hash, password_salt, created_at"
        placeholders = ", ".join("?" for _ in range(len(fields) + 3))
        params = [values[key] or None for key in fields] + [password_hash, salt, timestamp()]
        try:
            with connect_db() as db:
                cursor = db.execute(f"INSERT INTO students ({columns}) VALUES ({placeholders})", params)
                student = db.execute("SELECT * FROM students WHERE id = ?", (cursor.lastrowid,)).fetchone()
        except sqlite3.IntegrityError as error:
            message = str(error).lower()
            if "phone" in message:
                detail = "An account with this phone number already exists."
            elif "email" in message:
                detail = "An account with this email address already exists."
            elif "id_number" in message:
                detail = "An account with this identity document already exists."
            else:
                detail = "Could not create the account with those details."
            self._error(HTTPStatus.CONFLICT, detail)
            return
        token = self._set_session(student["id"])
        self._send_json(HTTPStatus.CREATED, {"user": public_student(student)}, {"Set-Cookie": self._cookie_header(token)})

    def _login(self, data: dict[str, Any]) -> None:
        identifier = str(data.get("identifier", "")).strip()
        password = data.get("password")
        if not identifier or not isinstance(password, str):
            self._error(HTTPStatus.BAD_REQUEST, "Enter your phone/email and password.")
            return
        try:
            lookup = normalize_phone(identifier) if "@" not in identifier else identifier.lower()
        except ValueError:
            lookup = identifier
        with connect_db() as db:
            student = db.execute(
                "SELECT * FROM students WHERE phone = ? OR lower(email) = lower(?)", (lookup, lookup)
            ).fetchone()
        if student is None:
            self._error(HTTPStatus.UNAUTHORIZED, "The phone/email or password is incorrect.")
            return
        candidate, _ = hash_password(password, bytes.fromhex(student["password_salt"]))
        if not hmac.compare_digest(candidate, student["password_hash"]):
            self._error(HTTPStatus.UNAUTHORIZED, "The phone/email or password is incorrect.")
            return
        token = self._set_session(student["id"])
        self._send_json(HTTPStatus.OK, {"user": public_student(student)}, {"Set-Cookie": self._cookie_header(token)})

    def _logout(self) -> None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel:
            token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
            with connect_db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self._send_json(
            HTTPStatus.OK,
            {"ok": True},
            {"Set-Cookie": self._cookie_header("", clear=True)},
        )

    def do_PATCH(self) -> None:
        if not self._origin_is_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Origin is not allowed.")
            return
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route != "/api/me/profile":
            self._error(HTTPStatus.NOT_FOUND, "Endpoint not found.")
            return
        student = self._session_student()
        if student is None:
            self._error(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
            return
        try:
            data = self._read_json()
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        editable = {
            "firstName": ("first_name", 100), "lastName": ("last_name", 100),
            "dateOfBirth": ("date_of_birth", 10), "phone": ("phone", 40),
            "email": ("email", 254), "county": ("county", 100),
            "constituency": ("constituency", 100), "ward": ("ward", 100),
            "village": ("village", 150), "institution": ("institution", 200),
            "educationLevel": ("education_level", 80),
        }
        changes = {key: str(data[key]).strip() for key in editable if key in data}
        if not changes:
            self._error(HTTPStatus.BAD_REQUEST, "No editable profile fields were provided.")
            return
        for key, value in changes.items():
            if not value and key not in {"email"}:
                self._error(HTTPStatus.BAD_REQUEST, f"{key} cannot be empty.")
                return
            if len(value) > editable[key][1]:
                self._error(HTTPStatus.BAD_REQUEST, f"{key} is too long.")
                return
        if "phone" in changes:
            try:
                changes["phone"] = normalize_phone(changes["phone"])
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
                return
        if "email" in changes and changes["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", changes["email"]):
            self._error(HTTPStatus.BAD_REQUEST, "Enter a valid email address.")
            return
        if "dateOfBirth" in changes:
            try:
                if datetime.strptime(changes["dateOfBirth"], "%Y-%m-%d").date() >= utc_now().date():
                    raise ValueError
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "Enter a valid date of birth.")
                return
        assignments = ", ".join(f"{editable[key][0]} = ?" for key in changes)
        params = [value or None for value in changes.values()] + [student["id"]]
        try:
            with connect_db() as db:
                db.execute(f"UPDATE students SET {assignments} WHERE id = ?", params)
                updated = db.execute("SELECT * FROM students WHERE id = ?", (student["id"],)).fetchone()
        except sqlite3.IntegrityError as error:
            field = "phone number" if "phone" in str(error).lower() else "email address"
            self._error(HTTPStatus.CONFLICT, f"That {field} is already associated with another account.")
            return
        self._send_json(HTTPStatus.OK, {"user": public_student(updated)})

    def _create_application(self, data: dict[str, Any]) -> None:
        student = self._session_student()
        if student is None:
            self._error(HTTPStatus.UNAUTHORIZED, "Sign in to continue.")
            return
        try:
            cycle_id = int(data.get("cycleId"))
        except (TypeError, ValueError):
            self._error(HTTPStatus.BAD_REQUEST, "Select an application cycle.")
            return
        admission_number = str(data.get("admissionNumber", "")).strip()
        if not admission_number or len(admission_number) > 100:
            self._error(HTTPStatus.BAD_REQUEST, "Enter a valid admission number.")
            return
        now = timestamp()
        reference = "ELF-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))
        try:
            with connect_db() as db:
                cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
                if cycle is None or cycle["status"] != "open" or not (cycle["opens_at"] <= now <= cycle["closes_at"]):
                    self._error(HTTPStatus.CONFLICT, "This application cycle is not currently open.")
                    return
                cursor = db.execute(
                    """INSERT INTO applications(reference, student_id, cycle_id, admission_number, status, submitted_at)
                       VALUES (?, ?, ?, ?, 'submitted', ?)""",
                    (reference, student["id"], cycle_id, admission_number, now),
                )
                db.execute(
                    "INSERT INTO application_events(application_id, title, description, occurred_at) VALUES (?, ?, ?, ?)",
                    (cursor.lastrowid, "Application submitted", "Your application was received and is awaiting review.", now),
                )
                row = db.execute(
                    """SELECT applications.*, cycles.academic_year FROM applications
                       JOIN cycles ON cycles.id = applications.cycle_id WHERE applications.id = ?""",
                    (cursor.lastrowid,),
                ).fetchone()
        except sqlite3.IntegrityError:
            self._error(HTTPStatus.CONFLICT, "You have already applied for this cycle.")
            return
        self._send_json(HTTPStatus.CREATED, {"application": self._application_json(row)})

    def do_DELETE(self) -> None:
        self._error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")


def main() -> None:
    initialize_database()
    host = os.environ.get("ELIMU_HOST", "127.0.0.1")
    port = int(os.environ.get("ELIMU_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), APIHandler)
    print(f"Elimu Fund API listening on http://{host}:{port}")
    print(f"SQLite database: {DATABASE_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Elimu Fund API...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()