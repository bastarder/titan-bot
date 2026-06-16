#!/usr/bin/env python3
"""Build a JSON manifest for the static GitHub Pages dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from guild_config import load_guilds


SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_index(config_path: Path, data_dir: Path, output_path: Path, root: Path) -> None:
    guilds = load_guilds(config_path)
    manifest: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "guilds": [],
    }

    for guild in guilds:
        guild_data_dir = data_dir / guild.slug
        snapshots = []
        for path in sorted(guild_data_dir.glob("*.json")):
            if not SNAPSHOT_RE.match(path.name):
                continue
            payload = read_json(path)
            if not payload or payload.get("snapshot_date") != path.stem:
                continue
            try:
                relative_path = path.resolve().relative_to(root).as_posix()
            except ValueError:
                relative_path = path.as_posix()
            snapshots.append(
                {
                    "date": path.stem,
                    "path": relative_path,
                    "ok": payload.get("ok") is not False,
                    "fetched_at": payload.get("fetched_at"),
                }
            )

        manifest["guilds"].append(
            {
                "slug": guild.slug,
                "name": guild.name,
                "guild_id": guild.guild_id,
                "guild_url": guild.guild_url,
                "snapshots": snapshots,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/guilds.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/pages-index.json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    build_index(
        config_path=(root / args.config).resolve(),
        data_dir=(root / args.data_dir).resolve(),
        output_path=(root / args.output).resolve(),
        root=root.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
