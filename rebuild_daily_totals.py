import argparse
import datetime as dt
import sqlite3


def rebuild(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        select hall_key, report_date,
               count(*) unit_count,
               sum(avg_diff) total_diff,
               round(avg(avg_diff)) avg_diff,
               round(avg(avg_game)) avg_game
          from machine_reports
         where category = 'unit'
           and avg_diff is not null
         group by hall_key, report_date
        """
    ).fetchall()
    collected_at = dt.datetime.now().isoformat(timespec="seconds")
    updated = 0
    for row in rows:
        if not row["unit_count"]:
            continue
        cursor = conn.execute(
            """
            update daily_reports
               set total_diff = ?,
                   avg_diff = ?,
                   avg_game = coalesce(?, avg_game),
                   collected_at = ?
             where hall_key = ?
               and report_date = ?
            """,
            (
                row["total_diff"],
                row["avg_diff"],
                row["avg_game"],
                collected_at,
                row["hall_key"],
                row["report_date"],
            ),
        )
        updated += cursor.rowcount if cursor.rowcount > 0 else 0
    conn.commit()
    conn.close()
    print(f"rebuilt daily totals from unit rows={len(rows)}, updated daily rows={updated}")


def main():
    parser = argparse.ArgumentParser(description="Rebuild daily total/average diffs from stored unit rows.")
    parser.add_argument("--db", default="data/minrepo.sqlite")
    args = parser.parse_args()
    rebuild(args.db)


if __name__ == "__main__":
    main()
