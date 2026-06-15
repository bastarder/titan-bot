#!/usr/bin/env python3
"""Fetch one TitansDB guild snapshot into data/YYYY-MM-DD.json."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


GUILD_ID = "60bb3bd6b7b3871333bbde3c"
GUILD_URL = f"https://www.titansdb.com/guilds/{GUILD_ID}"
API_URL = "https://www.titansdb.com/api/my_guild"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def request_json(api_key: str) -> tuple[int, Any]:
    query = urllib.parse.urlencode({"api_key": api_key})
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-API-Key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:2000]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"error": "request_failed", "reason": str(exc.reason)}
    except json.JSONDecodeError as exc:
        return 0, {"error": "invalid_json", "reason": str(exc)}


def normalize_members(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []

    candidates = [
        payload.get("members"),
        payload.get("players"),
        payload.get("guild", {}).get("members") if isinstance(payload.get("guild"), dict) else None,
        payload.get("data", {}).get("members") if isinstance(payload.get("data"), dict) else None,
        payload.get("data", {}).get("players") if isinstance(payload.get("data"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def fetch_snapshot(api_key: str | None) -> dict[str, Any]:
    if not api_key:
        return {
            "ok": False,
            "source": "api",
            "guild_id": GUILD_ID,
            "guild_url": GUILD_URL,
            "api_url": API_URL,
            "error": {
                "error": "missing_api_key",
                "reason": "Set TITANSDB_API_KEY in GitHub Actions repository secrets.",
            },
        }

    status, payload = request_json(api_key)
    if status != 200:
        return {
            "ok": False,
            "source": "api",
            "guild_id": GUILD_ID,
            "guild_url": GUILD_URL,
            "api_url": API_URL,
            "http_status": status,
            "error": payload,
        }

    return {
        "ok": True,
        "source": "api",
        "guild_id": GUILD_ID,
        "guild_url": GUILD_URL,
        "api_url": API_URL,
        "members": normalize_members(payload),
        "raw": payload,
    }


def read_existing_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data", help="Directory for YYYY-MM-DD.json output")
    parser.add_argument("--date", default=None, help="Override output date, format YYYY-MM-DD")
    parser.add_argument(
        "--overwrite-success-with-error",
        action="store_true",
        help="Replace an existing successful same-day snapshot with an error snapshot.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")

    snapshot_date = args.date or dt.datetime.now().astimezone().date().isoformat()
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{snapshot_date}.json"

    result = {
        "snapshot_date": snapshot_date,
        "fetched_at": fetched_at,
        **fetch_snapshot(os.environ.get("TITANSDB_API_KEY", "").strip()),
    }

    existing = read_existing_snapshot(output_path)
    if (
        result.get("ok") is False
        and existing
        and existing.get("ok") is True
        and not args.overwrite_success_with_error
    ):
        print(
            f"{output_path} already contains a successful snapshot; "
            "keeping it instead of overwriting with the failed fetch result."
        )
        return 2

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
