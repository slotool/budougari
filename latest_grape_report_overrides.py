from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any


def combined_grape_denom(rows: list[dict[str, Any]]) -> float | None:
    total_games = 0
    total_grapes = 0.0
    for row in rows:
        games = row.get("games")
        denom = row.get("grape_denom")
        if isinstance(games, int) and games > 0 and isinstance(denom, (int, float)) and denom > 0:
            total_games += games
            total_grapes += games / denom
    if total_games <= 0 or total_grapes <= 0:
        return None
    return total_games / total_grapes


def summarize_with_grade(report, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for machine in sorted({r["machine"] for r in rows}):
        ms = [r for r in rows if r["machine"] == machine]
        calc = [r for r in ms if isinstance(r.get("grape_denom"), (int, float))]
        total_games = sum((r.get("games") or 0) for r in ms)
        total_bb = sum((r.get("bb") or 0) for r in ms)
        total_rb = sum((r.get("rb") or 0) for r in ms)
        avg_grape = combined_grape_denom(calc)
        result.append(
            {
                "machine": machine,
                "count": len(ms),
                "calc_count": len(calc),
                "avg_grape": avg_grape,
                "grade": report.grade_grape(avg_grape, report.spec_for(machine)) if avg_grape is not None else "-",
                "avg_games": round(total_games / len(ms)) if ms else None,
                "total_diff": sum((r.get("diff") or 0) for r in ms),
                "bb": total_bb,
                "rb": total_rb,
                "combined_rate": total_games / (total_bb + total_rb) if total_bb + total_rb > 0 else None,
                "bb_rate": total_games / total_bb if total_bb > 0 else None,
                "rb_rate": total_games / total_rb if total_rb > 0 else None,
            }
        )
    return result


def write_outputs_with_grade(report, results: list[dict[str, Any]]) -> None:
    Path("reports").mkdir(exist_ok=True)
    Path("exports").mkdir(exist_ok=True)

    lines: list[str] = []
    lines.append("# 最新掲載日 ジャグラーぶどう逆算")
    lines.append("")
    lines.append(f"生成日時: {datetime.now(report.JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    lines.append("")
    lines.append("前提: 最新掲載日のジャグラー各機種だけを対象に、BB/RB・差枚・G数から台番別に逆算しています。チェリー、ベル、ピエロは実測値ではなく機種別の公表確率どおり取得できた前提です。低G数や小役取りこぼしがある台は、推定ぶどうが悪めに出やすくなります。")
    lines.append("機種別まとめの推定ぶどうは、各台の分母単純平均ではなく、G数で重みを付けた合算値です。")
    lines.append("")

    csv_rows: list[dict[str, Any]] = []
    for result in results:
        latest = result["latest"]
        rows = result["rows"]
        lines.append(f"## {result['hall']}")
        lines.append("")
        lines.append(f"- 参照データ日: {latest['date'].isoformat()} ({latest['label']})")
        lines.append(f"- レポートURL: {latest['url']}")
        lines.append(f"- 対象台数: {len(rows)}")
        lines.append("")
        lines.append("### 機種別まとめ")
        lines.append("")
        lines.append("| 機種 | 推定ぶどう | 判定 | 合算確率 | BIG確率 | REG確率 | 台数 | 計算台数 | 平均G | 合計差枚 | BB/RB |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for s in summarize_with_grade(report, rows):
            lines.append(
                f"| {s['machine']} | {report.fmt_grape(s['avg_grape'])} | {s['grade']} | {report.fmt_rate(s['combined_rate'])} | {report.fmt_rate(s['bb_rate'])} | {report.fmt_rate(s['rb_rate'])} | {s['count']} | {s['calc_count']} | {report.fmt_int(s['avg_games'])} | {report.fmt_int(s['total_diff'])} | {report.fmt_int(s['bb'])}/{report.fmt_int(s['rb'])} |"
            )
        lines.append("")
        lines.append("### 台番別")
        lines.append("")
        for machine in sorted({r["machine"] for r in rows}):
            ms = sorted([r for r in rows if r["machine"] == machine], key=lambda r: r["unit"])
            lines.append(f"#### {machine}")
            lines.append("")
            lines.append("| 台番 | 推定ぶどう | 判定 | G数 | 差枚 | BB/RB | 出率 |")
            lines.append("|---:|---:|---|---:|---:|---:|---:|")
            for r in ms:
                rate = f"{r['payout_rate']:.1f}%" if isinstance(r.get("payout_rate"), (int, float)) else "-"
                lines.append(
                    f"| {r['unit']} | {report.fmt_grape(r.get('grape_denom'))} | {r.get('grade', '-')} | {report.fmt_int(r.get('games'))} | {report.fmt_int(r.get('diff'))} | {report.fmt_int(r.get('bb'))}/{report.fmt_int(r.get('rb'))} | {rate} |"
                )
                csv_rows.append(
                    {
                        "hall": result["hall"],
                        "date": latest["date"].isoformat(),
                        "machine": machine,
                        "unit": r["unit"],
                        "grape_denom": f"{r.get('grape_denom'):.4f}" if isinstance(r.get("grape_denom"), (int, float)) else "",
                        "grade": r.get("grade", ""),
                        "games": r.get("games", ""),
                        "diff": r.get("diff", ""),
                        "bb": r.get("bb", ""),
                        "rb": r.get("rb", ""),
                        "payout_rate": r.get("payout_rate", ""),
                    }
                )
            lines.append("")

    Path("reports/grape_estimates.md").write_text("\n".join(lines), encoding="utf-8")
    with Path("exports/latest_grapes.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["hall"])
        writer.writeheader()
        writer.writerows(csv_rows)
