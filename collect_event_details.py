import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.request import Request, urlopen

import minrepo_collect as collector


def extract_cookie(page_html, name):
    match = re.search(rf"\$\.cookie\('{re.escape(name)}',\s*'([^']+)'", page_html)
    return match.group(1) if match else None


def fetch_with_d2(url, d2_cookie=None, delay=0.0):
    headers = {"User-Agent": collector.USER_AGENT}
    if d2_cookie:
        headers["Cookie"] = f"_d2={d2_cookie}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page_html = response.read().decode(charset, "replace")
    if not d2_cookie:
        d2_cookie = extract_cookie(page_html, "_d2")
        if d2_cookie:
            if delay:
                time.sleep(delay)
            return fetch_with_d2(url, d2_cookie, 0.0)
    return page_html, d2_cookie


def update_daily_from_units(conn, hall_id, report, unit_records, collected_at):
    diffs = [item["avg_diff"] for item in unit_records if item.get("avg_diff") is not None]
    games = [item["avg_game"] for item in unit_records if item.get("avg_game") is not None]
    if not diffs:
        return
    total_diff = sum(diffs)
    avg_diff = round(total_diff / len(diffs))
    avg_game = round(sum(games) / len(games)) if games else None
    conn.execute(
        """
        update daily_reports
           set total_diff = ?,
               avg_diff = ?,
               avg_game = coalesce(?, avg_game),
               collected_at = ?
         where hall_key = ?
           and report_date = ?
        """,
        (total_diff, avg_diff, avg_game, collected_at, hall_id, report["report_date"]),
    )


def main():
    parser = argparse.ArgumentParser(description="Collect detail/all-unit pages for selected event days.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--hall", default="パーラーゾーン姪浜")
    parser.add_argument("--ones", default="5", help="Comma-separated day ones digits, e.g. 5 or 3,5,6,9.")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--weekdays", default="", help="Comma-separated Japanese weekdays, e.g. 土,日.")
    parser.add_argument("--limit-per-group", type=int, help="Collect up to this many reports for each ones/weekday group.")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    conn = sqlite3.connect(config["database"])
    collector.init_db(conn)
    target = next(item for item in config["targets"] if item["name"] == args.hall)
    hall_id = collector.hall_key(target["name"], target["url"])
    ones_digits = {int(value.strip()) for value in args.ones.split(",") if value.strip()}
    weekdays = {value.strip() for value in args.weekdays.split(",") if value.strip()}

    conn.row_factory = sqlite3.Row
    reports = conn.execute(
        """
        select *
          from daily_reports
         where hall_name = ?
           and report_url is not null
           and report_id is not null
         order by report_date desc
        """,
        (args.hall,),
    ).fetchall()
    selected_map = {}
    if args.limit_per_group:
        for digit in ones_digits:
            matches = [row for row in reports if int(row["report_date"][-2:]) % 10 == digit]
            for row in matches[: args.limit_per_group]:
                selected_map[row["report_id"]] = row
        for weekday in weekdays:
            matches = [row for row in reports if row["weekday"] == weekday]
            for row in matches[: args.limit_per_group]:
                selected_map[row["report_id"]] = row
    else:
        selected = [
            row
            for row in reports
            if (ones_digits and int(row["report_date"][-2:]) % 10 in ones_digits)
            or (weekdays and row["weekday"] in weekdays)
        ][: args.limit]
        selected_map = {row["report_id"]: row for row in selected}

    selected = sorted(selected_map.values(), key=lambda row: row["report_date"], reverse=True)

    collected_at = dt.datetime.now().isoformat(timespec="seconds")
    collected_on = dt.date.today()
    delay = float(config.get("request_delay_seconds", 1.0))
    count = 0
    d2_cookie = None

    for row in selected:
        report = dict(row)
        detail_html, d2_cookie = fetch_with_d2(report["report_url"], d2_cookie, delay)
        detail_raw_path = collector.save_raw(
            config["raw_dir"], collected_on, hall_id, report["report_id"], detail_html
        )
        summary, records = collector.parse_detail_page(detail_html, report)
        collector.save_detail(conn, hall_id, report, summary, records, collected_at, detail_raw_path)

        time.sleep(delay)
        all_url = report["report_url"].rstrip("/") + "/?kishu=all&sort=num"
        all_html, d2_cookie = fetch_with_d2(all_url, d2_cookie, delay)
        all_raw_path = collector.save_raw(
            config["raw_dir"], collected_on, hall_id, f"{report['report_id']}_all", all_html
        )
        _, unit_records = collector.parse_detail_page(all_html, report, row_category="unit")
        collector.save_detail(conn, hall_id, report, {}, unit_records, collected_at, all_raw_path)
        update_daily_from_units(conn, hall_id, report, unit_records, collected_at)
        conn.commit()
        count += 1
        time.sleep(delay)

    collector.export_csv(conn, config["csv_dir"])
    conn.close()
    print(f"collected event detail pages={count}")


if __name__ == "__main__":
    main()
