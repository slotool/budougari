from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

import grape_formula
import latest_grape_report_impl as report


JST = report.JST
HISTORY_CSV = Path("data/grape_history.csv")
REPORT_MD = Path("reports/grape_history_analysis.md")
REPORT_HTML = Path("site/grape_history_analysis.html")


def setting_grade(denom: float, spec: report.ModelSpec) -> str:
    return grape_formula.setting_grade(denom, spec)


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
    posts = fetch_json(f"{report.BASE_URL}/wp-json/wp/v2/posts?tags={tags[0]['id']}&per_page=10&_fields=id,link,title,date")
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


def list_reports_from_tag(client: report.MinRepoClient, hall: dict[str, str], today: date, days: int) -> list[dict[str, object]]:
    source = client.fetch(hall["tag_url"])
    since = today - timedelta(days=days)
    found_by_id: dict[str, dict[str, object]] = {}
    for table in report.parse_tables(source):
        if not table:
            continue
        header = [report.split_link(c)[0] for c in table[0]]
        if not header or header[0] != "日付":
            continue
        for row in table[1:]:
            if not row:
                continue
            label, href = report.split_link(row[0])
            found = candidate(label, href, hall["tag_url"], today)
            if not found:
                continue
            if since <= found["date"] <= today:
                found_by_id[str(found["id"])] = found
    return sorted(found_by_id.values(), key=lambda item: item["date"])


def collect_hall_report(client: report.MinRepoClient, hall: dict[str, str], latest: dict[str, object]) -> dict[str, object]:
    all_url = f"{str(latest['url']).rstrip('/')}/?kishu=all&sort=num"
    all_rows = report.parse_all_units(client.fetch(all_url))
    by_key: dict[tuple[str, int], dict[str, object]] = {(r["machine"], r["unit"]): r for r in all_rows}
    for machine in sorted({r["machine"] for r in all_rows}):
        machine_url = f"{report.BASE_URL}/{latest['id']}/?kishu={quote(machine)}"
        for row in report.parse_machine_units(client.fetch(machine_url), machine):
            key = (row["machine"], row["unit"])
            merged = by_key.get(key, {"machine": row["machine"], "unit": row["unit"]})
            merged.update({k: v for k, v in row.items() if v is not None})
            by_key[key] = merged

    rows = []
    for row in by_key.values():
        row.update(grape_formula.estimate_grape_by_play_levels(row))
        rows.append(row)
    rows.sort(key=lambda r: (r["machine"], r["unit"]))
    return {"hall": hall["name"], "latest": latest, "rows": rows}


def fmt_int(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"


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
    rows_by_key: dict[tuple[str, str, str, str], dict[str, object]] = {history_key(r): dict(r) for r in load_history()}
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

    fields = ["hall", "date", "label", "report_url", "machine", "unit", "grape_denom", "grade", "games", "diff", "bb", "rb", "payout_rate", "collected_at"]
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
        if other["hall"] == row["hall"] and other["unit"] == row["unit"] and date.fromisoformat(other["date"]) > base_date
    ]
    return min(candidates, key=lambda r: r["date"], default=None)


def is_estimated_six(row: dict[str, str]) -> bool:
    return row.get("grade") == "設定6以上目安"


def diff_bucket(diff: int) -> str:
    if diff <= -1000:
        return "-1000枚以下"
    if diff < 0:
        return "-999～-1枚"
    if diff <= 499:
        return "0～+499枚"
    if diff <= 999:
        return "+500～+999枚"
    return "+1000枚以上"


def games_bucket(games: int) -> str:
    if games < 1000:
        return "0～999G"
    if games < 2000:
        return "1000～1999G"
    if games < 4000:
        return "2000～3999G"
    if games < 6000:
        return "4000～5999G"
    return "6000G以上"


def summarize_items(items: list[dict[str, dict[str, str] | None]]) -> dict[str, object]:
    followed = [item for item in items if item["next"]]
    next_positive = [item for item in followed if (to_int(item["next"].get("diff")) or 0) > 0]
    next_est_six = [item for item in followed if is_estimated_six(item["next"])]
    same_machine = [item for item in followed if item["base"]["machine"] == item["next"]["machine"]]
    next_diffs = [to_int(item["next"].get("diff")) for item in followed if to_int(item["next"].get("diff")) is not None]
    return {
        "targets": len(items),
        "followed": len(followed),
        "missing": len(items) - len(followed),
        "next_positive_count": len(next_positive),
        "next_est_six_count": len(next_est_six),
        "same_machine_count": len(same_machine),
        "avg_next_diff": round(sum(next_diffs) / len(next_diffs)) if next_diffs else None,
    }


def analyze(rows: list[dict[str, str]], min_games: int, low_output_diff_max: int) -> dict[str, object]:
    targets = []
    for row in rows:
        if is_estimated_six(row):
            targets.append({"base": row, "next": next_same_unit(row, rows)})

    bucket_order = ["-1000枚以下", "-999～-1枚", "0～+499枚", "+500～+999枚", "+1000枚以上", "差枚不明"]
    games_bucket_order = ["0～999G", "1000～1999G", "2000～3999G", "4000～5999G", "6000G以上", "G数不明"]
    by_bucket = {bucket: [] for bucket in bucket_order}
    by_games_bucket = {bucket: [] for bucket in games_bucket_order}
    by_hall: dict[str, list[dict[str, dict[str, str] | None]]] = {}
    by_machine: dict[str, list[dict[str, dict[str, str] | None]]] = {}

    for item in targets:
        base = item["base"]
        diff = to_int(base.get("diff"))
        games = to_int(base.get("games"))
        by_bucket[diff_bucket(diff) if diff is not None else "差枚不明"].append(item)
        by_games_bucket[games_bucket(games) if games is not None else "G数不明"].append(item)
        by_hall.setdefault(base["hall"], []).append(item)
        by_machine.setdefault(base["machine"], []).append(item)

    return {
        "targets": targets,
        "summary": summarize_items(targets),
        "bucket_summary": [(bucket, summarize_items(items)) for bucket, items in by_bucket.items() if items],
        "games_bucket_summary": [(bucket, summarize_items(items)) for bucket, items in by_games_bucket.items() if items],
        "hall_summary": sorted([(name, summarize_items(items)) for name, items in by_hall.items()], key=lambda x: x[0]),
        "machine_summary": sorted([(name, summarize_items(items)) for name, items in by_machine.items()], key=lambda x: (-int(x[1]["targets"]), x[0])),
    }


def write_report(rows: list[dict[str, str]], analysis: dict[str, object], min_games: int, low_output_diff_max: int) -> None:
    REPORT_MD.parent.mkdir(exist_ok=True)
    REPORT_HTML.parent.mkdir(exist_ok=True)
    targets = analysis["targets"]
    summary = analysis["summary"]
    lines: list[str] = [
        "# 推定ぶどう履歴 翌掲載日分析",
        "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
        "",
        "判定条件: 推定ぶどう判定が「設定6以上目安」の全台を、G数・差枚に関係なく追跡。",
        "店休日を考慮し、翌カレンダー日ではなく同じ店舗・同じ台番の「次に蓄積された掲載日」と比較します。",
        "機種名が変わった場合は、同じ台番の次掲載日として追跡しつつ「機種変更あり」と表示します。",
        "",
        "## 集計",
        "",
        f"- 履歴行数: {len(rows):,}",
        f"- 追跡対象: {len(targets):,}",
        f"- 翌掲載日まで確認済み: {summary['followed']:,}",
        f"- 翌掲載日なし: {summary['missing']:,}",
    ]
    if summary["followed"]:
        lines.extend([
            f"- 翌掲載日プラス率: {summary['next_positive_count']}/{summary['followed']} ({summary['next_positive_count'] / summary['followed'] * 100:.1f}%)",
            f"- 翌掲載日も推定6率: {summary['next_est_six_count']}/{summary['followed']} ({summary['next_est_six_count'] / summary['followed'] * 100:.1f}%)",
            f"- 翌掲載日同機種継続率: {summary['same_machine_count']}/{summary['followed']} ({summary['same_machine_count'] / summary['followed'] * 100:.1f}%)",
            f"- 翌掲載日平均差枚: {fmt_int(summary['avg_next_diff'])}",
        ])

    def add_summary_table(title: str, rows_: list[tuple[str, dict[str, object]]]) -> None:
        lines.extend(["", f"## {title}", ""])
        lines.append("| 区分 | 対象 | 翌確認 | 翌なし | 翌プラス率 | 翌推定6率 | 同機種継続率 | 翌平均差枚 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, s in rows_:
            followed_count = int(s["followed"])
            plus_rate = f"{int(s['next_positive_count']) / followed_count * 100:.1f}%" if followed_count else "-"
            six_rate = f"{int(s['next_est_six_count']) / followed_count * 100:.1f}%" if followed_count else "-"
            same_rate = f"{int(s['same_machine_count']) / followed_count * 100:.1f}%" if followed_count else "-"
            lines.append(f"| {name} | {s['targets']:,} | {s['followed']:,} | {s['missing']:,} | {plus_rate} | {six_rate} | {same_rate} | {fmt_int(s['avg_next_diff'])} |")

    add_summary_table("基準日の差枚別傾向", analysis["bucket_summary"])
    add_summary_table("基準日のG数別傾向", analysis["games_bucket_summary"])
    add_summary_table("店舗別傾向", analysis["hall_summary"])
    add_summary_table("機種別傾向", analysis["machine_summary"])

    lines.extend(["", "## 追跡対象と翌掲載日", ""])
    lines.append("| 店舗 | 基準日 | 機種 | 台番 | 基準G | 基準差枚 | 基準ぶどう | 翌掲載日 | 翌機種 | 追跡 | 翌G | 翌差枚 | 翌ぶどう | 翌判定 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|")
    for item in targets:
        base = item["base"]
        nxt = item["next"]
        follow_status = "-"
        if nxt:
            follow_status = "同機種継続" if nxt.get("machine") == base.get("machine") else "機種変更あり"
        lines.append(
            "| {hall} | {date} | {machine} | {unit} | {games} | {diff} | {grape} | {next_date} | {next_machine} | {follow_status} | {next_games} | {next_diff} | {next_grape} | {next_grade} |".format(
                hall=base["hall"],
                date=base["date"],
                machine=base["machine"],
                unit=base["unit"],
                games=fmt_int(to_int(base.get("games"))),
                diff=fmt_int(to_int(base.get("diff"))),
                grape=fmt_grape(to_float(base.get("grape_denom"))),
                next_date=nxt["date"] if nxt else "-",
                next_machine=nxt["machine"] if nxt else "-",
                follow_status=follow_status,
                next_games=fmt_int(to_int(nxt.get("games"))) if nxt else "-",
                next_diff=fmt_int(to_int(nxt.get("diff"))) if nxt else "-",
                next_grape=fmt_grape(to_float(nxt.get("grape_denom"))) if nxt else "-",
                next_grade=nxt.get("grade", "-") if nxt else "-",
            )
        )
    if not targets:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | - | - | - |")

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
    td:nth-child(7), td:nth-child(13) {{ color: #b42318; font-weight: 800; }}
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
    parser.add_argument("--min-games", type=int, default=0)
    parser.add_argument("--low-output-diff-max", type=int, default=500)
    parser.add_argument("--backfill-days", type=int, default=0)
    parser.add_argument("--max-new-reports", type=int, default=20)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    delay = args.delay if args.delay is not None else float(config.get("delay_seconds", 5))
    client = report.MinRepoClient(delay_seconds=delay)
    today = datetime.now(JST).date()

    existing = load_history()
    existing_report_keys = {(row["hall"], row["date"]) for row in existing}
    results: list[dict[str, object]] = []
    if args.backfill_days > 0:
        for hall in config["halls"]:
            reports = list_reports_from_tag(client, hall, today, args.backfill_days)
            for latest in reports:
                if (hall["name"], latest["date"].isoformat()) in existing_report_keys:
                    continue
                results.append(collect_hall_report(client, hall, latest))
                if len(results) >= args.max_new_reports:
                    break
            if len(results) >= args.max_new_reports:
                break
    else:
        results = [report.collect_hall(client, hall, today) for hall in config["halls"]]

    history = append_history(results)
    analysis = analyze(history, args.min_games, args.low_output_diff_max)
    write_report(history, analysis, args.min_games, args.low_output_diff_max)


original_find_latest_report = report.find_latest_report
report.find_latest_report = find_latest_report_resilient
report.grade_grape = setting_grade
report.estimate_grape = grape_formula.estimate_grape_by_play_levels


if __name__ == "__main__":
    main()
