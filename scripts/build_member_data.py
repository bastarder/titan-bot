#!/usr/bin/env python3
"""Build member-centric data files from existing guild snapshot JSON files."""

from __future__ import annotations

import argparse
from pathlib import Path

from guild_config import load_guilds
from member_store import (
    GUILD_MEMBERS_FILENAME,
    MEMBERS_FILENAME,
    finalize_guild_member_store,
    finalize_member_store,
    iter_snapshot_files,
    read_json_object,
    update_stores_from_snapshot,
    utc_now,
    write_json,
)


def build_member_data(
    config_path: Path,
    data_dir: Path,
    members_output: Path,
    guild_members_output: Path,
    allow_empty: bool = False,
) -> None:
    generated_at = utc_now()
    member_store = {
        "schema_version": 1,
        "generated_at": generated_at,
        "dates": [],
        "members": {},
    }
    guild_store = {
        "schema_version": 1,
        "generated_at": generated_at,
        "guilds": {},
    }

    updated_count = 0
    for guild in load_guilds(config_path):
        for path in iter_snapshot_files(data_dir, guild):
            snapshot = read_json_object(path)
            if not snapshot or snapshot.get("snapshot_date") != path.stem:
                continue
            updated = update_stores_from_snapshot(
                member_store=member_store,
                guild_store=guild_store,
                guild=guild,
                snapshot=snapshot,
                snapshot_date=path.stem,
                fetched_at=str(snapshot.get("fetched_at") or ""),
            )
            if updated:
                updated_count += 1

    if updated_count == 0 and not allow_empty:
        raise SystemExit(
            "No legacy snapshot files were found. Refusing to overwrite aggregate data with empty stores."
        )

    finalize_member_store(member_store, generated_at=generated_at)
    finalize_guild_member_store(guild_store, generated_at=generated_at)
    write_json(members_output, member_store)
    write_json(guild_members_output, guild_store)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/guilds.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--members-output", default=f"data/{MEMBERS_FILENAME}")
    parser.add_argument("--guild-members-output", default=f"data/{GUILD_MEMBERS_FILENAME}")
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    build_member_data(
        config_path=(root / args.config).resolve(),
        data_dir=(root / args.data_dir).resolve(),
        members_output=(root / args.members_output).resolve(),
        guild_members_output=(root / args.guild_members_output).resolve(),
        allow_empty=args.allow_empty,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
