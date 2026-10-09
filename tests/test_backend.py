import json
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


class BackendAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DATABASE_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
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
        self.cookies = CookieJar()
        self.client = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, path, method="GET", data=None, expected_status=200):
        body = None if data is None else json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Origin": "http://127.0.0.1:5173",
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        try:
            response = self.client.open(request)
        except urllib.error.HTTPError as error:
            response = error
        try:
            payload = json.loads(response.read())
        finally:
            response.close()
        self.assertEqual(response.status, expected_status, payload)
        return payload

    def test_account_session_profile_and_logout(self):
        self.assertEqual(self.request("/health")["status"], "ok")
        registration = {
            "firstName": "Test",
            "lastName": "Student",
            "idNumber": "TEST-" + str(threading.get_ident()),
            "dateOfBirth": "2004-01-02",
            "phone": "0712345678",
            "email": "test.student@example.test",
            "county": "Nairobi",
            "constituency": "Westlands",
            "ward": "Test ward",
            "village": "Test estate",
            "institution": "Test college",
            "educationLevel": "College",
            "password": "securepass1",
            "consent": True,
        }
        created = self.request("/auth/register", "POST", registration, 201)
        self.assertTrue(created["user"]["idNumberMasked"].endswith(registration["idNumber"][-3:]))
        self.assertNotIn("password", created["user"])
        self.assertEqual(self.request("/me")["user"]["firstName"], "Test")
        updated = self.request("/me/profile", "PATCH", {"institution": "Updated college"})
        self.assertEqual(updated["user"]["institution"], "Updated college")
        self.request("/auth/logout", "POST", {})
        self.request("/me", expected_status=401)
        self.request("/auth/login", "POST", {"identifier": "0712345678", "password": "securepass1"})
        self.assertEqual(self.request("/me")["user"]["phone"], "+254712345678")
        with server.connect_db() as db:
            cycle = db.execute(
                "INSERT INTO cycles(academic_year, opens_at, closes_at) VALUES (?, ?, ?)",
                ("Test cycle", "2020-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00"),
            )
            cycle_id = cycle.lastrowid
        submitted = self.request(
            "/applications", "POST", {"cycleId": cycle_id, "admissionNumber": "TEST/001"}, 201
        )["application"]
        self.assertEqual(submitted["status"], "submitted")
        self.assertEqual(self.request("/applications")["applications"][0]["reference"], submitted["reference"])
        details = self.request(f"/applications/{submitted['reference']}")["application"]
        self.assertEqual(details["timeline"][0]["title"], "Application submitted")


if __name__ == "__main__":
    unittest.main()
