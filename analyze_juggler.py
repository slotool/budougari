import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3


def fmt_int(value):
    if value is None:
        return "-"
    return f"{round(value):,}"


def fmt_diff(value):
    if value is None:
        return "-"
    return f"{round(value):,}"


def pct(value):
    if value is None:
        return "-"
    return f"{value:.1f}%"


def event_for_date(report_date):
    day = dt.date.fromisoformat(report_date).day
    ones = day % 10
    if ones == 3:
        return "末尾系イベント"
    if ones == 5:
        return "ジャグラー強め"
    if ones == 6:
        return "メリハリ設定"
    if ones == 9:
        return "並び・全台系イベント"
    return "通常/その他"


def load_config(path="config.json"):
    file_path = Path(path)
    if not file_path.exists():
        return {"targets": []}
    return json.loads(file_path.read_text(encoding="utf-8"))


def hall_config(hall_name, config):
    for target in config.get("targets", []):
        if target.get("name") == hall_name:
            return target
    return {}


def configured_event_for_date(report_date, hall_rule_config):
    rules = hall_rule_config.get("event_rules") or {}
    ones = str(dt.date.fromisoformat(report_date).day % 10)
    rule = rules.get(ones)
    if rule:
        return rule.get("type") or "通常/その他"
    return "通常/その他"


def next_event(today=None):
    today = today or dt.date.today()
    for offset in range(1, 15):
        candidate = today + dt.timedelta(days=offset)
        event = event_for_date(candidate.isoformat())
        if event != "通常/その他":
            return candidate, event
    return today + dt.timedelta(days=1), "通常/その他"


def next_juggler_event(today=None):
    today = today or dt.date.today()
    for offset in range(1, 32):
        candidate = today + dt.timedelta(days=offset)
        if candidate.day % 10 == 5:
            return candidate, "ジャグラー強め"
    return next_event(today)


def weekday_jp(date_value):
    return "月火水木金土日"[date_value.weekday()]


def effective_diff(row):
    return row["avg_diff"]


def average_effective(rows):
    values = [effective_diff(row) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def fetch_rows(conn, hall_name):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        select mr.report_date, mr.machine_name, mr.unit_no, mr.avg_diff, mr.avg_game, mr.payout_rate,
               dr.event_type
        from machine_reports mr
        join daily_reports dr
          on dr.hall_key = mr.hall_key
         and dr.report_date = mr.report_date
        where mr.category = 'unit'
          and dr.hall_name = ?
          and mr.machine_name like '%ジャグラー%'
          and mr.unit_no is not null
        order by mr.report_date desc, mr.unit_no
        """,
        (hall_name,),
    ).fetchall()


def summarize(rows, target_event):
    by_unit = {}
    latest_date = max((row["report_date"] for row in rows), default=None)
    current_units = {row["unit_no"] for row in rows if row["report_date"] == latest_date}
    current_machine_units = {}
    for row in rows:
        if row["report_date"] != latest_date:
            continue
        current_machine_units.setdefault(row["machine_name"], []).append(row["unit_no"])
    for row in rows:
        unit = row["unit_no"]
        by_unit.setdefault(
            unit,
            {
                "unit_no": unit,
                "machine_names": set(),
                "rows": [],
                "event_rows": [],
                "recent_rows": [],
                "latest": None,
            },
        )
        item = by_unit[unit]
        item["machine_names"].add(row["machine_name"])
        item["rows"].append(row)
        if row["event_type"] == target_event:
            item["event_rows"].append(row)

    all_dates = sorted({row["report_date"] for row in rows}, reverse=True)
    recent_dates = set(all_dates[:7])
    for item in by_unit.values():
        item["recent_rows"] = [row for row in item["rows"] if row["report_date"] in recent_dates]
        item["latest"] = max(item["rows"], key=lambda row: row["report_date"])

    summaries = []
    for item in by_unit.values():
        if item["unit_no"] not in current_units:
            continue
        rows_all = item["rows"]
        recent_rows = item["recent_rows"]
        event_rows = item["event_rows"] or []
        latest = item["latest"]
        current_machine = latest["machine_name"]
        current_units_for_machine = current_machine_units.get(current_machine, [])
        is_corner = bool(
            current_units_for_machine
            and item["unit_no"] in {min(current_units_for_machine), max(current_units_for_machine)}
        )

        avg_diff = average_effective(rows_all)
        recent_avg = average_effective(recent_rows) if recent_rows else None
        event_avg = average_effective(event_rows) if event_rows else None
        positive_rate = sum(1 for r in rows_all if (effective_diff(r) or 0) > 0) / len(rows_all) * 100
        event_positive = (
            sum(1 for r in event_rows if (effective_diff(r) or 0) > 0) / len(event_rows) * 100
            if event_rows
            else None
        )
        latest_diff = effective_diff(latest)
        latest_diff = latest_diff or 0
        latest_game = latest["avg_game"] or 0

        # Score favors target-event history, recent weakness with enough games, and avoids chasing a huge latest win.
        score = 0.0
        score += (event_avg if event_avg is not None else avg_diff or 0) * 0.35
        score += (recent_avg if recent_avg is not None else avg_diff or 0) * 0.15
        score += positive_rate * 8
        if event_positive is not None:
            score += event_positive * 5
        if latest_diff < -500 and latest_game >= 3000:
            score += min(abs(latest_diff), 2500) * 0.35
        elif latest_diff > 2500:
            score -= min(latest_diff, 5000) * 0.3
        if latest_game < 1500:
            score -= 250

        summaries.append(
            {
                "unit_no": item["unit_no"],
                "machines": " / ".join(sorted(item["machine_names"])),
                "current_machine": current_machine,
                "is_corner": is_corner,
                "count": len(rows_all),
                "event_count": len(event_rows),
                "avg_diff": avg_diff,
                "recent_avg": recent_avg,
                "event_avg": event_avg,
                "positive_rate": positive_rate,
                "event_positive": event_positive,
                "latest_date": latest["report_date"],
                "latest_diff": latest_diff,
                "latest_game": latest_game,
                "score": score,
            }
        )
    return sorted(summaries, key=lambda row: row["score"], reverse=True), latest_date, len(current_units)


def machine_groups(summaries):
    grouped = {}
    for row in summaries:
        grouped.setdefault(row["current_machine"], []).append(row)
    return {name: sorted(rows, key=lambda item: item["score"], reverse=True) for name, rows in sorted(grouped.items())}


def normalize_name(value):
    return (value or "").replace(" ", "").replace("　", "").lower()


def load_recommended_machines(path, hall_name, target_date):
    file_path = Path(path)
    if not file_path.exists():
        return []
    items = json.loads(file_path.read_text(encoding="utf-8"))
    target = dt.date.fromisoformat(target_date)
    machines = []
    for item in items:
        if item.get("hall") != hall_name:
            continue
        start = dt.date.fromisoformat(item["start_date"])
        end = dt.date.fromisoformat(item["end_date"])
        if start <= target <= end:
            machines.extend(item.get("machines") or [])
    return machines


def apply_recommendation_boost(summaries, recommended_machines):
    normalized = [normalize_name(name) for name in recommended_machines if name]
    for row in summaries:
        current = normalize_name(row["current_machine"])
        matched = [name for name, norm in zip(recommended_machines, normalized) if norm and norm in current]
        row["recommended"] = bool(matched)
        row["recommended_match"] = " / ".join(matched)
        if row["recommended"]:
            row["score"] += 450
    return sorted(summaries, key=lambda row: row["score"], reverse=True)


def apply_weekday_boost(summaries, target_date):
    weekday = weekday_jp(target_date)
    notes = []

    if weekday == "土":
        notes.append("土曜日補正: 各機種に満遍なく当たりがある想定で、機種ごとの上位台を加点。")
        grouped = machine_groups(summaries)
        for rows in grouped.values():
            for idx, row in enumerate(rows[:3], 1):
                if idx == 1:
                    row["score"] += 320
                    row["weekday_boost"] = row.get("weekday_boost", 0) + 320
                elif idx == 2:
                    row["score"] += 160
                    row["weekday_boost"] = row.get("weekday_boost", 0) + 160
                else:
                    row["score"] += 80
                    row["weekday_boost"] = row.get("weekday_boost", 0) + 80

    elif weekday == "日":
        notes.append("日曜日補正: 土曜日に不発・凹んだ台を戻し候補として加点。")
        for row in summaries:
            latest_diff = row["latest_diff"] or 0
            latest_game = row["latest_game"] or 0
            if latest_diff < -500 and latest_game >= 2500:
                boost = min(abs(latest_diff), 2500) * 0.35
                row["score"] += boost
                row["weekday_boost"] = row.get("weekday_boost", 0) + boost
            elif latest_diff <= 0 and latest_game >= 4000:
                row["score"] += 180
                row["weekday_boost"] = row.get("weekday_boost", 0) + 180

    return sorted(summaries, key=lambda row: row["score"], reverse=True), notes


def apply_hall_rule_boost(summaries, target_date, hall_rule_config):
    notes = []
    weekday = weekday_jp(target_date)
    weekday_rule = (hall_rule_config.get("weekday_rules") or {}).get(weekday)
    if weekday_rule:
        rule_type = weekday_rule.get("type", "")
        if "満遍" in rule_type or "各機種" in rule_type:
            notes.append(f"{weekday}曜日補正: {weekday_rule.get('note', rule_type)}")
            grouped = machine_groups(summaries)
            for rows in grouped.values():
                for idx, row in enumerate(rows[:3], 1):
                    boost = 320 if idx == 1 else 160 if idx == 2 else 80
                    row["score"] += boost
                    row["weekday_boost"] = row.get("weekday_boost", 0) + boost
        elif "土曜不発" in rule_type or "凹み" in rule_type:
            notes.append(f"{weekday}曜日補正: {weekday_rule.get('note', rule_type)}")
            for row in summaries:
                latest_diff = row["latest_diff"] or 0
                latest_game = row["latest_game"] or 0
                if latest_diff < -500 and latest_game >= 2500:
                    boost = min(abs(latest_diff), 2500) * 0.35
                    row["score"] += boost
                    row["weekday_boost"] = row.get("weekday_boost", 0) + boost
                elif latest_diff <= 0 and latest_game >= 4000:
                    row["score"] += 180
                    row["weekday_boost"] = row.get("weekday_boost", 0) + 180

    if hall_rule_config.get("corner_rules", {}).get("enabled"):
        note = hall_rule_config["corner_rules"].get("note", "角台を加点。")
        notes.append(f"角台補正: {note}")
        for row in summaries:
            if row.get("is_corner"):
                row["score"] += 420
                row["corner_boost"] = row.get("corner_boost", 0) + 420

    return sorted(summaries, key=lambda row: row["score"], reverse=True), notes


def write_report(db_path, hall_name, output_path, target_date=None, recommendations_path="weekly_recommendations.json", config_path="config.json"):
    conn = sqlite3.connect(db_path)
    rows = fetch_rows(conn, hall_name)
    config = load_config(config_path)
    rules = hall_config(hall_name, config)
    if target_date is None:
        target_date, target_event = next_juggler_event()
    else:
        target_date = dt.date.fromisoformat(target_date)
        target_event = configured_event_for_date(target_date.isoformat(), rules)
    summaries, latest_date, current_unit_count = summarize(rows, target_event)
    recommended_machines = load_recommended_machines(recommendations_path, hall_name, target_date.isoformat())
    summaries = apply_recommendation_boost(summaries, recommended_machines)
    summaries, rule_notes = apply_hall_rule_boost(summaries, target_date, rules)

    lines = [
        "# ジャグラー系 台番分析",
        "",
        f"対象店舗: {hall_name}",
        f"次の想定イベント日: {target_date.isoformat()} ({target_event})",
        f"分析対象の最新日: {latest_date or '-'}",
        f"現在存在するジャグラー台番数: {current_unit_count}",
        f"ジャグラー系レコード数: {len(rows)}",
        f"今週のおすすめ機種: {', '.join(recommended_machines) if recommended_machines else '-'}",
        f"店舗ルール補正: {' / '.join(rule_notes) if rule_notes else '-'}",
        "",
        "## 次に入りやすそうな台番候補",
        "",
        "| 順位 | 台番 | 機種 | 角 | おすすめ | ルール補正 | スコア | 対象イベント平均差枚 | 直近平均差枚 | 全体プラス率 | 最新差枚 | 最新G |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for idx, row in enumerate(summaries[:15], 1):
        lines.append(
            f"| {idx} | {row['unit_no']} | {row['current_machine']} | {'○' if row.get('is_corner') else ''} | {'○' if row['recommended'] else ''} | {fmt_int((row.get('weekday_boost') or 0) + (row.get('corner_boost') or 0))} | {fmt_int(row['score'])} | "
            f"{fmt_int(row['event_avg'])} | {fmt_int(row['recent_avg'])} | {pct(row['positive_rate'])} | "
            f"{fmt_diff(row['latest_diff'])} | {fmt_int(row['latest_game'])} |"
        )

    lines.extend(
        [
            "",
            "## 機種別 狙い台",
            "",
        ]
    )

    for machine_name, machine_rows in machine_groups(summaries).items():
        lines.extend(
            [
                f"### {machine_name}",
                "",
                "| 順位 | 台番 | 角 | おすすめ | ルール補正 | スコア | 対象イベント平均差枚 | 直近平均差枚 | 全体プラス率 | 最新差枚 | 最新G |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for idx, row in enumerate(machine_rows[:8], 1):
            lines.append(
                f"| {idx} | {row['unit_no']} | {'○' if row.get('is_corner') else ''} | {'○' if row['recommended'] else ''} | {fmt_int((row.get('weekday_boost') or 0) + (row.get('corner_boost') or 0))} | {fmt_int(row['score'])} | {fmt_int(row['event_avg'])} | "
                f"{fmt_int(row['recent_avg'])} | {pct(row['positive_rate'])} | {fmt_diff(row['latest_diff'])} | "
                f"{fmt_int(row['latest_game'])} |"
            )
        lines.append("")

    lines.extend(
        [
            "",
            "## 見方",
            "",
            "- スコアは、次のイベント種別との相性、直近の履歴、最新日の凹み具合を混ぜた目安です。",
            "- 今週のおすすめ機種に指定された機種は、扱いが良い前提でスコアを加点しています。",
            "- 土曜日は各機種に当たりがある想定で、機種ごとの上位台に曜日補正を入れています。",
            "- 日曜日は土曜日に不発・凹みだった台を戻し候補として加点します。",
            "- 角台が強い店舗では、現行機種ごとの先頭台・末尾台を角台として加点しています。",
            "- 最新日に大きく出た台は少し減点し、よく回されて凹んだ台は加点しています。",
            "- マイナス差枚は `-1,000`、`−1,000`、`－1,000` などの符号表記を正規化して取り込みます。",
            "- 台番配置や入替で機種が変わっている可能性があるため、実戦前に島図・当日設置を確認してください。",
        ]
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")


def main():
    parser = argparse.ArgumentParser(description="Analyze Juggler units from min-repo stored data.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    parser.add_argument("--hall", default="パーラーゾーン姪浜")
    parser.add_argument("--out", default="reports/juggler_analysis.md")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to the next 5 day.")
    parser.add_argument("--recommendations", default="weekly_recommendations.json")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    write_report(args.db, args.hall, args.out, args.date, args.recommendations, args.config)


if __name__ == "__main__":
    main()
