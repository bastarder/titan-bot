#!/usr/bin/env python3
"""Build root README and per-guild reports from member-centric TitansDB data."""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guild_config import GuildConfig, load_guilds
from member_store import GUILD_MEMBERS_FILENAME, MEMBERS_FILENAME, read_json_object


HUNDRED_MILLION = 100_000_000
AUTO_UPDATE_TEXT = (
    "GitHub Actions 每天按 `.github/workflows/daily-snapshot.yml` 中的 cron 配置运行一次，"
    "当前配置是 Asia/Shanghai 09:18。也可以在 GitHub Actions 页面通过 `Run workflow` "
    "手动触发，并可选填写 `snapshot_date` 和 `readme_days`。"
)


@dataclass
class MemberRecord:
    id: str
    latest_name: str
    latest_level: Any = ""
    latest_role: str = ""
    by_date: dict[str, int] = field(default_factory=dict)


@dataclass
class GuildSummary:
    guild: GuildConfig
    report_path: Path
    updated_at: str
    valid_count: int
    days: int
    latest_date: str
    latest_member_count: int
    latest_total: int


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


def load_required_json(path: Path) -> dict[str, Any]:
    payload = read_json_object(path)
    if payload is None:
        raise FileNotFoundError(f"Missing or invalid JSON: {path}")
    return payload


def numeric_investments(record: dict[str, Any]) -> dict[str, int]:
    investments = record.get("investments")
    if not isinstance(investments, dict):
        return {}

    values: dict[str, int] = {}
    for date, value in investments.items():
        try:
            values[str(date)] = int(value)
        except (TypeError, ValueError):
            continue
    return values


def build_model(
    guild_entry: dict[str, Any],
    member_store: dict[str, Any],
    days: int,
) -> tuple[list[str], list[MemberRecord], int]:
    all_members = member_store.get("members")
    if not isinstance(all_members, dict):
        all_members = {}

    raw_guild_members = guild_entry.get("members")
    guild_members = raw_guild_members if isinstance(raw_guild_members, list) else []
    dates: set[str] = set()
    records: list[MemberRecord] = []

    for item in guild_members:
        if not isinstance(item, dict):
            continue
        member_id = str(item.get("id") or "").strip()
        if not member_id:
            continue
        stored = all_members.get(member_id)
        if not isinstance(stored, dict):
            continue
        by_date = numeric_investments(stored)
        dates.update(by_date)
        records.append(
            MemberRecord(
                id=member_id,
                latest_name=str(item.get("name") or stored.get("name") or member_id),
                latest_level=stored.get("level") or "",
                latest_role=str(stored.get("role") or ""),
                by_date=by_date,
            )
        )

    recent_dates = sorted(dates)[-days:]
    recent_date_set = set(recent_dates)
    for record in records:
        record.by_date = {
            date: value
            for date, value in record.by_date.items()
            if date in recent_date_set
        }

    latest_date = recent_dates[-1] if recent_dates else ""
    ordered = sorted(
        records,
        key=lambda item: item.by_date.get(latest_date, 0),
        reverse=True,
    )
    return recent_dates, ordered, len(guild_members)


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
        lines.append("至少需要两天有效投资数据才能计算新增投资额排行。")
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
        "单元格格式：`累计投资额 (较上一投资记录变化)`。最新日期在左侧。",
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


def build_guild_report(
    guild: GuildConfig,
    guild_entry: dict[str, Any],
    member_store: dict[str, Any],
    report_path: Path,
    days: int,
) -> GuildSummary:
    dates, members, listed_member_count = build_model(guild_entry, member_store, days)
    latest_date = dates[-1] if dates else "-"
    latest_total = sum(member.by_date.get(latest_date, 0) for member in members) if dates else 0
    latest_member_count = listed_member_count
    updated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    sections = [
        f"# {guild.name} TitansDB 投资快照",
        "",
        "<!-- This file is generated by scripts/build_readme.py. Do not edit the tables manually. -->",
        "",
        f"- 公会页面：{guild.guild_url}",
        f"- Guild ID：`{guild.guild_id}`",
        f"- README 更新时间：{updated_at}",
        f"- 有效投资日期数量：{len(dates)} / 最近 {days} 天",
        f"- 最新公会成员日期：{guild_entry.get('snapshot_date') or '-'}",
        f"- 最新投资日期：{latest_date}",
        f"- 最新成员数：{latest_member_count}",
        f"- 最新总投资：{format_yi(latest_total)}",
        "",
    ]

    if not dates:
        sections.extend(
            [
                "## 暂无有效投资数据",
                "",
                f"请先运行 `python3 scripts/fetch_snapshot.py --guild-slug {guild.slug}` 获取数据。",
            ]
        )
    else:
        sections.extend([render_top_section(dates, members), "", render_detail_table(dates, members)])

    sections.extend(
        [
            "",
            "## 自动更新",
            "",
            AUTO_UPDATE_TEXT,
            "",
            f"每次运行会拉取 `{guild.name}` 的最新公会成员，并更新 `data/{MEMBERS_FILENAME}` 中每个成员在指定日期的投资值，同时刷新 `data/{GUILD_MEMBERS_FILENAME}` 中该公会的最新成员列表。",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(sections), encoding="utf-8")

    return GuildSummary(
        guild=guild,
        report_path=report_path,
        updated_at=updated_at,
        valid_count=len(dates),
        days=days,
        latest_date=latest_date,
        latest_member_count=latest_member_count,
        latest_total=latest_total,
    )


def relative_markdown_path(from_path: Path, to_path: Path) -> str:
    return to_path.relative_to(from_path.parent).as_posix()


def build_root_readme(output_path: Path, summaries: list[GuildSummary]) -> None:
    updated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = [
        "# TitansDB Guild Investment Snapshots",
        "",
        "<!-- This file is generated by scripts/build_readme.py. Do not edit the tables manually. -->",
        "",
        f"- README 更新时间：{updated_at}",
        f"- 已配置公会数量：{len(summaries)}",
        "- 网页看板：启用 GitHub Pages 后访问仓库 Pages 地址，页面入口为 `index.html`。",
        "",
        "## 公会报告",
        "",
        "| 公会 | Guild ID | 最新投资日期 | 最新成员数 | 最新总投资 | 有效日期 | 报告 | TitansDB |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]

    for summary in summaries:
        report_link = relative_markdown_path(output_path, summary.report_path)
        lines.append(
            "| "
            f"{markdown_escape(summary.guild.name)} | "
            f"`{summary.guild.guild_id}` | "
            f"{summary.latest_date} | "
            f"{summary.latest_member_count} | "
            f"{format_yi(summary.latest_total)} | "
            f"{summary.valid_count} / {summary.days} | "
            f"[查看报告]({report_link}) | "
            f"[打开]({summary.guild.guild_url}) |"
        )

    lines.extend(
        [
            "",
            "## 自动更新",
            "",
            AUTO_UPDATE_TEXT,
            "",
            f"公会列表在 `config/guilds.json` 中维护；成员投资历史集中保存在 `data/{MEMBERS_FILENAME}`；每个公会的最新成员列表保存在 `data/{GUILD_MEMBERS_FILENAME}`；每个公会的详细报告生成到 `reports/`。",
            "",
            f"静态网页看板通过 `index.html` 读取 `data/{MEMBERS_FILENAME}` 和 `data/{GUILD_MEMBERS_FILENAME}` 后在浏览器端汇总展示，不再依赖 `data/pages-index.json` 或每日快照清单。",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_readmes(config_path: Path, data_dir: Path, reports_dir: Path, output_path: Path, days: int) -> None:
    guilds = load_guilds(config_path)
    member_store = load_required_json(data_dir / MEMBERS_FILENAME)
    guild_store = load_required_json(data_dir / GUILD_MEMBERS_FILENAME)
    guild_entries = guild_store.get("guilds") if isinstance(guild_store.get("guilds"), dict) else {}

    summaries = [
        build_guild_report(
            guild=guild,
            guild_entry=guild_entries.get(guild.slug, {}) if isinstance(guild_entries, dict) else {},
            member_store=member_store,
            report_path=reports_dir / f"{guild.slug}.md",
            days=days,
        )
        for guild in guilds
    ]
    build_root_readme(output_path, summaries)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/guilds.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--output", default="README.md")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    build_readmes(
        config_path=(root / args.config).resolve(),
        data_dir=(root / args.data_dir).resolve(),
        reports_dir=(root / args.reports_dir).resolve(),
        output_path=(root / args.output).resolve(),
        days=args.days,
    )
    print((root / args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
