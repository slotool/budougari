import argparse
import datetime as dt
from pathlib import Path
import sqlite3

import analyze_juggler as base
from prediction_learning import apply_learned_weights, save_prediction_run


def predict_tail_targets(rows, target_date, target_event, hall_name):
    if hall_name != "パーラーゾーン姪浜" or target_date.day % 10 != 3:
        return [], []
    event_rows = [row for row in rows if row["event_type"] == target_event and row["unit_no"] is not None]
    if not event_rows:
        return [], []

    by_date_tail = {}
    for row in event_rows:
        tail = row["unit_no"] % 10
        by_date_tail.setdefault((row["report_date"], tail), []).append(row)

    dates = sorted({row["report_date"] for row in event_rows}, reverse=True)
    tail_stats = {
        tail: {"samples": 0, "hits": 0, "diff": 0.0, "positive": 0, "big": 0, "last_hit_index": None}
        for tail in range(10)
    }

    for date_index, date_text in enumerate(dates):
        daily = []
        for tail in range(10):
            items = by_date_tail.get((date_text, tail), [])
            if not items:
                continue
            diffs = [row["avg_diff"] or 0 for row in items]
            avg_diff = sum(diffs) / len(diffs)
            positive_rate = sum(1 for value in diffs if value > 0) / len(diffs) * 100
            big_rate = sum(1 for value in diffs if value >= 1000) / len(diffs) * 100
            daily_score = avg_diff + positive_rate * 8 + big_rate * 10
            daily.append((tail, daily_score))

            stats = tail_stats[tail]
            stats["samples"] += len(items)
            stats["diff"] += sum(diffs)
            stats["positive"] += sum(1 for value in diffs if value > 0)
            stats["big"] += sum(1 for value in diffs if value >= 1000)

        winners = {tail for tail, _ in sorted(daily, key=lambda item: item[1], reverse=True)[:2]}
        for tail in winners:
            tail_stats[tail]["hits"] += 1
            if tail_stats[tail]["last_hit_index"] is None:
                tail_stats[tail]["last_hit_index"] = date_index

    predictions = []
    for tail, stats in tail_stats.items():
        if stats["samples"] == 0:
            continue
        avg_diff = stats["diff"] / stats["samples"]
        positive_rate = stats["positive"] / stats["samples"] * 100
        big_rate = stats["big"] / stats["samples"] * 100
        last_hit_index = stats["last_hit_index"]
        miss_bonus = 180 if last_hit_index is None else min(last_hit_index, 5) * 55
        recent_penalty = 170 if last_hit_index == 0 else 80 if last_hit_index == 1 else 0
        hit_rate = stats["hits"] / len(dates) * 100 if dates else 0
        score = avg_diff * 0.25 + positive_rate * 4 + big_rate * 5 + hit_rate * 3 + miss_bonus - recent_penalty
        predictions.append(
            {
                "tail": tail,
                "score": score,
                "samples": stats["samples"],
                "hit_count": stats["hits"],
                "hit_rate": hit_rate,
                "avg_diff": avg_diff,
                "positive_rate": positive_rate,
                "last_hit_ago": last_hit_index,
            }
        )

    predictions = sorted(predictions, key=lambda row: row["score"], reverse=True)
    notes = []
    for row in predictions[:5]:
        if row["last_hit_ago"] is None:
            recency = "直近未確認"
        elif row["last_hit_ago"] == 0:
            recency = "前回当たり"
        else:
            recency = f"{row['last_hit_ago']}回前"
        notes.append(
            f"末尾{row['tail']}: score {base.fmt_int(row['score'])}, "
            f"当たり{row['hit_count']}回, 平均{base.fmt_int(row['avg_diff'])}, {recency}"
        )
    return predictions[:2], notes


def apply_tail_prediction_boost(summaries, tail_predictions):
    boost_by_tail = {}
    for idx, row in enumerate(tail_predictions, 1):
        boost_by_tail[row["tail"]] = 520 if idx == 1 else 360
    if not boost_by_tail:
        return summaries
    for row in summaries:
        tail = row["unit_no"] % 10
        if tail in boost_by_tail:
            row["score"] += boost_by_tail[tail]
            row["tail_boost"] = boost_by_tail[tail]
            row["tail_pick_rank"] = 1 if boost_by_tail[tail] == 520 else 2
    return sorted(summaries, key=lambda row: row["score"], reverse=True)


def write_report(db_path, hall_name, output_path, target_date=None, recommendations_path="weekly_recommendations.json", config_path="config.json"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = base.fetch_rows(conn, hall_name)
    config = base.load_config(config_path)
    rules = base.hall_config(hall_name, config)
    if target_date is None:
        target_date, target_event = base.next_juggler_event()
    else:
        target_date = dt.date.fromisoformat(target_date)
        target_event = base.configured_event_for_date(target_date.isoformat(), rules)

    summaries, latest_date, current_unit_count = base.summarize(rows, target_event)
    recommended_machines = base.load_recommended_machines(recommendations_path, hall_name, target_date.isoformat())
    summaries = base.apply_recommendation_boost(summaries, recommended_machines)
    summaries, rule_notes = base.apply_hall_rule_boost(summaries, target_date, rules)
    tail_predictions, tail_notes = predict_tail_targets(rows, target_date, target_event, hall_name)
    summaries = apply_tail_prediction_boost(summaries, tail_predictions)
    summaries, learned_notes = apply_learned_weights(conn, hall_name, summaries, target_date.isoformat(), target_event)
    tail_text = " / ".join(f"末尾{row['tail']}" for row in tail_predictions) if tail_predictions else "-"

    lines = [
        "# ジャグラー系 台番分析",
        "",
        f"対象店舗: {hall_name}",
        f"狙い日: {target_date.isoformat()} ({target_event})",
        f"参照データ日: {latest_date or '-'}",
        f"現在存在するジャグラー台番数: {current_unit_count}",
        f"ジャグラー系レコード数: {len(rows)}",
        f"今週のおすすめ機種: {', '.join(recommended_machines) if recommended_machines else '-'}",
        f"店舗ルール補正: {' / '.join(rule_notes) if rule_notes else '-'}",
        f"3の日 末尾予想: {tail_text}",
        f"学習補正: {' / '.join(learned_notes) if learned_notes else 'まだ答え合わせデータ不足'}",
        "",
    ]

    if tail_predictions:
        lines.extend(
            [
                "## 3の日 末尾2本予想",
                "",
                "| 順位 | 末尾 | スコア | 過去3の日当たり回数 | 当たり率 | 平均差枚 | プラス率 | 最終当たり |",
                "|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for idx, row in enumerate(tail_predictions, 1):
            if row["last_hit_ago"] is None:
                recency = "直近未確認"
            elif row["last_hit_ago"] == 0:
                recency = "前回当たり"
            else:
                recency = f"{row['last_hit_ago']}回前"
            lines.append(
                f"| {idx} | {row['tail']} | {base.fmt_int(row['score'])} | {row['hit_count']} | "
                f"{base.pct(row['hit_rate'])} | {base.fmt_int(row['avg_diff'])} | {base.pct(row['positive_rate'])} | {recency} |"
            )
        lines.extend(["", "理由: " + " / ".join(tail_notes), ""])

    lines.extend(
        [
            "## 次に入りやすそうな台番候補",
            "",
            "| 順位 | 台番 | 機種 | 角 | おすすめ | 末尾 | ルール補正 | 学習補正 | スコア | 対象イベント平均差枚 | 直近平均差枚 | 全体プラス率 | 最新差枚 | 最新G |",
            "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for idx, row in enumerate(summaries[:15], 1):
        rule_boost = (row.get("weekday_boost") or 0) + (row.get("corner_boost") or 0)
        lines.append(
            f"| {idx} | {row['unit_no']} | {row['current_machine']} | {'○' if row.get('is_corner') else ''} | "
            f"{'○' if row['recommended'] else ''} | {'○' if row.get('tail_boost') else ''} | {base.fmt_int(rule_boost)} | "
            f"{base.fmt_int(row.get('learned_boost'))} | {base.fmt_int(row['score'])} | {base.fmt_int(row['event_avg'])} | "
            f"{base.fmt_int(row['recent_avg'])} | {base.pct(row['positive_rate'])} | {base.fmt_diff(row['latest_diff'])} | {base.fmt_int(row['latest_game'])} |"
        )

    lines.extend(["", "## 機種別 狙い台", ""])
    for machine_name, machine_rows in base.machine_groups(summaries).items():
        lines.extend(
            [
                f"### {machine_name}",
                "",
                "| 順位 | 台番 | 角 | おすすめ | 末尾 | スコア | 直近平均差枚 | 最新差枚 | 最新G |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for idx, row in enumerate(machine_rows[:8], 1):
            lines.append(
                f"| {idx} | {row['unit_no']} | {'○' if row.get('is_corner') else ''} | {'○' if row['recommended'] else ''} | "
                f"{'○' if row.get('tail_boost') else ''} | {base.fmt_int(row['score'])} | {base.fmt_int(row['recent_avg'])} | "
                f"{base.fmt_diff(row['latest_diff'])} | {base.fmt_int(row['latest_game'])} |"
            )
        lines.append("")

    lines.extend(
        [
            "",
            "## 学習の扱い",
            "",
            "- 狙い台として出した台番と理由タグをDBへ保存します。",
            "- 後日その日の結果が入ったら、差枚+500枚以上を当たりとして答え合わせします。",
            "- 当たった理由タグは加点、外した理由タグは減点され、次回以降のスコアへ反映されます。",
            "- 姪浜の3の日は末尾2本予想も理由タグとして保存します。",
        ]
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    save_prediction_run(conn, hall_name, target_date.isoformat(), target_event, latest_date, summaries)
    conn.close()
    print(f"wrote {output}")


def main():
    parser = argparse.ArgumentParser(description="Build learned Juggler target report.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    parser.add_argument("--hall", default="パーラーゾーン姪浜")
    parser.add_argument("--out", default="reports/juggler_today.md")
    parser.add_argument("--date")
    parser.add_argument("--recommendations", default="weekly_recommendations.json")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    write_report(args.db, args.hall, args.out, args.date, args.recommendations, args.config)


if __name__ == "__main__":
    main()
