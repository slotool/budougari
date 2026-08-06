from __future__ import annotations

import html
import re
from pathlib import Path


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("#### "):
            out.append(f"<h4>{html.escape(line[5:])}</h4>")
        elif line.startswith("### "):
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{linkify(html.escape(lines[i][2:]))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(render_table(table_lines))
            continue
        else:
            out.append(f"<p>{linkify(html.escape(line))}</p>")
        i += 1
    return "\n".join(out)


def linkify(text: str) -> str:
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', text)


def render_table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = [row for row in rows[2:] if any(cell.strip("-: ") for cell in row)]
    ths = "".join(f'<th><button type="button" class="sort-btn">{html.escape(cell)}</button></th>' for cell in header)
    trs = []
    for row in body:
        tds = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        trs.append(f"<tr>{tds}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def main() -> None:
    md_path = Path("reports/grape_estimates.md")
    if not md_path.exists():
        raise SystemExit("reports/grape_estimates.md がありません。先に latest_grape_report.py を実行してください。")

    body = markdown_to_html(md_path.read_text(encoding="utf-8"))
    html_doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>最新ジャグラーぶどう逆算</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f5;
      --paper: #ffffff;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d9dee5;
      --head: #eef4ff;
      --accent: #b42318;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 18px 12px 48px;
    }}
    h1 {{ margin: 0 0 14px; font-size: 24px; }}
    h2 {{ margin: 28px 0 10px; padding-top: 12px; border-top: 3px solid var(--accent); font-size: 22px; }}
    h3 {{ margin: 24px 0 10px; font-size: 18px; }}
    h4 {{ margin: 22px 0 8px; font-size: 17px; }}
    p, li {{ font-size: 14px; }}
    .table-wrap {{
      overflow-x: auto;
      margin: 8px 0 18px;
      border: 1px solid var(--line);
      background: var(--paper);
    }}
    table {{ width: 100%; min-width: 620px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
    th {{ position: sticky; top: 0; background: var(--head); color: #1d2939; font-weight: 700; }}
    .sort-btn {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border: 0;
      padding: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .sort-btn::after {{ content: "↕"; color: var(--muted); font-size: 11px; }}
    th[data-sort-dir="asc"] .sort-btn::after {{ content: "↑"; color: var(--accent); }}
    th[data-sort-dir="desc"] .sort-btn::after {{ content: "↓"; color: var(--accent); }}
    th:first-child, td:first-child {{
      position: sticky;
      left: 0;
      z-index: 1;
      background: var(--paper);
      text-align: right;
      font-weight: 700;
      box-shadow: 1px 0 0 var(--line);
    }}
    th:first-child {{ background: var(--head); z-index: 2; }}
    th:nth-child(2), td:nth-child(2) {{ color: var(--accent); font-weight: 800; }}
    td:nth-child(3), th:nth-child(3), td:first-child + td + td {{ text-align: left; }}
    a {{ color: #175cd3; word-break: break-all; }}
    @media (max-width: 640px) {{
      main {{ padding: 14px 8px 40px; }}
      h1 {{ font-size: 21px; }}
      h2 {{ font-size: 19px; }}
      table {{ min-width: 560px; font-size: 12px; }}
      th, td {{ padding: 7px 8px; }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
  <script>
    function parseCellValue(text) {{
      const raw = text.trim();
      if (!raw || raw === "-") return null;
      const grape = raw.match(/^1\/(\d+(?:\.\d+)?)/);
      if (grape) return Number(grape[1]);
      if (raw.includes("設定6以上")) return 7;
      if (raw.includes("設定1未満")) return 0;
      const setting = raw.match(/設定(\d)/);
      if (setting) return Number(setting[1]);
      const numeric = raw.replace(/,/g, "").replace(/%/g, "").match(/-?\d+(?:\.\d+)?/);
      if (numeric) return Number(numeric[0]);
      return raw;
    }}

    document.querySelectorAll("table").forEach((table) => {{
      table.querySelectorAll("th").forEach((th, index) => {{
        th.addEventListener("click", () => {{
          const tbody = table.querySelector("tbody");
          const rows = Array.from(tbody.querySelectorAll("tr"));
          const current = th.dataset.sortDir;
          const next = current === "asc" ? "desc" : "asc";
          table.querySelectorAll("th").forEach((other) => delete other.dataset.sortDir);
          th.dataset.sortDir = next;

          rows.sort((a, b) => {{
            const av = parseCellValue(a.children[index]?.innerText || "");
            const bv = parseCellValue(b.children[index]?.innerText || "");
            if (av === null && bv === null) return 0;
            if (av === null) return 1;
            if (bv === null) return -1;
            if (typeof av === "number" && typeof bv === "number") {{
              return next === "asc" ? av - bv : bv - av;
            }}
            return next === "asc"
              ? String(av).localeCompare(String(bv), "ja")
              : String(bv).localeCompare(String(av), "ja");
          }});
          rows.forEach((row) => tbody.appendChild(row));
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    Path("site").mkdir(exist_ok=True)
    Path("site/grape_estimates.html").write_text(html_doc, encoding="utf-8")
    picks_path = Path("site/juggler_picks.html")
    index_doc = picks_path.read_text(encoding="utf-8") if picks_path.exists() else html_doc
    Path("site/index.html").write_text(index_doc, encoding="utf-8")


if __name__ == "__main__":
    main()
