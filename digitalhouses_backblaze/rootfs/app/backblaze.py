"""Small Backblaze B2 Native API v4 client."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from core import BucketAccumulator

AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v4/b2_authorize_account"


class BackblazeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Authorization:
    account_id: str
    api_url: str
    token: str
    capabilities: frozenset[str]
    allowed_buckets: tuple[dict[str, Any], ...]


class B2Client:
    def __init__(
        self,
        application_key_id: str,
        application_key: str,
        *,
        timeout_seconds: int = 20,
    ) -> None:
        self.application_key_id = application_key_id
        self.application_key = application_key
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        url: str,
        *,
        authorization: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Authorization": authorization}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BackblazeError(
                f"Backblaze API HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BackblazeError(f"Backblaze API connection failed: {exc}") from exc

        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackblazeError("Backblaze API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise BackblazeError("Backblaze API returned an unexpected payload")
        return parsed

    def authorize(self) -> Authorization:
        token = base64.b64encode(
            f"{self.application_key_id}:{self.application_key}".encode("utf-8")
        ).decode("ascii")
        body = self._request(
            "GET",
            AUTHORIZE_URL,
            authorization=f"Basic {token}",
        )

        try:
            storage = body["apiInfo"]["storageApi"]
            allowed = storage["allowed"]
            account_id = str(body["accountId"])
            api_url = str(storage["apiUrl"]).rstrip("/")
            auth_token = str(body["authorizationToken"])
        except (KeyError, TypeError) as exc:
            raise BackblazeError(
                "Backblaze authorization response is missing storage API fields"
            ) from exc

        capabilities = frozenset(str(x) for x in allowed.get("capabilities", []))
        missing = {"listBuckets", "listFiles"} - capabilities
        if missing:
            raise BackblazeError(
                "Application key is missing required capabilities: "
                + ", ".join(sorted(missing))
            )

        buckets = allowed.get("buckets")
        if not isinstance(buckets, list):
            buckets = []

        return Authorization(
            account_id=account_id,
            api_url=api_url,
            token=auth_token,
            capabilities=capabilities,
            allowed_buckets=tuple(
                item for item in buckets if isinstance(item, dict)
            ),
        )

    def _list_buckets_call(
        self,
        auth: Authorization,
        *,
        bucket_id: str | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"accountId": auth.account_id}
        if bucket_id:
            payload["bucketId"] = bucket_id
        body = self._request(
            "POST",
            f"{auth.api_url}/b2api/v4/b2_list_buckets",
            authorization=auth.token,
            payload=payload,
        )
        buckets = body.get("buckets", [])
        if not isinstance(buckets, list):
            raise BackblazeError("b2_list_buckets returned invalid buckets")
        return [item for item in buckets if isinstance(item, dict)]

    def list_buckets(self, auth: Authorization) -> list[dict[str, Any]]:
        restricted_ids = [
            str(item["id"])
            for item in auth.allowed_buckets
            if item.get("id")
        ]
        if not restricted_ids:
            return self._list_buckets_call(auth)

        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for bucket_id in restricted_ids:
            for bucket in self._list_buckets_call(auth, bucket_id=bucket_id):
                current_id = str(bucket.get("bucketId") or "")
                if current_id and current_id not in seen:
                    seen.add(current_id)
                    result.append(bucket)
        result.sort(key=lambda item: str(item.get("bucketName") or ""))
        return result

    def iter_file_versions(
        self,
        auth: Authorization,
        bucket_id: str,
    ):
        start_file_name: str | None = None
        start_file_id: str | None = None

        while True:
            params: dict[str, Any] = {
                "bucketId": bucket_id,
                "maxFileCount": 1000,
            }
            if start_file_name is not None:
                params["startFileName"] = start_file_name
            if start_file_id is not None:
                params["startFileId"] = start_file_id

            url = (
                f"{auth.api_url}/b2api/v4/b2_list_file_versions?"
                + urllib.parse.urlencode(params)
            )
            body = self._request(
                "GET",
                url,
                authorization=auth.token,
            )
            entries = body.get("files", [])
            if not isinstance(entries, list):
                raise BackblazeError(
                    "b2_list_file_versions returned invalid files"
                )
            for item in entries:
                if isinstance(item, dict):
                    yield item

            next_name = body.get("nextFileName")
            next_id = body.get("nextFileId")
            if not next_name:
                break
            start_file_name = str(next_name)
            start_file_id = str(next_id) if next_id else None

    def collect(self) -> list[dict[str, Any]]:
        auth = self.authorize()
        results: list[dict[str, Any]] = []
        for bucket in self.list_buckets(auth):
            bucket_id = str(bucket.get("bucketId") or "")
            if not bucket_id:
                continue
            accumulator = BucketAccumulator(
                bucket_id=bucket_id,
                bucket_name=str(bucket.get("bucketName") or bucket_id),
                bucket_type=str(bucket.get("bucketType") or "unknown"),
            )
            for item in self.iter_file_versions(auth, bucket_id):
                accumulator.consume(item)
            results.append(accumulator.result())
        return results
