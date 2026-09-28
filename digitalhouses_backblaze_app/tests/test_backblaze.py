import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from backblaze import BackblazeApiError, BackblazeClient


class BackblazeClientTests(unittest.TestCase):
    def test_scan_all_counts_all_stored_versions_and_current_files(self):
        client = BackblazeClient("id", "secret")
        responses = [
            {
                "accountId": "account",
                "authorizationToken": "token",
                "apiInfo": {
                    "storageApi": {
                        "apiUrl": "https://api.example.test",
                        "allowed": {
                            "capabilities": ["listBuckets", "listFiles"],
                        },
                    }
                },
            },
            {
                "buckets": [
                    {"bucketId": "a", "bucketName": "alpha", "bucketType": "allPrivate"},
                    {"bucketId": "b", "bucketName": "beta", "bucketType": "allPrivate"},
                ]
            },
            {
                "files": [
                    {"fileName": "bar", "fileId": "1", "action": "upload", "contentLength": 200},
                    {"fileName": "foo", "fileId": "2", "action": "upload", "contentLength": 100},
                    {"fileName": "foo", "fileId": "3", "action": "upload", "contentLength": 90},
                    {"fileName": "hidden", "fileId": "4", "action": "hide", "contentLength": 0},
                    {"fileName": "hidden", "fileId": "5", "action": "upload", "contentLength": 50},
                ],
                "nextFileName": "part",
                "nextFileId": "6",
            },
            {
                "files": [
                    {"fileName": "part", "fileId": "6", "action": "start", "contentLength": 0},
                    {"fileName": "part", "fileId": "7", "action": "upload", "contentLength": 20},
                ],
                "nextFileName": None,
                "nextFileId": None,
            },
            {
                "files": [
                    {"fileName": "one", "fileId": "8", "action": "upload", "contentLength": 300},
                ],
                "nextFileName": None,
                "nextFileId": None,
            },
        ]

        with patch.object(client, "_request_json", side_effect=responses):
            usage = client.scan_all()

        self.assertEqual(len(usage.buckets), 2)
        self.assertEqual(usage.stored_bytes, 760)
        self.assertEqual(usage.current_files, 4)
        self.assertEqual(usage.versions, 6)
        self.assertEqual(usage.buckets[0].stored_bytes, 460)
        self.assertEqual(usage.buckets[0].current_files, 3)
        self.assertEqual(usage.buckets[0].hide_markers, 1)

    def test_authorize_requires_read_only_listing_capabilities(self):
        client = BackblazeClient("id", "secret")
        response = {
            "accountId": "account",
            "authorizationToken": "token",
            "apiInfo": {
                "storageApi": {
                    "apiUrl": "https://api.example.test",
                    "allowed": {"capabilities": ["listFiles"]},
                }
            },
        }
        with patch.object(client, "_request_json", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "listBuckets"):
                client.authorize()

    def test_missing_content_length_fails_contract(self):
        client = BackblazeClient("id", "secret")
        account = type(
            "Account",
            (),
            {
                "account_id": "account",
                "api_url": "https://api.example.test",
                "authorization_token": "token",
            },
        )()
        bucket = {
            "bucketId": "a",
            "bucketName": "alpha",
            "bucketType": "allPrivate",
        }
        response = {
            "files": [
                {
                    "fileName": "broken",
                    "fileId": "1",
                    "action": "upload",
                }
            ],
            "nextFileName": None,
            "nextFileId": None,
        }

        with patch.object(client, "_post", return_value=response):
            with self.assertRaisesRegex(BackblazeApiError, "contentLength"):
                client.scan_bucket(account, bucket)

    def test_unknown_file_action_fails_contract(self):
        client = BackblazeClient("id", "secret")
        account = type(
            "Account",
            (),
            {
                "account_id": "account",
                "api_url": "https://api.example.test",
                "authorization_token": "token",
            },
        )()
        bucket = {
            "bucketId": "a",
            "bucketName": "alpha",
            "bucketType": "allPrivate",
        }
        response = {
            "files": [
                {
                    "fileName": "future",
                    "fileId": "1",
                    "action": "future-action",
                    "contentLength": 1,
                }
            ],
            "nextFileName": None,
            "nextFileId": None,
        }

        with patch.object(client, "_post", return_value=response):
            with self.assertRaisesRegex(BackblazeApiError, "unsupported action"):
                client.scan_bucket(account, bucket)

    def test_missing_bucket_name_fails_contract(self):
        client = BackblazeClient("id", "secret")
        account = type(
            "Account",
            (),
            {
                "account_id": "account",
                "api_url": "https://api.example.test",
                "authorization_token": "token",
            },
        )()
        bucket = {
            "bucketId": "a",
            "bucketType": "allPrivate",
        }

        with self.assertRaisesRegex(BackblazeApiError, "bucketName"):
            client.scan_bucket(account, bucket)


if __name__ == "__main__":
    unittest.main()
