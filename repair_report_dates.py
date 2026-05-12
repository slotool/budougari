import datetime as dt
import sqlite3

import minrepo_collect as collector


TABLES = [
    "daily_reports",
    "detail_summaries",
    "machine_reports",
    "unit_bonus_reports",
]

WEEKDAYS = "月火水木金土日"


def table_exists(conn, name):
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (name,),
    ).fetchone()
    return bool(row)


def repair_dates(db_path="data/minrepo.sqlite"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    fixed = 0
    rows = conn.execute(
        """
        select hall_key, report_id, report_date, weekday
          from daily_reports
         where weekday in ('月','火','水','木','金','土','日')
        """
    ).fetchall()
    for row in rows:
        current = dt.date.fromisoformat(row["report_date"])
        expected = collector.infer_report_date(current.month, current.day, dt.date.today(), row["weekday"])
        if expected == current:
            continue
        new_date = expected.isoformat()
        old_date = current.isoformat()
        for table in TABLES:
            if not table_exists(conn, table):
                continue
            conn.execute(
                f"""
                update or ignore {table}
                   set report_date = ?
                 where report_id = ?
                   and report_date = ?
                """,
                (new_date, row["report_id"], old_date),
            )
        duplicate = conn.execute(
            """
            select 1
              from daily_reports
             where hall_key = ?
               and report_date = ?
            """,
            (row["hall_key"], new_date),
        ).fetchone()
        if duplicate:
            conn.execute(
                """
                delete from daily_reports
                 where hall_key = ?
                   and report_id = ?
                   and report_date = ?
                """,
                (row["hall_key"], row["report_id"], old_date),
            )
        fixed += 1
    if table_exists(conn, "unit_bonus_reports"):
        bonus_rows = conn.execute(
            """
            select distinct hall_key, hall_name, report_date, report_id
              from unit_bonus_reports
            """
        ).fetchall()
        for row in bonus_rows:
            exists = conn.execute(
                """
                select 1
                  from daily_reports
                 where hall_key = ?
                   and report_date = ?
                """,
                (row["hall_key"], row["report_date"]),
            ).fetchone()
            if exists:
                continue
            date_value = dt.date.fromisoformat(row["report_date"])
            event_type, event_note = collector.classify_event(row["report_date"], {})
            conn.execute(
                """
                insert into daily_reports
                (hall_key, hall_name, report_date, weekday, report_url, report_id, event_type, event_note,
                 total_diff, avg_diff, avg_game, featured, collected_at, raw_path)
                values (?, ?, ?, ?, ?, ?, ?, ?, null, null, null, '', ?, null)
                """,
                (
                    row["hall_key"],
                    row["hall_name"],
                    row["report_date"],
                    WEEKDAYS[date_value.weekday()],
                    f"https://min-repo.com/{row['report_id']}/",
                    row["report_id"],
                    event_type,
                    event_note,
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )
            fixed += 1
    conn.commit()
    conn.close()
    print(f"repaired report dates: {fixed}")


if __name__ == "__main__":
    repair_dates()
