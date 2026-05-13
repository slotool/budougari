import argparse
import datetime as dt
from pathlib import Path
import sqlite3


REPLAY_DENOM = 7.298

MODEL_SPECS = [
    {"keys": ["マイジャグラーV", "マイジャグラーⅤ"], "bonus": (240, 96), "grapes": [5.910, 5.870, 5.830, 5.800, 5.760, 5.670], "cherry": 34.657, "bell": 1024.0, "pierrot": 1024.0},
    {"keys": ["Sアイムジャグラー", "アイムジャグラー", "ネオアイムジャグラー"], "bonus": (252, 96), "grapes": [6.024, 6.024, 6.024, 6.024, 6.024, 5.848], "cherry": 35.617, "bell": 1092.267, "pierrot": 1092.267},
    {"keys": ["ゴーゴージャグラー３", "ゴーゴージャグラー3"], "bonus": (240, 96), "grapes": [6.2499, 6.2002, 6.1502, 6.0698, 5.9998, 5.9201], "cherry": 33.20, "bell": 1092.267, "pierrot": 1092.267},
    {"keys": ["ファンキージャグラー"], "bonus": (240, 96), "grapes": [5.9400, 5.9298, 5.8798, 5.8301, 5.8000, 5.7700], "cherry": 35.62, "bell": 1092.27, "pierrot": 1092.27},
    {"keys": ["ハッピージャグラー"], "bonus": (240, 96), "grapes": [6.04, 6.01, 5.98, 5.86, 5.84, 5.82], "cherry": 56.55, "bell": 655.36, "pierrot": 655.36, "cherry_payout": 4},
    {"keys": ["ジャグラーガールズ"], "bonus": (252, 96), "grapes": [6.01, 6.01, 6.01, 6.01, 5.92, 5.89], "cherry": 33.301, "bell": 1092.267, "pierrot": 1092.267},
    {"keys": ["ミスタージャグラー"], "bonus": (240, 96), "grapes": [6.24212, 6.18381, 6.13690, 6.09807, 6.05973, 6.01689], "cherry": 37.236, "bell": 655.36, "pierrot": 2173.04},
    {"keys": ["ウルトラミラクルジャグラー"], "bonus": (240, 96), "grapes": [5.940, 5.938, 5.936, 5.934, 5.933, 5.929], "cherry": 34.86, "bell": 1024.0, "pierrot": 1024.0},
]


def fmt_int(value):
    if value is None:
        return "-"
    return f"{round(value):,}"


def fmt_float(value, digits=2):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def spec_for(machine_name):
    for spec in MODEL_SPECS:
        if any(key in machine_name for key in spec["keys"]):
            return spec
    return {"keys": ["汎用"], "bonus": (240, 96), "grapes": [6.20, 6.10, 6.00, 5.90, 5.85, 5.80], "cherry": 35.62, "bell": 1092.27, "pierrot": 1092.27}


def grade(denom, spec):
    if denom is None:
        return "-"
    grapes = spec["grapes"]
    closest = min(range(6), key=lambda idx: abs(denom - grapes[idx])) + 1
    return f"設定{closest}近辺"


def available_report_date(conn, target_date, hall_name):
    row = conn.execute(
        """
        select max(mr.report_date)
          from machine_reports mr
          join daily_reports dr
            on dr.hall_key = mr.hall_key
           and dr.report_date = mr.report_date
         where mr.category = 'unit'
           and mr.report_date <= ?
           and instr(mr.machine_name, 'ジャグラー') > 0
           and dr.hall_name = ?
        """,
        (target_date.isoformat(), hall_name),
    ).fetchone()
    if row and row[0]:
        report_date = dt.date.fromisoformat(row[0])
        return report_date, report_date != target_date
    return target_date, True


def load_unit_rows(conn, report_date, hall_name):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        select dr.hall_name, mr.machine_name, mr.unit_no, mr.avg_game, mr.avg_diff, mr.payout_rate,
               ub.bb_count, ub.rb_count
          from machine_reports mr
          join daily_reports dr
            on dr.hall_key = mr.hall_key
           and dr.report_date = mr.report_date
          left join unit_bonus_reports ub
            on ub.report_id = mr.report_id
           and ub.unit_no = mr.unit_no
         where mr.category = 'unit'
           and mr.report_date = ?
           and instr(mr.machine_name, 'ジャグラー') > 0
           and dr.hall_name = ?
         order by dr.hall_name, mr.machine_name, mr.unit_no
        """,
        (report_date.isoformat(), hall_name),
    ).fetchall()


def estimate_from_totals(machine_name, games, diff, bb, rb, skill="cherry"):
    if not games or diff is None or bb is None or rb is None:
        return None, None
    spec = spec_for(machine_name)
    big_payout, reg_payout = spec["bonus"]
    replay_count = games / REPLAY_DENOM
    cherry_payout = spec.get("cherry_payout", 2)
    known_payout = bb * big_payout + rb * reg_payout
    known_payout += games / spec["cherry"] * cherry_payout
    if skill == "perfect":
        known_payout += games / spec["bell"] * 14
        known_payout += games / spec["pierrot"] * 10
    input_medals = (games - replay_count) * 3
    grape_count = (diff + input_medals - known_payout) / 8
    if grape_count <= 0:
        return None, spec
    return games / grape_count, spec


def effective_diff(row):
    if row["avg_diff"] is not None:
        return row["avg_diff"], "actual"
    if row["payout_rate"] is not None and row["avg_game"]:
        return row["avg_game"] * 3 * (row["payout_rate"] / 100 - 1), "payout"
    return None, "missing"


def summarize_machine(rows, skill):
    by_machine = {}
    for row in rows:
        by_machine.setdefault(row["machine_name"], []).append(row)

    summaries = []
    for machine_name, machine_rows in sorted(by_machine.items()):
        usable = []
        actual_diff_units = 0
        payout_diff_units = 0
        for row in machine_rows:
            diff_value, diff_source = effective_diff(row)
            if row["avg_game"] and diff_value is not None and row["bb_count"] is not None and row["rb_count"] is not None:
                item = dict(row)
                item["effective_diff"] = diff_value
                usable.append(item)
                if diff_source == "actual":
                    actual_diff_units += 1
                elif diff_source == "payout":
                    payout_diff_units += 1
        games = sum(row["avg_game"] for row in usable)
        diff = sum(row["effective_diff"] for row in usable) if usable else None
        bb = sum(row["bb_count"] for row in usable) if usable else None
        rb = sum(row["rb_count"] for row in usable) if usable else None
        denom, spec = estimate_from_totals(machine_name, games, diff, bb, rb, skill)
        summaries.append(
            {
                "machine_name": machine_name,
                "units": len(machine_rows),
                "usable_units": len(usable),
                "avg_game": sum((row["avg_game"] or 0) for row in machine_rows) / len(machine_rows),
                "actual_diff_units": actual_diff_units,
                "payout_diff_units": payout_diff_units,
                "total_games": games if usable else None,
                "total_diff": diff,
                "bb": bb,
                "rb": rb,
                "denom": denom,
                "grade": grade(denom, spec),
            }
        )
    return summaries


def unit_sort_key(row):
    unit_no = row["unit_no"]
    try:
        return (int(unit_no), str(unit_no))
    except (TypeError, ValueError):
        return (999999, str(unit_no or ""))


def summarize_units(rows, skill):
    units = []
    for row in sorted(rows, key=unit_sort_key):
        diff_value, diff_source = effective_diff(row)
        denom, spec = estimate_from_totals(
            row["machine_name"], row["avg_game"], diff_value, row["bb_count"], row["rb_count"], skill
        )
        units.append(
            {
                "machine_name": row["machine_name"],
                "unit_no": row["unit_no"],
                "avg_game": row["avg_game"],
                "diff": diff_value,
                "diff_source": diff_source,
                "bb": row["bb_count"],
                "rb": row["rb_count"],
                "denom": denom,
                "grade": grade(denom, spec) if spec else "-",
            }
        )
    return units


def summarize_units_by_machine(rows, skill):
    grouped = {}
    for row in summarize_units(rows, skill):
        grouped.setdefault(row["machine_name"], []).append(row)
    return sorted(grouped.items(), key=lambda item: item[0])


def diff_source_label(source):
    return {"actual": "実差枚", "payout": "出率補完", "missing": "欠損"}.get(source, source)


def write_report(db_path, target_date, output_path, skill):
    conn = sqlite3.connect(db_path)
    halls = [row[0] for row in conn.execute("select distinct hall_name from daily_reports order by hall_name").fetchall()]

    lines = [
        "# 最新掲載ジャグラー 機種別ぶどう推定",
        "",
        f"実行対象日: {target_date.isoformat()}",
        f"目押し前提: {'完全技術介入' if skill == 'perfect' else 'チェリー狙い'}",
        "",
        "注意: BB/RBが取れている台だけで逆算します。差枚が欠損している台は、出率とG数から差枚を補完して計算します。",
        "計算式: ぶどう回数 = (差枚 + (総G - リプレイ回数)×3 - BIG払出 - REG払出 - チェリー等払出) / 8。",
        "リプレイ確率・チェリー確率・ベル/ピエロ確率は、けんのスロットシミュレーションの逆算ツール掲載値を元にしています。",
        "",
    ]

    any_rows = False
    for hall_name in halls:
        report_date, fallback = available_report_date(conn, target_date, hall_name)
        rows = load_unit_rows(conn, report_date, hall_name)
        if not rows:
            continue
        any_rows = True
        lines.extend(
            [
                f"## {hall_name}",
                "",
                f"参照データ日: {report_date.isoformat()}" + ("（対象日以前の最新取得日を使用）" if fallback else ""),
                "",
                "| 機種 | 推定ぶどう | 判定 | 台数 | 計算台数 | 平均G | 計算差枚 | BB/RB | 実差枚台数 | 出率補完台数 | 計算G |",
                "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in summarize_machine(rows, skill):
            bonus_text = f"BB {fmt_int(row['bb'])} / RB {fmt_int(row['rb'])}" if row["bb"] is not None else "未取得"
            grape_text = f"1/{fmt_float(row['denom'])}" if row["denom"] is not None else "計算不可"
            lines.append(
                f"| {row['machine_name']} | {grape_text} | {row['grade']} | {row['units']} | {row['usable_units']} | "
                f"{fmt_int(row['avg_game'])} | {fmt_int(row['total_diff'])} | {bonus_text} | "
                f"{row['actual_diff_units']} | {row['payout_diff_units']} | {fmt_int(row['total_games'])} |"
            )
        lines.append("")
        lines.extend(
            [
                "### 台番別ぶどう推定",
                "",
                "| 台番 | 推定ぶどう | 判定 | 機種 | G数 | 差枚 | BB/RB | 差枚元 |",
                "|---:|---:|---|---|---:|---:|---:|---|",
            ]
        )
        for machine_name, unit_rows in summarize_units_by_machine(rows, skill):
            lines.extend(["", f"#### {machine_name}", ""])
            for row in unit_rows:
                bonus_text = f"BB {fmt_int(row['bb'])} / RB {fmt_int(row['rb'])}" if row["bb"] is not None else "未取得"
                grape_text = f"1/{fmt_float(row['denom'])}" if row["denom"] is not None else "計算不可"
                lines.append(
                    f"| {row['unit_no']} | {grape_text} | {row['grade']} | {row['machine_name']} | "
                    f"{fmt_int(row['avg_game'])} | {fmt_int(row['diff'])} | {bonus_text} | {diff_source_label(row['diff_source'])} |"
                )
        lines.append("")

    if not any_rows:
        lines.append("対象データがありません。")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {output}")


def main():
    parser = argparse.ArgumentParser(description="Estimate Juggler grape probability by machine from latest available data.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--out", default="reports/grape_estimates.md")
    parser.add_argument("--skill", choices=["cherry", "perfect"], default="cherry")
    args = parser.parse_args()
    write_report(args.db, dt.date.fromisoformat(args.date), args.out, args.skill)


if __name__ == "__main__":
    main()
