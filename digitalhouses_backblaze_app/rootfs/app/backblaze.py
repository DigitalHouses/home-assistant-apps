from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"
API_VERSION_PATH = "/b2api/v4"


class BackblazeApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorizedAccount:
    account_id: str
    api_url: str
    authorization_token: str


@dataclass(frozen=True)
class BucketUsage:
    bucket_id: str
    bucket_name: str
    bucket_type: str
    stored_bytes: int
    current_bytes: int
    current_files: int
    versions: int
    hide_markers: int


@dataclass(frozen=True)
class AccountUsage:
    buckets: tuple[BucketUsage, ...]
    stored_bytes: int
    current_bytes: int
    current_files: int
    versions: int


class BackblazeClient:
    def __init__(
        self,
        application_key_id: str,
        application_key: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.application_key_id = application_key_id
        self.application_key = application_key
        self.timeout = timeout

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise BackblazeApiError(
                f"Backblaze API HTTP {exc.code}: {detail[:300]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BackblazeApiError(f"Backblaze API request failed: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackblazeApiError("Backblaze API returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise BackblazeApiError("Backblaze API returned unexpected payload")
        return data

    def authorize(self) -> AuthorizedAccount:
        credentials = (
            f"{self.application_key_id}:{self.application_key}".encode("utf-8")
        )
        basic = base64.b64encode(credentials).decode("ascii")
        data = self._request_json(
            "GET",
            AUTHORIZE_URL,
            headers={"Authorization": f"Basic {basic}"},
        )
        try:
            storage = data["apiInfo"]["storageApi"]
            allowed = storage["allowed"]
            capabilities = set(allowed.get("capabilities") or [])
            missing = {"listBuckets", "listFiles"} - capabilities
            if missing:
                raise BackblazeApiError(
                    "Application key is missing capabilities: "
                    + ", ".join(sorted(missing))
                )
            return AuthorizedAccount(
                account_id=str(data["accountId"]),
                api_url=str(storage["apiUrl"]).rstrip("/"),
                authorization_token=str(data["authorizationToken"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackblazeApiError(
                "Backblaze authorization response is incomplete"
            ) from exc

    def _post(
        self,
        account: AuthorizedAccount,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"{account.api_url}{API_VERSION_PATH}/{operation}",
            headers={"Authorization": account.authorization_token},
            payload=payload,
        )

    def list_buckets(self, account: AuthorizedAccount) -> list[dict[str, Any]]:
        data = self._post(
            account,
            "b2_list_buckets",
            {"accountId": account.account_id, "bucketTypes": ["all"]},
        )
        buckets = data.get("buckets")
        if not isinstance(buckets, list):
            raise BackblazeApiError("b2_list_buckets returned no buckets array")
        return [item for item in buckets if isinstance(item, dict)]

    @staticmethod
    def _content_version(item: dict[str, Any]) -> bool:
        action = str(item.get("action") or "")
        if action in {"start", "hide", "folder"}:
            return False
        try:
            int(item.get("contentLength") or 0)
        except (TypeError, ValueError):
            return False
        return bool(item.get("fileId"))

    def scan_bucket(
        self,
        account: AuthorizedAccount,
        bucket: dict[str, Any],
    ) -> BucketUsage:
        bucket_id = str(bucket.get("bucketId") or "")
        bucket_name = str(bucket.get("bucketName") or bucket_id)
        bucket_type = str(bucket.get("bucketType") or "")
        if not bucket_id:
            raise BackblazeApiError("Bucket without bucketId")

        stored_bytes = 0
        current_bytes = 0
        current_files = 0
        versions = 0
        hide_markers = 0
        active_name: str | None = None
        current_decided = False
        start_file_name: str | None = None
        start_file_id: str | None = None

        while True:
            request: dict[str, Any] = {
                "bucketId": bucket_id,
                "maxFileCount": 1000,
            }
            if start_file_name is not None:
                request["startFileName"] = start_file_name
            if start_file_id is not None:
                request["startFileId"] = start_file_id

            data = self._post(account, "b2_list_file_versions", request)
            files = data.get("files")
            if not isinstance(files, list):
                raise BackblazeApiError(
                    f"b2_list_file_versions returned invalid files for {bucket_name}"
                )

            for item in files:
                if not isinstance(item, dict):
                    continue
                file_name = str(item.get("fileName") or "")
                if file_name != active_name:
                    active_name = file_name
                    current_decided = False

                action = str(item.get("action") or "")
                content_version = self._content_version(item)
                try:
                    content_length = int(item.get("contentLength") or 0)
                except (TypeError, ValueError):
                    content_length = 0

                if content_version:
                    stored_bytes += max(content_length, 0)
                    versions += 1
                elif action == "hide":
                    hide_markers += 1

                if not current_decided and action not in {"start", "folder"}:
                    current_decided = True
                    if content_version:
                        current_files += 1
                        current_bytes += max(content_length, 0)

            next_name = data.get("nextFileName")
            next_id = data.get("nextFileId")
            if not next_name:
                break
            start_file_name = str(next_name)
            start_file_id = str(next_id) if next_id else None

        return BucketUsage(
            bucket_id=bucket_id,
            bucket_name=bucket_name,
            bucket_type=bucket_type,
            stored_bytes=stored_bytes,
            current_bytes=current_bytes,
            current_files=current_files,
            versions=versions,
            hide_markers=hide_markers,
        )

    def scan_all(self) -> AccountUsage:
        account = self.authorize()
        usages = tuple(
            self.scan_bucket(account, bucket)
            for bucket in self.list_buckets(account)
        )
        return AccountUsage(
            buckets=usages,
            stored_bytes=sum(item.stored_bytes for item in usages),
            current_bytes=sum(item.current_bytes for item in usages),
            current_files=sum(item.current_files for item in usages),
            versions=sum(item.versions for item in usages),
        )
