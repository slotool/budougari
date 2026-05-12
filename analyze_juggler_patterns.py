import argparse
import datetime as dt
from pathlib import Path
import sqlite3


DEFAULT_HALL = "パーラーゾーン姪浜"


def fmt_int(value):
    if value is None:
        return "-"
    return f"{round(value):,}"


def pct(value):
    if value is None:
        return "-"
    return f"{value:.1f}%"


def weekday_jp(date_text):
    return "月火水木金土日"[dt.date.fromisoformat(date_text).weekday()]


def event_label(report_date, db_event_type):
    if db_event_type:
        return db_event_type
    return "通常/その他"


def load_rows(conn, hall_name):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        select mr.report_date, mr.machine_name, mr.unit_no, mr.avg_diff, mr.avg_game, mr.payout_rate,
               dr.event_type
          from machine_reports mr
          join daily_reports dr
            on dr.hall_key = mr.hall_key
           and dr.report_date = mr.report_date
         where dr.hall_name = ?
           and mr.category = 'unit'
           and mr.machine_name like '%ジャグラー%'
           and mr.unit_no is not null
         order by mr.report_date, mr.unit_no
        """,
        (hall_name,),
    ).fetchall()


def summarize_group(rows, key_func):
    groups = {}
    for row in rows:
        key = key_func(row)
        groups.setdefault(key, []).append(row)

    result = []
    for key, items in groups.items():
        diffs = [row["avg_diff"] or 0 for row in items]
        games = [row["avg_game"] or 0 for row in items]
        result.append(
            {
                "key": key,
                "units": len(items),
                "days": len({row["report_date"] for row in items}),
                "avg_diff": sum(diffs) / len(diffs),
                "avg_game": sum(games) / len(games),
                "positive_rate": sum(1 for value in diffs if value > 0) / len(diffs) * 100,
                "big_win_rate": sum(1 for value in diffs if value >= 1000) / len(diffs) * 100,
                "big_loss_rate": sum(1 for value in diffs if value <= -1000) / len(diffs) * 100,
            }
        )
    return sorted(result, key=lambda row: row["avg_diff"], reverse=True)


def previous_day_map(rows):
    by_unit_date = {(row["unit_no"], row["report_date"]): row for row in rows}
    dates = sorted({row["report_date"] for row in rows})
    prev_date = {}
    for idx, date_text in enumerate(dates[1:], 1):
        prev_date[date_text] = dates[idx - 1]
    return by_unit_date, prev_date


def transition_analysis(rows, target_event_name):
    by_unit_date, prev_date = previous_day_map(rows)
    buckets = {
        "前日-1000枚以下": [],
        "前日-500枚以下": [],
        "前日0付近": [],
        "前日+1000枚以上": [],
        "前日+2000枚以上": [],
    }
    for row in rows:
        label = event_label(row["report_date"], row["event_type"])
        if label != target_event_name:
            continue
        prev = by_unit_date.get((row["unit_no"], prev_date.get(row["report_date"])))
        if not prev:
            continue
        prev_diff = prev["avg_diff"] or 0
        if prev_diff <= -1000:
            buckets["前日-1000枚以下"].append(row)
        if prev_diff <= -500:
            buckets["前日-500枚以下"].append(row)
        if -300 <= prev_diff <= 300:
            buckets["前日0付近"].append(row)
        if prev_diff >= 1000:
            buckets["前日+1000枚以上"].append(row)
        if prev_diff >= 2000:
            buckets["前日+2000枚以上"].append(row)
    return summarize_bucket_rows(buckets)


def summarize_bucket_rows(buckets):
    result = []
    for key, items in buckets.items():
        if not items:
            result.append({"key": key, "units": 0, "avg_diff": None, "positive_rate": None, "avg_game": None})
            continue
        diffs = [row["avg_diff"] or 0 for row in items]
        games = [row["avg_game"] or 0 for row in items]
        result.append(
            {
                "key": key,
                "units": len(items),
                "avg_diff": sum(diffs) / len(diffs),
                "positive_rate": sum(1 for value in diffs if value > 0) / len(diffs) * 100,
                "avg_game": sum(games) / len(games),
            }
        )
    return result


def top_previous_rank_analysis(rows, target_event_name):
    by_date = {}
    for row in rows:
        by_date.setdefault(row["report_date"], []).append(row)
    dates = sorted(by_date)
    buckets = {"前日上位10台": [], "前日下位10台": [], "前日中間": []}
    for idx, date_text in enumerate(dates[1:], 1):
        label = event_label(date_text, by_date[date_text][0]["event_type"])
        if label != target_event_name:
            continue
        prev_rows = sorted(by_date[dates[idx - 1]], key=lambda row: row["avg_diff"] or 0, reverse=True)
        top = {row["unit_no"] for row in prev_rows[:10]}
        bottom = {row["unit_no"] for row in prev_rows[-10:]}
        for row in by_date[date_text]:
            if row["unit_no"] in top:
                buckets["前日上位10台"].append(row)
            elif row["unit_no"] in bottom:
                buckets["前日下位10台"].append(row)
            else:
                buckets["前日中間"].append(row)
    return summarize_bucket_rows(buckets)


def corner_analysis(rows):
    by_date_machine = {}
    for row in rows:
        by_date_machine.setdefault((row["report_date"], row["machine_name"]), []).append(row)

    buckets = {"角台": [], "角以外": []}
    for items in by_date_machine.values():
        units = [row["unit_no"] for row in items]
        corners = {min(units), max(units)}
        for row in items:
            buckets["角台" if row["unit_no"] in corners else "角以外"].append(row)
    return summarize_bucket_rows(buckets)


def write_report(hall_name, output_path):
    conn = sqlite3.connect("data/minrepo.sqlite")
    rows = load_rows(conn, hall_name)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    by_event = summarize_group(rows, lambda row: event_label(row["report_date"], row["event_type"]))
    by_weekday = summarize_group(rows, lambda row: weekday_jp(row["report_date"]))
    by_machine_event = summarize_group(
        rows,
        lambda row: f"{event_label(row['report_date'], row['event_type'])} / {row['machine_name']}",
    )
    normal_transition = transition_analysis(rows, "通常/その他")
    normal_rank = top_previous_rank_analysis(rows, "通常/その他")
    event_names = [
        row["key"]
        for row in by_event
        if row["key"] != "通常/その他"
    ]
    corner_rows = corner_analysis(rows)

    lines = [
        "# ジャグラー傾向検証",
        "",
        f"対象店舗: {hall_name}",
        f"対象レコード数: {len(rows)}",
        "",
        "## イベント種別別",
        "",
        "| 種別 | 日数 | 台数 | 平均差枚 | プラス率 | 1000枚以上率 | -1000枚以下率 | 平均G |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_event:
        lines.append(
            f"| {row['key']} | {row['days']} | {row['units']} | {fmt_int(row['avg_diff'])} | "
            f"{pct(row['positive_rate'])} | {pct(row['big_win_rate'])} | {pct(row['big_loss_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    lines.extend(
        [
            "",
            "## 曜日別",
            "",
            "| 曜日 | 日数 | 台数 | 平均差枚 | プラス率 | 1000枚以上率 | -1000枚以下率 | 平均G |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in by_weekday:
        lines.append(
            f"| {row['key']} | {row['days']} | {row['units']} | {fmt_int(row['avg_diff'])} | "
            f"{pct(row['positive_rate'])} | {pct(row['big_win_rate'])} | {pct(row['big_loss_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    lines.extend(
        [
            "",
            "## 前日差枚別: 通常日",
            "",
            "| 条件 | 台数 | 翌日平均差枚 | 翌日プラス率 | 翌日平均G |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in normal_transition:
        lines.append(
            f"| {row['key']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    lines.extend(
        [
            "",
            "## 前日順位別: 通常日",
            "",
            "| 条件 | 台数 | 翌日平均差枚 | 翌日プラス率 | 翌日平均G |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in normal_rank:
        lines.append(
            f"| {row['key']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    for event_name in event_names:
        lines.extend(
            [
                "",
                f"## 前日差枚別: {event_name}",
                "",
                "| 条件 | 台数 | 翌日平均差枚 | 翌日プラス率 | 翌日平均G |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in transition_analysis(rows, event_name):
            lines.append(
                f"| {row['key']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
            )

        lines.extend(
            [
                "",
                f"## 前日順位別: {event_name}",
                "",
                "| 条件 | 台数 | 翌日平均差枚 | 翌日プラス率 | 翌日平均G |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in top_previous_rank_analysis(rows, event_name):
            lines.append(
                f"| {row['key']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
            )

    lines.extend(
        [
            "",
            "## 角台傾向",
            "",
            "| 条件 | 台数 | 平均差枚 | プラス率 | 平均G |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in corner_rows:
        lines.append(
            f"| {row['key']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    lines.extend(
        [
            "",
            "## 種別 x 機種 上位",
            "",
            "| 種別 / 機種 | 日数 | 台数 | 平均差枚 | プラス率 | 平均G |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in by_machine_event[:25]:
        lines.append(
            f"| {row['key']} | {row['days']} | {row['units']} | {fmt_int(row['avg_diff'])} | {pct(row['positive_rate'])} | {fmt_int(row['avg_game'])} |"
        )

    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")


def main():
    parser = argparse.ArgumentParser(description="Analyze Juggler patterns by hall.")
    parser.add_argument("--hall", default=DEFAULT_HALL)
    parser.add_argument("--out", default="reports/juggler_pattern_analysis.md")
    args = parser.parse_args()
    write_report(args.hall, args.out)


if __name__ == "__main__":
    main()
