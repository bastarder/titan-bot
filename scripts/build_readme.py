#!/usr/bin/env python3
"""Build README.md from TitansDB daily JSON snapshots."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


GUILD_URL = "https://www.titansdb.com/guilds/60bb3bd6b7b3871333bbde3c"
SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
HUNDRED_MILLION = 100_000_000


@dataclass
class MemberRecord:
    id: str
    latest_name: str
    latest_level: Any = ""
    latest_role: str = ""
    by_date: dict[str, int] = field(default_factory=dict)


def markdown_escape(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def format_yi(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value / HUNDRED_MILLION:.2f}亿"


def format_delta(value: int | float | None) -> str:
    if value is None:
        return ""
    sign = "+" if value > 0 else ""
    return f"{sign}{value / HUNDRED_MILLION:.2f}亿"


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("snapshot_date") != path.stem:
        return None
    return payload


def get_members(snapshot: dict[str, Any]) -> list[Any]:
    if isinstance(snapshot.get("members"), list):
        return snapshot["members"]
    raw = snapshot.get("raw")
    if isinstance(raw, dict):
        guild = raw.get("guild")
        if isinstance(guild, dict) and isinstance(guild.get("members"), list):
            return guild["members"]
    return []


def investment_of(member: Any) -> int:
    if not isinstance(member, dict):
        return 0
    stats = member.get("stats")
    if isinstance(stats, dict):
        value = stats.get("investments", 0)
    else:
        value = member.get("investments", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def role_of(member: dict[str, Any]) -> str:
    guild = member.get("guild")
    if isinstance(guild, dict):
        return str(guild.get("rank") or "")
    return str(member.get("rank") or "")


def build_model(snapshots: list[tuple[str, dict[str, Any]]]) -> tuple[list[str], list[MemberRecord]]:
    dates = sorted(date for date, _ in snapshots)
    members: dict[str, MemberRecord] = {}

    for snapshot_date, snapshot in snapshots:
        for member in get_members(snapshot):
            if not isinstance(member, dict):
                continue
            member_id = str(member.get("id") or member.get("name") or "")
            if not member_id:
                continue

            record = members.get(member_id)
            if record is None:
                record = MemberRecord(
                    id=member_id,
                    latest_name=str(member.get("name") or member_id),
                    latest_level=member.get("level") or "",
                    latest_role=role_of(member),
                )
                members[member_id] = record

            record.latest_name = str(member.get("name") or record.latest_name)
            record.latest_level = member.get("level") or record.latest_level
            record.latest_role = role_of(member) or record.latest_role
            record.by_date[snapshot_date] = investment_of(member)

    latest_date = dates[-1] if dates else ""
    ordered = sorted(
        members.values(),
        key=lambda item: item.by_date.get(latest_date, 0),
        reverse=True,
    )
    return dates, ordered


def cell_value(member: MemberRecord, date: str, previous_date: str | None) -> str:
    current = member.by_date.get(date)
    if current is None:
        return "-"
    previous = member.by_date.get(previous_date) if previous_date else None
    if previous is None:
        return format_yi(current)
    return f"{format_yi(current)} ({format_delta(current - previous)})"


def top_investors(dates: list[str], members: list[MemberRecord], limit: int = 10) -> list[tuple[MemberRecord, int]]:
    if len(dates) < 2:
        return []
    first_date = dates[0]
    latest_date = dates[-1]
    gains: list[tuple[MemberRecord, int]] = []
    for member in members:
        start = member.by_date.get(first_date)
        end = member.by_date.get(latest_date)
        if start is None or end is None:
            continue
        gain = end - start
        if gain > 0:
            gains.append((member, gain))
    return sorted(gains, key=lambda item: item[1], reverse=True)[:limit]


def render_top_section(dates: list[str], members: list[MemberRecord]) -> str:
    lines = [
        "## 近30天新增投资额排行",
        "",
    ]
    ranking = top_investors(dates, members)
    if not ranking:
        lines.append("至少需要两天有效快照才能计算新增投资额排行。")
        return "\n".join(lines)

    lines.extend(
        [
            "| 排名 | 成员 | 等级 | 职位 | 近30天新增投资 |",
            "| ---: | --- | ---: | --- | ---: |",
        ]
    )
    for index, (member, gain) in enumerate(ranking, start=1):
        lines.append(
            "| "
            f"{index} | "
            f"{markdown_escape(member.latest_name)} | "
            f"{markdown_escape(member.latest_level)} | "
            f"{markdown_escape(member.latest_role)} | "
            f"{format_delta(gain)} |"
        )
    return "\n".join(lines)


def render_detail_table(dates: list[str], members: list[MemberRecord]) -> str:
    display_dates = list(reversed(dates))
    previous_by_date = {date: dates[index - 1] if index > 0 else None for index, date in enumerate(dates)}
    lines = [
        "## 近30天投资详情",
        "",
        "单元格格式：`累计投资额 (较上一快照变化)`。最新日期在左侧。",
        "",
        "| 成员 | 等级 | 职位 | " + " | ".join(display_dates) + " |",
        "| --- | ---: | --- | " + " | ".join(["---:"] * len(display_dates)) + " |",
    ]
    for member in members:
        values = [cell_value(member, date, previous_by_date[date]) for date in display_dates]
        lines.append(
            "| "
            f"{markdown_escape(member.latest_name)} | "
            f"{markdown_escape(member.latest_level)} | "
            f"{markdown_escape(member.latest_role)} | "
            + " | ".join(markdown_escape(value) for value in values)
            + " |"
        )
    return "\n".join(lines)


def render_failed_snapshots(failed: list[tuple[str, dict[str, Any]]]) -> str:
    if not failed:
        return ""
    lines = [
        "## 无效快照",
        "",
        "| 日期 | HTTP 状态 | 错误 |",
        "| --- | ---: | --- |",
    ]
    for snapshot_date, snapshot in failed[-10:]:
        error = snapshot.get("error")
        if isinstance(error, dict):
            error_text = error.get("error") or error.get("reason") or json.dumps(error, ensure_ascii=False)
        else:
            error_text = error
        lines.append(
            f"| {snapshot_date} | {snapshot.get('http_status', '-')} | {markdown_escape(error_text)} |"
        )
    return "\n".join(lines)


def build_readme(data_dir: Path, output_path: Path, days: int) -> None:
    loaded: list[tuple[str, dict[str, Any]]] = []
    failed: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(data_dir.glob("*.json")):
        if not SNAPSHOT_RE.match(path.name):
            continue
        snapshot = load_snapshot(path)
        if snapshot is None:
            continue
        item = (path.stem, snapshot)
        if snapshot.get("ok") is False:
            failed.append(item)
        else:
            loaded.append(item)

    recent = loaded[-days:]
    dates, members = build_model(recent)
    latest_date = dates[-1] if dates else "-"
    latest_total = sum(member.by_date.get(latest_date, 0) for member in members) if dates else 0
    latest_member_count = sum(1 for member in members if member.by_date.get(latest_date) is not None) if dates else 0
    updated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    sections = [
        "# TitansDB Guild Investment Snapshot",
        "",
        "<!-- This file is generated by scripts/build_readme.py. Do not edit the tables manually. -->",
        "",
        f"- 公会页面：{GUILD_URL}",
        f"- README 更新时间：{updated_at}",
        f"- 有效快照数量：{len(recent)} / 最近 {days} 天",
        f"- 最新快照日期：{latest_date}",
        f"- 最新成员数：{latest_member_count}",
        f"- 最新总投资：{format_yi(latest_total)}",
        "",
    ]

    if not recent:
        sections.extend(
            [
                "## 暂无有效快照",
                "",
                "请先运行 `python3 scripts/fetch_snapshot.py --output-dir data` 获取数据。",
            ]
        )
    else:
        sections.extend([render_top_section(dates, members), "", render_detail_table(dates, members)])

    failed_section = render_failed_snapshots(failed)
    if failed_section:
        sections.extend(["", failed_section])

    sections.extend(
        [
            "",
            "## 自动更新",
            "",
            "GitHub Actions 每天按 `.github/workflows/daily-snapshot.yml` 中的 cron 配置运行一次，当前默认是 UTC 01:00 / 北京时间 09:00。也可以在 GitHub Actions 页面通过 `Run workflow` 手动触发，并可选填写 `snapshot_date` 和 `readme_days`。",
            "",
            "每次运行会先拉取当天 JSON 到 `data/`，提交数据，再重新生成并提交本 README。同一天重复运行会更新同一个 `data/YYYY-MM-DD.json`；如果请求失败且当天已有成功快照，脚本会保留已有成功快照，避免被 cooldown、网络错误或 key 问题覆盖。",
            "",
        ]
    )
    output_path.write_text("\n".join(sections), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="README.md")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    build_readme((root / args.data_dir).resolve(), (root / args.output).resolve(), args.days)
    print((root / args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
