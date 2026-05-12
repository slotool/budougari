import json
from pathlib import Path
import sqlite3


def main():
    config = json.loads(Path("config.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(config["database"])

    for target in config["targets"]:
        rules = target.get("event_rules") or {}
        if not rules:
            continue
        hall_name = target["name"]
        rows = conn.execute(
            "select hall_key, report_date from daily_reports where hall_name = ?",
            (hall_name,),
        ).fetchall()
        for hall_key, report_date in rows:
            ones = str(int(report_date[-2:]) % 10)
            rule = rules.get(ones)
            event_type = rule.get("type") if rule else None
            event_note = rule.get("note") if rule else None
            conn.execute(
                """
                update daily_reports
                   set event_type = ?, event_note = ?
                 where hall_key = ? and report_date = ?
                """,
                (event_type, event_note, hall_key, report_date),
            )

    conn.commit()
    conn.close()
    print("backfilled event labels")


if __name__ == "__main__":
    main()
