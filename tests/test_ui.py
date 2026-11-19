"""Tests for the read-only audit workbench."""

from __future__ import annotations

import http.client
import json
import threading
import unittest

from letro.ui.server import MAX_BODY, create_server


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def get_json(self, path):
        status, data = self.request("GET", path)
        return status, json.loads(data)

    def post_json(self, path, payload):
        status, data = self.request("POST", path, payload)
        return status, json.loads(data)

    def first_episode(self):
        status, payload = self.get_json("/api/episodes")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["episodes"]), 20)
        return payload["episodes"][0]["episode_id"]

    def test_health(self):
        status, payload = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(payload["episodes"], 20)

    def test_episodes(self):
        status, payload = self.get_json("/api/episodes")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["episodes"]), 20)
        splits = {item["split"] for item in payload["episodes"]}
        self.assertEqual(splits, {"train", "dev"})

    def test_summary_has_no_truth(self):
        episode_id = self.first_episode()
        status, payload = self.get_json(f"/api/episodes/{episode_id}/summary")
        self.assertEqual(status, 200)
        self.assertEqual(payload["episode_id"], episode_id)
        text = json.dumps(payload)
        self.assertNotIn("allowed_evidence_sets", text)
        self.assertNotIn("expected_amount_minor", text)
        self.assertNotIn("issue_id", text)

    def test_records(self):
        episode_id = self.first_episode()
        status, payload = self.get_json(
            f"/api/episodes/{episode_id}/records?table=ledger&cursor=0&limit=5"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["rows"]), 5)
        self.assertEqual(payload["cursor"], 0)
        self.assertGreaterEqual(payload["total"], 200)

    def test_record(self):
        episode_id = self.first_episode()
        _status, page = self.get_json(
            f"/api/episodes/{episode_id}/records?table=ledger&limit=1"
        )
        row_id = page["rows"][0]["row_id"]
        status, payload = self.get_json(
            f"/api/episodes/{episode_id}/record?table=ledger&id={row_id}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["record"]["row_id"], row_id)

    def test_invalid_table(self):
        episode_id = self.first_episode()
        status, payload = self.get_json(
            f"/api/episodes/{episode_id}/records?table=secrets"
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown table", payload["error"])

    def test_run(self):
        episode_id = self.first_episode()
        status, payload = self.post_json(
            "/api/run", {"episode_id": episode_id, "policy": "reconciliation"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["policy"], "reconciliation")
        self.assertIn("f1", payload["metrics"])
        self.assertIn("reward", payload["metrics"])
        self.assertIsInstance(payload["findings"], list)
        text = json.dumps(payload)
        self.assertNotIn("allowed_evidence_sets", text)
        self.assertNotIn("expected_amount_minor", text)

    def test_run_unknown_policy(self):
        episode_id = self.first_episode()
        status, payload = self.post_json(
            "/api/run", {"episode_id": episode_id, "policy": "oracle"}
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown policy", payload["error"])

    def test_unknown_episode(self):
        status, payload = self.get_json("/api/episodes/ep-0000000000/summary")
        self.assertEqual(status, 404)
        self.assertIn("unknown episode", payload["error"])

    def test_static_and_path_traversal(self):
        status, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"LETRO", data)
        status, data = self.request("GET", "/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn(b"--paper", data)
        status, _data = self.request("GET", "/static/../server.py")
        self.assertEqual(status, 404)

    def test_body_limit(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("POST", "/api/run")
        connection.putheader("Content-Length", str(MAX_BODY + 1))
        connection.endheaders()
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        self.assertEqual(status, 400)
        self.assertIn("too large", json.loads(data)["error"])


if __name__ == "__main__":
    unittest.main()
