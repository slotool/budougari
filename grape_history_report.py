from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import latest_grape_report_impl as report


JST = report.JST
HISTORY_CSV = Path("data/grape_history.csv")
REPORT_MD = Path("reports/grape_history_analysis.md")
REPORT_HTML = Path("site/grape_history_analysis.html")


def setting_grade(denom: float, spec: report.ModelSpec) -> str:
    pairs = [
        (1, spec.grape_denoms[0]),
        (2, spec.grape_denoms[1]),
        (3, spec.grape_denoms[2]),
        (4, spec.grape_denoms[3]),
        (5, spec.grape_denoms[4]),
        (6, spec.grape_denoms[5]),
    ]
    nearest_setting, _ = min(pairs, key=lambda item: abs(denom - item[1]))
    if denom <= spec.grape_denoms[5]:
        return "設定6以上目安"
    if denom > spec.grape_denoms[0]:
        return "設定1未満目安"
    return f"設定{nearest_setting}近辺"


def date_from_label(label: str, today: date) -> date | None:
    match = re.search(r"(?:(20\d{2})/)?(\d{1,2})/(\d{1,2})\((.)\)", label)
    if not match:
        return None
    year_text, month_text, day_text, weekday = match.groups()
    years = [int(year_text)] if year_text else range(today.year + 1, today.year - 4, -1)
    for year in years:
        try:
            candidate = date(year, int(month_text), int(day_text))
        except ValueError:
            continue
        if candidate > today:
            continue
        if weekday in report.WEEKDAY_INDEX and candidate.weekday() != report.WEEKDAY_INDEX[weekday]:
            continue
        return candidate
    return None


def candidate(label: str, href: str | None, tag_url: str, today: date) -> dict[str, object] | None:
    if not href:
        return None
    report_url = urljoin(tag_url, href)
    report_id = urlparse(report_url).path.strip("/").split("/")[0]
    if not report_id.isdigit():
        return None
    rep_date = date_from_label(label, today)
    if not rep_date:
        return None
    return {"date": rep_date, "url": report_url, "id": report_id, "label": label}


def fetch_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
    with urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def latest_from_wp_api(tag_url: str, today: date) -> dict[str, object] | None:
    slug = urlparse(tag_url).path.strip("/").split("/")[-1]
    if not slug:
        return None
    tags = fetch_json(f"{report.BASE_URL}/wp-json/wp/v2/tags?slug={slug}")
    if not isinstance(tags, list) or not tags or not tags[0].get("id"):
        return None
    posts = fetch_json(
        f"{report.BASE_URL}/wp-json/wp/v2/posts?tags={tags[0]['id']}&per_page=10&_fields=id,link,title,date"
    )
    if not isinstance(posts, list):
        return None
    for post in posts:
        title = html.unescape(str(post.get("title", {}).get("rendered", "")))
        found = candidate(title, str(post.get("link", "")), tag_url, today)
        if found:
            return found
    return None


def find_latest_report_resilient(source: str, tag_url: str, today: date) -> dict[str, object]:
    try:
        return original_find_latest_report(source, tag_url, today)
    except RuntimeError:
        pass

    for table in report.parse_tables(source):
        if not table:
            continue
        header = [report.split_link(c)[0] for c in table[0]]
        if not header or header[0] != "日付":
            continue
        for row in table[1:]:
            label, href = report.split_link(row[0])
            found = candidate(label, href, tag_url, today)
            if found:
                return found

    found = latest_from_wp_api(tag_url, today)
    if found:
        return found
    raise RuntimeError("最新掲載日の行が見つかりませんでした")


def fmt_int(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"


def fmt_float(value: object, digits: int = 2) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and math.isfinite(value) else "-"


def fmt_grape(value: object) -> str:
    return f"1/{value:.2f}" if isinstance(value, (int, float)) and math.isfinite(value) else "-"


def to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value)))


def to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value))


def load_history() -> list[dict[str, str]]:
    if not HISTORY_CSV.exists():
        return []
    with HISTORY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def history_key(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (str(row["hall"]), str(row["date"]), str(row["machine"]), str(row["unit"]))


def append_history(results: list[dict[str, object]]) -> list[dict[str, str]]:
    HISTORY_CSV.parent.mkdir(exist_ok=True)
    existing = load_history()
    rows_by_key: dict[tuple[str, str, str, str], dict[str, object]] = {history_key(r): dict(r) for r in existing}
    collected_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S%z")

    for result in results:
        latest = result["latest"]
        for row in result["rows"]:
            if not isinstance(row.get("grape_denom"), (int, float)):
                continue
            out = {
                "hall": result["hall"],
                "date": latest["date"].isoformat(),
                "label": latest["label"],
                "report_url": latest["url"],
                "machine": row["machine"],
                "unit": row["unit"],
                "grape_denom": f"{row['grape_denom']:.4f}",
                "grade": row.get("grade", ""),
                "games": row.get("games", ""),
                "diff": row.get("diff", ""),
                "bb": row.get("bb", ""),
                "rb": row.get("rb", ""),
                "payout_rate": row.get("payout_rate", ""),
                "collected_at": collected_at,
            }
            rows_by_key[history_key(out)] = out

    fields = [
        "hall",
        "date",
        "label",
        "report_url",
        "machine",
        "unit",
        "grape_denom",
        "grade",
        "games",
        "diff",
        "bb",
        "rb",
        "payout_rate",
        "collected_at",
    ]
    sorted_rows = sorted(rows_by_key.values(), key=lambda r: (str(r["hall"]), str(r["date"]), str(r["machine"]), int(r["unit"])))
    with HISTORY_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted_rows)
    return [{k: str(v) for k, v in row.items()} for row in sorted_rows]


def next_same_unit(row: dict[str, str], rows: list[dict[str, str]]) -> dict[str, str] | None:
    base_date = date.fromisoformat(row["date"])
    candidates = [
        other
        for other in rows
        if other["hall"] == row["hall"]
        and other["machine"] == row["machine"]
        and other["unit"] == row["unit"]
        and date.fromisoformat(other["date"]) > base_date
    ]
    return min(candidates, key=lambda r: r["date"], default=None)


def is_estimated_six(row: dict[str, str]) -> bool:
    return row.get("grade") == "設定6以上目安"


def analyze(rows: list[dict[str, str]], min_games: int, low_output_diff_max: int) -> dict[str, object]:
    targets = []
    followed = []
    for row in rows:
        games = to_int(row.get("games"))
        diff = to_int(row.get("diff"))
        if games is None or diff is None:
            continue
        if games >= min_games and diff <= low_output_diff_max and is_estimated_six(row):
            nxt = next_same_unit(row, rows)
            item = {"base": row, "next": nxt}
            targets.append(item)
            if nxt:
                followed.append(item)

    next_positive = [x for x in followed if (to_int(x["next"].get("diff")) or 0) > 0]
    next_est_six = [x for x in followed if is_estimated_six(x["next"])]
    next_diffs = [to_int(x["next"].get("diff")) for x in followed if to_int(x["next"].get("diff")) is not None]
    return {
        "targets": targets,
        "followed": followed,
        "next_positive_count": len(next_positive),
        "next_est_six_count": len(next_est_six),
        "avg_next_diff": round(sum(next_diffs) / len(next_diffs)) if next_diffs else None,
    }


def write_report(rows: list[dict[str, str]], analysis: dict[str, object], min_games: int, low_output_diff_max: int) -> None:
    REPORT_MD.parent.mkdir(exist_ok=True)
    REPORT_HTML.parent.mkdir(exist_ok=True)
    targets = analysis["targets"]
    followed = analysis["followed"]
    lines: list[str] = [
        "# 推定ぶどう履歴 翌掲載日分析",
        "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
        "",
        f"判定条件: G数 {min_games:,}G以上、推定ぶどう判定が「設定6以上目安」、差枚 {low_output_diff_max:+,}枚以下を「推定6なのに伸び不足」として追跡。",
        "店休日を考慮し、翌カレンダー日ではなく同じ店舗・同じ機種・同じ台番の「次に蓄積された掲載日」と比較します。",
        "",
        "## 集計",
        "",
        f"- 履歴行数: {len(rows):,}",
        f"- 追跡対象: {len(targets):,}",
        f"- 翌掲載日まで確認済み: {len(followed):,}",
    ]
    if followed:
        lines.extend(
            [
                f"- 翌掲載日プラス率: {analysis['next_positive_count']}/{len(followed)} ({analysis['next_positive_count'] / len(followed) * 100:.1f}%)",
                f"- 翌掲載日も推定6率: {analysis['next_est_six_count']}/{len(followed)} ({analysis['next_est_six_count'] / len(followed) * 100:.1f}%)",
                f"- 翌掲載日平均差枚: {fmt_int(analysis['avg_next_diff'])}",
            ]
        )
    lines.extend(["", "## 追跡対象と翌掲載日", ""])
    lines.append("| 店舗 | 基準日 | 機種 | 台番 | 基準G | 基準差枚 | 基準ぶどう | 翌掲載日 | 翌G | 翌差枚 | 翌ぶどう | 翌判定 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for item in targets:
        base = item["base"]
        nxt = item["next"]
        lines.append(
            "| {hall} | {date} | {machine} | {unit} | {games} | {diff} | {grape} | {next_date} | {next_games} | {next_diff} | {next_grape} | {next_grade} |".format(
                hall=base["hall"],
                date=base["date"],
                machine=base["machine"],
                unit=base["unit"],
                games=fmt_int(to_int(base.get("games"))),
                diff=fmt_int(to_int(base.get("diff"))),
                grape=fmt_grape(to_float(base.get("grape_denom"))),
                next_date=nxt["date"] if nxt else "-",
                next_games=fmt_int(to_int(nxt.get("games"))) if nxt else "-",
                next_diff=fmt_int(to_int(nxt.get("diff"))) if nxt else "-",
                next_grape=fmt_grape(to_float(nxt.get("grape_denom"))) if nxt else "-",
                next_grade=nxt.get("grade", "-") if nxt else "-",
            )
        )
    if not targets:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | - |")

    markdown = "\n".join(lines)
    REPORT_MD.write_text(markdown, encoding="utf-8")
    REPORT_HTML.write_text(render_html(markdown), encoding="utf-8")


def render_html(markdown: str) -> str:
    body = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{html.escape(lines[i][2:])}</li>")
                i += 1
            body.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            body.append(render_table(table_lines))
            continue
        else:
            body.append(f"<p>{html.escape(line)}</p>")
        i += 1
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>推定ぶどう履歴 翌掲載日分析</title>
  <style>
    body {{ margin: 0; background: #f7f7f5; color: #1f2933; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.65; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 18px 10px 48px; }}
    h1 {{ font-size: 23px; margin: 0 0 14px; }}
    h2 {{ margin: 28px 0 10px; padding-top: 12px; border-top: 3px solid #b42318; font-size: 20px; }}
    p, li {{ font-size: 14px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #d9dee5; background: #fff; }}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; font-size: 12px; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid #d9dee5; white-space: nowrap; text-align: right; }}
    th {{ background: #eef4ff; }}
    th:first-child, td:first-child {{ position: sticky; left: 0; background: #fff; text-align: left; font-weight: 700; box-shadow: 1px 0 0 #d9dee5; }}
    th:first-child {{ background: #eef4ff; }}
    td:nth-child(7), td:nth-child(11) {{ color: #b42318; font-weight: 800; }}
  </style>
</head>
<body><main>
{chr(10).join(body)}
</main></body></html>
"""


def render_table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    header = rows[0]
    body = [row for row in rows[2:] if any(cell.strip("-: ") for cell in row)]
    ths = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
    trs = ["<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in body]
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--delay", type=float, default=None)
    parser.add_argument("--min-games", type=int, default=2000)
    parser.add_argument("--low-output-diff-max", type=int, default=500)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    delay = args.delay if args.delay is not None else float(config.get("delay_seconds", 5))

    client = report.MinRepoClient(delay_seconds=delay)
    today = datetime.now(JST).date()
    results = [report.collect_hall(client, hall, today) for hall in config["halls"]]
    history = append_history(results)
    analysis = analyze(history, args.min_games, args.low_output_diff_max)
    write_report(history, analysis, args.min_games, args.low_output_diff_max)


original_find_latest_report = report.find_latest_report
report.find_latest_report = find_latest_report_resilient
report.grade_grape = setting_grade


if __name__ == "__main__":
    main()
