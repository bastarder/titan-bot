#!/usr/bin/env python3
"""Fetch TitansDB guild snapshots into data/{guild_slug}/YYYY-MM-DD.json."""

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

from guild_config import GuildConfig, load_guilds


API_URL_TEMPLATE = "https://www.titansdb.com/api/guild/{guild_id}"
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


def request_json(api_key: str, guild_id: str) -> tuple[int, Any]:
    api_url = API_URL_TEMPLATE.format(guild_id=guild_id)
    query = urllib.parse.urlencode({"api_key": api_key})
    request = urllib.request.Request(
        f"{api_url}?{query}",
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

    guild = payload.get("guild")
    data = payload.get("data")
    candidates = [
        payload.get("members"),
        payload.get("players"),
        guild.get("members") if isinstance(guild, dict) else None,
        data.get("members") if isinstance(data, dict) else None,
        data.get("players") if isinstance(data, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def fetch_snapshot(guild: GuildConfig, api_key: str | None) -> dict[str, Any]:
    api_url = API_URL_TEMPLATE.format(guild_id=guild.guild_id)
    base = {
        "source": "api",
        "guild_slug": guild.slug,
        "guild_name": guild.name,
        "guild_id": guild.guild_id,
        "guild_url": guild.guild_url,
        "api_url": api_url,
    }

    if not api_key:
        return {
            **base,
            "ok": False,
            "error": {
                "error": "missing_api_key",
                "reason": "Set TITANSDB_API_KEY in GitHub Actions repository secrets or local .env.",
            },
        }

    status, payload = request_json(api_key, guild.guild_id)
    if status != 200:
        return {
            **base,
            "ok": False,
            "http_status": status,
            "error": payload,
        }

    return {
        **base,
        "ok": True,
        "members": normalize_members(payload),
        "raw": payload,
    }


def read_existing_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_snapshot(
    *,
    guild: GuildConfig,
    output_dir: Path,
    snapshot_date: str,
    fetched_at: str,
    api_key: str | None,
    overwrite_success_with_error: bool,
) -> int:
    guild_output_dir = output_dir / guild.slug
    guild_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = guild_output_dir / f"{snapshot_date}.json"

    result = {
        "snapshot_date": snapshot_date,
        "fetched_at": fetched_at,
        **fetch_snapshot(guild, api_key),
    }

    existing = read_existing_snapshot(output_path)
    if (
        result.get("ok") is False
        and existing
        and existing.get("ok") is True
        and not overwrite_success_with_error
    ):
        print(
            f"{output_path} already contains a successful snapshot; "
            "keeping it instead of overwriting with the failed fetch result."
        )
        return 2

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0 if result.get("ok") else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data", help="Directory for guild snapshot output")
    parser.add_argument("--config", default="config/guilds.json", help="Guild config JSON path")
    parser.add_argument("--guild-slug", default=None, help="Fetch only one configured guild slug")
    parser.add_argument("--date", default=None, help="Override output date, format YYYY-MM-DD")
    parser.add_argument(
        "--overwrite-success-with-error",
        action="store_true",
        help="Replace an existing successful same-day snapshot with an error snapshot.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")

    guilds = load_guilds((root / args.config).resolve())
    if args.guild_slug:
        guilds = [guild for guild in guilds if guild.slug == args.guild_slug]
        if not guilds:
            raise SystemExit(f"Unknown guild slug: {args.guild_slug}")

    snapshot_date = args.date or dt.datetime.now().astimezone().date().isoformat()
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    output_dir = (root / args.output_dir).resolve()
    api_key = os.environ.get("TITANSDB_API_KEY", "").strip()

    exit_code = 0
    for guild in guilds:
        result = write_snapshot(
            guild=guild,
            output_dir=output_dir,
            snapshot_date=snapshot_date,
            fetched_at=fetched_at,
            api_key=api_key,
            overwrite_success_with_error=args.overwrite_success_with_error,
        )
        exit_code = max(exit_code, result)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
