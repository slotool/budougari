import datetime as dt
import sqlite3

import minrepo_collect as collector


TABLES = [
    "daily_reports",
    "detail_summaries",
    "machine_reports",
    "unit_bonus_reports",
]
DETAIL_TABLES = ["detail_summaries", "machine_reports", "unit_bonus_reports"]

WEEKDAYS = "月火水木金土日"
WEEKDAY_INDEX = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


def infer_report_date(month, day, collected_on, weekday=None):
    candidates = []
    for year in range(collected_on.year, collected_on.year - 4, -1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue
        if candidate > collected_on:
            continue
        if weekday in WEEKDAY_INDEX and candidate.weekday() != WEEKDAY_INDEX[weekday]:
            continue
        candidates.append(candidate)
    if candidates:
        return max(candidates)

    year = collected_on.year
    candidate = dt.date(year, month, day)
    if candidate > collected_on:
        candidate = dt.date(year - 1, month, day)
    return candidate


def table_exists(conn, name):
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (name,),
    ).fetchone()
    return bool(row)


def table_columns(conn, name):
    if not table_exists(conn, name):
        return set()
    return {row[1] for row in conn.execute(f"pragma table_info({name})")}


def known_hall_names(conn):
    return {
        row["hall_key"]: row["hall_name"]
        for row in conn.execute(
            """
            select hall_key, max(hall_name) hall_name
              from daily_reports
             group by hall_key
            """
        ).fetchall()
    }


def insert_missing_daily_from_details(conn):
    if not table_exists(conn, "detail_summaries"):
        return 0
    names = known_hall_names(conn)
    inserted = 0
    rows = conn.execute(
        """
        select distinct ds.report_id, ds.hall_key, ds.report_date
          from detail_summaries ds
         where ds.report_id is not null
           and ds.report_date is not null
        """
    ).fetchall()
    for row in rows:
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
        hall_name = names.get(row["hall_key"], row["hall_key"])
        event_type, event_note = collector.classify_event(row["report_date"], {})
        conn.execute(
            """
            insert or ignore into daily_reports
            (hall_key, hall_name, report_date, weekday, report_url, report_id, event_type, event_note,
             total_diff, avg_diff, avg_game, featured, collected_at, raw_path)
            values (?, ?, ?, ?, ?, ?, ?, ?, null, null, null, '', ?, null)
            """,
            (
                row["hall_key"],
                hall_name,
                row["report_date"],
                WEEKDAYS[date_value.weekday()],
                f"https://min-repo.com/{row['report_id']}/",
                row["report_id"],
                event_type,
                event_note,
                dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        inserted += 1
    return inserted


def align_detail_dates_to_daily(conn):
    fixed = 0
    daily = conn.execute(
        """
        select report_id, hall_key, report_date
          from daily_reports
         where report_id is not null
        """
    ).fetchall()
    for row in daily:
        for table in DETAIL_TABLES:
            if not table_exists(conn, table):
                continue
            columns = table_columns(conn, table)
            if "report_id" not in columns or "report_date" not in columns:
                continue
            conn.execute(
                f"""
                update {table}
                   set report_date = ?
                 where report_id = ?
                   and report_date != ?
                """,
                (row["report_date"], row["report_id"], row["report_date"]),
            )
            fixed += conn.total_changes
    return fixed


def repair_daily_weekday_dates(conn):
    fixed = 0
    rows = conn.execute(
        """
        select hall_key, report_id, report_date, weekday
          from daily_reports
         where weekday in ('月','火','水','木','金','土','日')
           and report_id is not null
        """
    ).fetchall()
    for row in rows:
        current = dt.date.fromisoformat(row["report_date"])
        expected = infer_report_date(current.month, current.day, dt.date.today(), row["weekday"])
        if expected == current:
            continue
        new_date = expected.isoformat()
        old_date = current.isoformat()
        duplicate = conn.execute(
            """
            select report_id
              from daily_reports
             where hall_key = ?
               and report_date = ?
               and report_id != ?
            """,
            (row["hall_key"], new_date, row["report_id"]),
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
            continue
        for table in TABLES:
            if not table_exists(conn, table):
                continue
            columns = table_columns(conn, table)
            if "report_id" not in columns or "report_date" not in columns:
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
        fixed += 1
    return fixed


def repair_dates(db_path="data/minrepo.sqlite"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    collector.init_db(conn)
    fixed = 0
    fixed += repair_daily_weekday_dates(conn)
    fixed += insert_missing_daily_from_details(conn)
    fixed += align_detail_dates_to_daily(conn)
    if table_exists(conn, "unit_bonus_reports"):
        fixed += insert_missing_daily_from_details(conn)
    conn.commit()
    collector.export_csv(conn, "exports")
    conn.close()
    print(f"repaired report dates: {fixed}")


if __name__ == "__main__":
    repair_dates()
