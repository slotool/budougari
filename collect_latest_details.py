import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import time

import collect_event_details as detail_tools
import minrepo_collect as collector


def collect_latest(config, hall=None):
    conn = sqlite3.connect(config["database"])
    conn.row_factory = sqlite3.Row
    collector.init_db(conn)
    targets = [item for item in config["targets"] if hall is None or item["name"] == hall]
    collected_at = dt.datetime.now().isoformat(timespec="seconds")
    collected_on = dt.date.today()
    delay = float(config.get("request_delay_seconds", 1.0))
    d2_cookie = None
    count = 0

    for target in targets:
        hall_id = collector.hall_key(target["name"], target["url"])
        report = conn.execute(
            """
            select *
              from daily_reports
             where hall_name = ?
               and report_url is not null
               and report_id is not null
             order by report_date desc
             limit 1
            """,
            (target["name"],),
        ).fetchone()
        if not report:
            continue
        report = dict(report)
        all_url = report["report_url"].rstrip("/") + "/?kishu=all&sort=num"
        all_html, d2_cookie = detail_tools.fetch_with_d2(all_url, d2_cookie, delay)
        raw_path = collector.save_raw(
            config["raw_dir"], collected_on, hall_id, f"{report['report_id']}_latest_all", all_html
        )
        _, unit_records = collector.parse_detail_page(all_html, report, row_category="unit")
        collector.save_detail(conn, hall_id, report, {}, unit_records, collected_at, raw_path)
        detail_tools.update_daily_from_units(conn, hall_id, report, unit_records, collected_at)
        conn.commit()
        count += 1
        time.sleep(delay)

    collector.export_csv(conn, config["csv_dir"])
    conn.close()
    print(f"collected latest all-unit pages={count}")


def main():
    parser = argparse.ArgumentParser(description="Collect latest all-unit pages and rebuild daily totals.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--hall")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    collect_latest(config, args.hall)


if __name__ == "__main__":
    main()
