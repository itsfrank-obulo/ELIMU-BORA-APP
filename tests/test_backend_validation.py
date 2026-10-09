"""Validation and access-control tests for the Elimu Fund API."""

import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPCookieProcessor, build_opener
from http.cookiejar import CookieJar

import server


class BackendValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DATABASE_PATH = Path(cls.temp_dir.name) / "validation.sqlite3"
        server.initialize_database()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.APIHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}/api"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.temp_dir.cleanup()

    def setUp(self):
        with server.connect_db() as db:
            db.execute("DELETE FROM students")
            db.execute("DELETE FROM cycles")
        self.client = self.new_client()

    @staticmethod
    def new_client():
        return build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, path, method="GET", data=None, expected_status=200, client=None, origin="http://127.0.0.1:5173", raw_body=None):
        body = raw_body if raw_body is not None else (None if data is None else json.dumps(data).encode("utf-8"))
        headers = {"Origin": origin}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            response = (client or self.client).open(request)
        except urllib.error.HTTPError as error:
            response = error
        try:
            response_body = response.read()
        finally:
            response.close()
        payload = json.loads(response_body) if response_body else {}
        self.assertEqual(response.status, expected_status, payload)
        return payload

    def registration(self, **changes):
        suffix = secrets.token_hex(4)
        phone_suffix = str(int(suffix, 16) % 100_000_000).zfill(8)
        values = {
            "firstName": "Test",
            "lastName": "Student",
            "idNumber": f"TEST-{suffix}",
            "dateOfBirth": "2004-01-02",
            "phone": "07" + phone_suffix,
            "email": f"student-{suffix}@example.test",
            "county": "Nairobi",
            "constituency": "Westlands",
            "ward": "Test ward",
            "village": "Test estate",
            "institution": "Test college",
            "educationLevel": "College",
            "password": "securepass1",
            "consent": True,
        }
        values.update(changes)
        return values

    def create_account(self, client=None, **changes):
        values = self.registration(**changes)
        result = self.request("/auth/register", "POST", values, 201, client=client)
        return values, result["user"]

    def test_registration_rejects_invalid_fields_and_duplicate_identifiers(self):
        for changes in (
            {"consent": False},
            {"phone": "not-a-phone"},
            {"dateOfBirth": "2099-01-01"},
            {"password": "short1"},
        ):
            self.request("/auth/register", "POST", self.registration(**changes), 400)

        account, _ = self.create_account()
        self.request("/auth/register", "POST", account, 409)
        self.request(
            "/auth/register", "POST",
            self.registration(idNumber=account["idNumber"], phone="0712345679", email="another@example.test"),
            409,
        )
        self.request(
            "/auth/register", "POST",
            self.registration(idNumber="OTHER-ID", phone="0712345680", email=account["email"].upper()),
            409,
        )

    def test_login_rejects_bad_credentials_and_accepts_email_case_insensitively(self):
        account, _ = self.create_account()
        self.request("/auth/login", "POST", {"identifier": account["phone"], "password": "wrongpass1"}, 401)
        self.request(
            "/auth/login", "POST",
            {"identifier": account["email"].upper(), "password": account["password"]},
        )
        self.assertEqual(self.request("/me")["user"]["email"], account["email"])

    def test_profile_requires_auth_and_validates_editable_fields(self):
        self.request("/me/profile", "PATCH", {"institution": "Changed"}, 401)
        account, user = self.create_account()
        unchanged = self.request(
            "/me/profile", "PATCH", {"idNumber": "REPLACEMENT", "institution": "Updated college"}
        )["user"]
        self.assertEqual(unchanged["institution"], "Updated college")
        self.assertEqual(unchanged["idNumberMasked"], user["idNumberMasked"])
        self.request("/me/profile", "PATCH", {"phone": "invalid"}, 400)
        self.request("/me/profile", "PATCH", {}, 400)
        normalized_phone = "+254" + account["phone"][1:]
        self.assertEqual(self.request("/me")["user"]["phone"], normalized_phone)

    def test_applications_enforce_cycle_and_student_ownership(self):
        self.request("/applications", expected_status=401)
        self.create_account()
        self.assertEqual(self.request("/cycles")["cycles"], [])
        with server.connect_db() as db:
            open_cycle = db.execute(
                "INSERT INTO cycles(academic_year, opens_at, closes_at) VALUES (?, ?, ?)",
                ("Open test cycle", "2020-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
            ).lastrowid
            closed_cycle = db.execute(
                "INSERT INTO cycles(academic_year, opens_at, closes_at, status) VALUES (?, ?, ?, 'closed')",
                ("Closed test cycle", "2020-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
            ).lastrowid
            future_cycle = db.execute(
                "INSERT INTO cycles(academic_year, opens_at, closes_at) VALUES (?, ?, ?)",
                ("Future test cycle", "2090-01-01T00:00:00+00:00", "2091-01-01T00:00:00+00:00"),
            ).lastrowid

        submission = self.request(
            "/applications", "POST", {"cycleId": open_cycle, "admissionNumber": "TEST/001"}, 201
        )["application"]
        self.assertEqual(submission["status"], "submitted")
        self.assertEqual(self.request("/applications")["applications"][0]["reference"], submission["reference"])
        detail = self.request(f"/applications/{submission['reference']}")["application"]
        self.assertEqual(detail["timeline"][0]["title"], "Application submitted")
        self.request("/applications", "POST", {"cycleId": open_cycle, "admissionNumber": "TEST/002"}, 409)
        self.request("/applications", "POST", {"cycleId": closed_cycle, "admissionNumber": "TEST/003"}, 409)
        self.request("/applications", "POST", {"cycleId": future_cycle, "admissionNumber": "TEST/004"}, 409)
        self.request("/applications", "POST", {"cycleId": open_cycle, "admissionNumber": ""}, 400)

        second_client = self.new_client()
        self.create_account(client=second_client)
        second_application = self.request(
            "/applications", "POST", {"cycleId": open_cycle, "admissionNumber": "TEST/OTHER"}, 201,
            client=second_client,
        )["application"]
        self.request(f"/applications/{second_application['reference']}", expected_status=404)

    def test_rejects_disallowed_origin_and_malformed_json(self):
        registration = self.registration()
        self.request(
            "/auth/register", "POST", registration, 403, origin="https://untrusted.example"
        )
        self.request("/auth/login", "POST", expected_status=400, raw_body=b"{not-json")

    def test_database_schema_initialization_is_repeatable(self):
        server.initialize_database()
        with server.connect_db() as db:
            tables = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertTrue(
            {"students", "sessions", "cycles", "applications", "application_events"}.issubset(tables)
        )

    def test_expired_sessions_are_rejected(self):
        self.create_account()
        with server.connect_db() as db:
            db.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
        self.request("/me", expected_status=401)


if __name__ == "__main__":
    unittest.main()
