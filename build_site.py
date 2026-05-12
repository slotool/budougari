import datetime as dt
import html
from pathlib import Path

from minrepo_dashboard import markdown_to_html


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"


REPORT_LINKS = [
    ("合同", "combined_juggler.html", "combined_juggler_report.md"),
    ("姪浜 本日", "juggler_today.html", "juggler_today.md"),
    ("姪浜 傾向", "juggler_patterns.html", "juggler_pattern_analysis.md"),
    ("アウトバーン 本日", "outbound_juggler_today.html", "outbound_juggler_today.md"),
    ("アウトバーン 傾向", "outbound_juggler_patterns.html", "outbound_juggler_pattern_analysis.md"),
    ("ぶどう推定", "grape_estimates.html", "grape_estimates.md"),
    ("総合分析", "latest_analysis.html", "latest_analysis.md"),
]


def wrap(title, body):
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    nav = " ".join(f'<a class="btn" href="{href}">{label}</a>' for label, href, _ in REPORT_LINKS)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: #f7f7f4; color: #202124; }}
    header {{ position: sticky; top: 0; background: #fff; border-bottom: 1px solid #ddd; padding: 12px 16px; z-index: 2; }}
    header h1 {{ margin: 0 0 10px; font-size: 20px; }}
    nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .btn {{ color: #111; border: 1px solid #bbb; background: #fff; padding: 10px 12px; border-radius: 6px; text-decoration: none; font-size: 14px; display: inline-block; }}
    main {{ padding: 16px; max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 24px; margin: 16px 0 10px; }}
    h2 {{ font-size: 19px; margin-top: 28px; border-top: 1px solid #ddd; padding-top: 16px; }}
    h3 {{ font-size: 16px; margin-top: 22px; }}
    p {{ line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 14px 0; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 14px; }}
    .table-wrap {{ overflow-x: auto; background: white; border: 1px solid #ddd; border-radius: 8px; margin: 10px 0 18px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; min-width: 780px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child, th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
    th {{ background: #fafafa; }}
    .notice {{ background: #fff7d6; border: 1px solid #e7cf72; padding: 12px; border-radius: 8px; }}
  </style>
</head>
<body>
  <header><h1>min-repo 分析</h1><nav><a class="btn" href="index.html">ホーム</a>{nav}</nav></header>
  <main>
    <p class="notice">生成日時: {generated}</p>
    {body}
  </main>
</body>
</html>"""


def write_report_page(label, href, markdown_name):
    markdown_path = REPORTS / markdown_name
    if not markdown_path.exists():
        body = f"<h1>{html.escape(label)}</h1><p>まだレポートがありません。</p>"
    else:
        body = markdown_to_html(markdown_path.read_text(encoding="utf-8"))
    (SITE / href).write_text(wrap(label, body), encoding="utf-8")


def main():
    SITE.mkdir(exist_ok=True)
    cards = []
    for label, href, markdown_name in REPORT_LINKS:
        write_report_page(label, href, markdown_name)
        cards.append(
            f'<div class="card"><h2>{html.escape(label)}</h2>'
            f'<p>{html.escape(markdown_name)}</p><a class="btn" href="{href}">開く</a></div>'
        )
    body = "<h1>レポート一覧</h1><div class='grid'>" + "\n".join(cards) + "</div>"
    (SITE / "index.html").write_text(wrap("ホーム", body), encoding="utf-8")
    print(f"wrote {SITE}")


if __name__ == "__main__":
    main()
