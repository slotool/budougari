import argparse
import datetime as dt
from pathlib import Path
import sqlite3


def fmt_int(value):
    if value is None:
        return "-"
    return f"{value:,}"


def pct(value):
    if value is None:
        return "-"
    return f"{value:.1f}%"


def query(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, params).fetchall()


def build_report(db_path, output_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    halls = query(
        conn,
        """
        select hall_key, hall_name, count(*) days,
               min(report_date) first_date, max(report_date) last_date,
               avg(avg_diff) avg_of_avg_diff,
               avg(avg_game) avg_game,
               sum(case when coalesce(total_diff, avg_diff) is not null then 1 else 0 end) known_days,
               sum(case when coalesce(total_diff, avg_diff) > 0 then 1 else 0 end) positive_days
        from daily_reports
        group by hall_key, hall_name
        order by hall_name
        """,
    )

    recent = query(
        conn,
        """
        select hall_name, report_date, weekday, event_type,
               coalesce(total_diff, avg_diff) as display_total_diff,
               total_diff, avg_diff, avg_game, featured
        from daily_reports
        order by report_date desc, hall_name
        limit 20
        """,
    )

    weekday = query(
        conn,
        """
        select hall_name, weekday, count(*) days, avg(avg_diff) avg_diff, avg(avg_game) avg_game,
               sum(case when coalesce(total_diff, avg_diff) is not null then 1 else 0 end) known_days,
               sum(case when coalesce(total_diff, avg_diff) > 0 then 1 else 0 end) positive_days
        from daily_reports
        where avg_diff is not null
        group by hall_name, weekday
        having days >= 2
        order by hall_name, avg_diff desc
        """,
    )

    events = query(
        conn,
        """
        select hall_name, event_type, count(*) days,
               sum(case when coalesce(total_diff, avg_diff) is not null then 1 else 0 end) known_days,
               sum(case when coalesce(total_diff, avg_diff) > 0 then 1 else 0 end) positive_days,
               avg(avg_diff) avg_diff,
               avg(avg_game) avg_game,
               avg(coalesce(total_diff, avg_diff)) avg_total_diff
        from daily_reports
        where event_type is not null
        group by hall_name, event_type
        order by hall_name, avg_diff desc
        """,
    )

    machines = query(
        conn,
        """
        select machine_name, count(*) appearances, avg(avg_diff) avg_diff, avg(avg_game) avg_game,
               avg(payout_rate) payout_rate
        from machine_reports
        where category = 'machine' and avg_diff is not null
        group by machine_name
        having appearances >= 2
        order by avg_diff desc
        limit 20
        """,
    )

    meinohama_tails = query(
        conn,
        """
        select dr.event_type,
               mr.unit_no % 10 as tail,
               count(*) units,
               sum(case when mr.avg_diff > 0 then 1 else 0 end) positive_units,
               avg(mr.avg_diff) avg_diff,
               avg(mr.avg_game) avg_game
        from machine_reports mr
        join daily_reports dr
          on dr.hall_key = mr.hall_key
         and dr.report_date = mr.report_date
        where dr.hall_name = 'パーラーゾーン姪浜'
          and dr.event_type is not null
          and mr.category = 'unit'
          and mr.unit_no is not null
        group by dr.event_type, tail
        having units >= 3
        order by dr.event_type, avg_diff desc
        """,
    )

    lines = [
        "# min-repo 蓄積データ分析",
        "",
        f"生成日時: {generated}",
        "",
        "## 店舗別サマリー",
        "",
        "| 店舗 | 期間 | 日数 | プラス日率 | 平均差枚の平均 | 平均G |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for row in halls:
        positive_rate = row["positive_days"] / row["known_days"] * 100 if row["known_days"] else None
        lines.append(
            f"| {row['hall_name']} | {row['first_date']} - {row['last_date']} | {row['days']} | "
            f"{pct(positive_rate)} | {fmt_int(round(row['avg_of_avg_diff']))} | {fmt_int(round(row['avg_game']))} |"
        )

    lines.extend(
        [
            "",
            "## 直近データ",
            "",
            "| 店舗 | 日付 | 総差枚 | 平均差枚 | 平均G | 注目 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in recent:
        event = f" [{row['event_type']}]" if row["event_type"] else ""
        featured = " / ".join([x for x in (row["featured"] or "").splitlines()[:3]])
        lines.append(
            f"| {row['hall_name']} | {row['report_date']}({row['weekday']}){event} | {fmt_int(row['display_total_diff'])} | "
            f"{fmt_int(row['avg_diff'])} | {fmt_int(row['avg_game'])} | {featured} |"
        )

    lines.extend(
        [
            "",
            "## 曜日傾向",
            "",
            "| 店舗 | 曜日 | 日数 | プラス日率 | 平均差枚の平均 | 平均G |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in weekday:
        positive_rate = row["positive_days"] / row["known_days"] * 100 if row["known_days"] else None
        lines.append(
            f"| {row['hall_name']} | {row['weekday']} | {row['days']} | {pct(positive_rate)} | "
            f"{fmt_int(round(row['avg_diff']))} | {fmt_int(round(row['avg_game']))} |"
        )

    lines.extend(
        [
            "",
            "## イベント種別傾向",
            "",
            "| 店舗 | イベント | 日数 | プラス日率 | 平均総差枚 | 平均差枚の平均 | 平均G |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    if events:
        for row in events:
            positive_rate = row["positive_days"] / row["known_days"] * 100 if row["known_days"] else None
            lines.append(
                f"| {row['hall_name']} | {row['event_type']} | {row['days']} | {pct(positive_rate)} | "
                f"{fmt_int(round(row['avg_total_diff']))} | {fmt_int(round(row['avg_diff']))} | {fmt_int(round(row['avg_game']))} |"
            )
    else:
        lines.append("| イベントルール未登録 | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 機種別の強そうな候補",
            "",
            "| 機種 | 出現回数 | 平均差枚 | 平均G | 平均出率 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    if machines:
        for row in machines:
            lines.append(
                f"| {row['machine_name']} | {row['appearances']} | {fmt_int(round(row['avg_diff']))} | "
                f"{fmt_int(round(row['avg_game']))} | {pct(row['payout_rate'])} |"
            )
    else:
        lines.append("| まだ詳細ページの蓄積が少ないため未判定 | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 姪浜 末尾・台番傾向",
            "",
            "| イベント | 末尾 | 台数 | プラス率 | 平均差枚 | 平均G |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    if meinohama_tails:
        for row in meinohama_tails:
            positive_rate = row["positive_units"] / row["units"] * 100 if row["units"] else None
            lines.append(
                f"| {row['event_type']} | {row['tail']} | {row['units']} | {pct(positive_rate)} | "
                f"{fmt_int(round(row['avg_diff']))} | {fmt_int(round(row['avg_game']))} |"
            )
    else:
        lines.append("| 全台データの蓄積待ち | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## AIに渡すときの見るポイント",
            "",
            "- プラス日率が高い曜日や末尾日を優先して見る",
            "- 姪浜は3の日=末尾系、6の日=メリハリ、9の日=並び・全台系として別々に見る",
            "- 平均差枚だけでなく平均G数も一緒に見る",
            "- 注目機種が繰り返し出るかを見る",
            "- 詳細ページを増やすほど、機種単位の判断が安定する",
        ]
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Create a Markdown analysis report from min-repo SQLite data.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    parser.add_argument("--out", default="reports/latest_analysis.md")
    args = parser.parse_args()
    build_report(args.db, args.out)


if __name__ == "__main__":
    main()
