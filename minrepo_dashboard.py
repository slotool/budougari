import datetime as dt
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import urllib.parse


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
PYTHON = "python"


def run_command(args):
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stdout or "") + "\n" + (result.stderr or ""))
    return (result.stdout or "").strip()


def today():
    return dt.date.today()


def markdown_to_html(markdown):
    lines = markdown.splitlines()
    out = []
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not in_table:
            return
        out.append("<div class='table-wrap'><table>")
        for idx, row in enumerate(table_rows):
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if idx == 1 and all(set(cell) <= {"-", ":"} for cell in cells):
                continue
            tag = "th" if idx == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in cells) + "</tr>")
        out.append("</table></div>")
        in_table = False
        table_rows = []

    for line in lines:
        if line.startswith("|") and line.endswith("|"):
            in_table = True
            table_rows.append(line)
            continue
        flush_table()
        if line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            out.append(f"<p class='bullet'>• {html.escape(line[2:])}</p>")
        elif line.strip():
            out.append(f"<p>{html.escape(line)}</p>")
    flush_table()
    return "\n".join(out)


def page(title, body):
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: #f7f7f4; color: #202124; }}
    header {{ position: sticky; top: 0; background: #ffffff; border-bottom: 1px solid #ddd; padding: 12px 16px; z-index: 2; }}
    header h1 {{ margin: 0 0 10px; font-size: 20px; }}
    nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    a, button {{ color: #111; }}
    .btn, button {{ appearance: none; border: 1px solid #bbb; background: #fff; padding: 10px 12px; border-radius: 6px; text-decoration: none; font-size: 14px; }}
    .primary {{ background: #1f6feb; color: white; border-color: #1f6feb; }}
    main {{ padding: 16px; max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 24px; margin: 16px 0 10px; }}
    h2 {{ font-size: 19px; margin-top: 28px; border-top: 1px solid #ddd; padding-top: 16px; }}
    h3 {{ font-size: 16px; margin-top: 22px; }}
    p {{ line-height: 1.5; }}
    form {{ display: inline; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 14px 0; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 14px; }}
    .table-wrap {{ overflow-x: auto; background: white; border: 1px solid #ddd; border-radius: 8px; margin: 10px 0 18px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; min-width: 780px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child, th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
    th {{ background: #fafafa; position: sticky; top: 0; }}
    .notice {{ background: #fff7d6; border: 1px solid #e7cf72; padding: 12px; border-radius: 8px; }}
    .error {{ background: #ffe8e8; border-color: #d66; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <header>
    <h1>min-repo 分析</h1>
    <nav>
      <a class="btn" href="/">ホーム</a>
      <a class="btn" href="/report?name=combined_juggler_report.md">合同</a>
      <a class="btn" href="/report?name=juggler_today.md">姪浜</a>
      <a class="btn" href="/report?name=outbound_juggler_today.md">アウトバーン</a>
      <a class="btn" href="/report?name=grape_estimates.md">ぶどう推定</a>
      <form method="post" action="/run"><button class="primary" name="kind" value="today">本日を再生成</button></form>
      <form method="post" action="/run"><button name="kind" value="patterns">傾向を再生成</button></form>
    </nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def send_html(self, text, status=200):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = f"""
<div class="notice">PCを起動したまま、同じWi-Fiのスマホからこの画面を開くとレポートを確認できます。</div>
<div class="grid">
  <div class="card"><h2>合同</h2><p>{today().isoformat()} 実行分の姪浜・アウトバーン狙い台。</p><a class="btn primary" href="/report?name=combined_juggler_report.md">開く</a></div>
  <div class="card"><h2>姪浜</h2><p>パーラーゾーン姪浜の本日狙い台。</p><a class="btn primary" href="/report?name=juggler_today.md">開く</a></div>
  <div class="card"><h2>アウトバーン</h2><p>アウトバーンブリッツの本日狙い台。</p><a class="btn primary" href="/report?name=outbound_juggler_today.md">開く</a></div>
  <div class="card"><h2>ぶどう推定</h2><p>対象日以前の最新掲載データから機種別に推定。</p><a class="btn primary" href="/report?name=grape_estimates.md">開く</a></div>
  <div class="card"><h2>傾向</h2><p>イベント別・曜日別・前日差枚別の検証。</p><a class="btn primary" href="/report?name=juggler_pattern_analysis.md">開く</a></div>
</div>
"""
            self.send_html(page("ホーム", body))
            return

        if parsed.path == "/report":
            params = urllib.parse.parse_qs(parsed.query)
            name = params.get("name", [""])[0]
            safe = Path(name).name
            path = REPORTS / safe
            if not path.exists():
                self.send_html(page("見つかりません", f"<p class='error'>レポートがありません: {html.escape(safe)}</p>"), 404)
                return
            content = path.read_text(encoding="utf-8")
            self.send_html(page(safe, markdown_to_html(content)))
            return

        self.send_html(page("見つかりません", "<p>ページがありません。</p>"), 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body)
        kind = form.get("kind", [""])[0]

        try:
            if parsed.path != "/run":
                raise RuntimeError("unknown action")
            if kind == "today":
                target = today().isoformat()
                messages = [
                    run_command([PYTHON, "minrepo_collect.py"]),
                    run_command([PYTHON, "analyze_juggler.py", "--date", target, "--out", "reports/juggler_today.md"]),
                    run_command([PYTHON, "analyze_juggler.py", "--hall", "アウトバーンブリッツ", "--date", target, "--out", "reports/outbound_juggler_today.md"]),
                    run_command([PYTHON, "estimate_grapes.py", "--date", target, "--out", "reports/grape_estimates.md"]),
                    run_command([PYTHON, "build_combined_report.py"]),
                ]
                message = "\n".join(messages)
                link = "/report?name=combined_juggler_report.md"
            elif kind == "patterns":
                message = run_command([PYTHON, "analyze_juggler_patterns.py"])
                link = "/report?name=juggler_pattern_analysis.md"
            else:
                raise RuntimeError("unknown kind")
            self.send_html(page("完了", f"<p class='notice'>{html.escape(message)}</p><p><a class='btn primary' href='{link}'>レポートを見る</a></p>"))
        except Exception as exc:
            self.send_html(page("エラー", f"<pre class='error'>{html.escape(str(exc))}</pre>"), 500)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
    print("dashboard: http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
