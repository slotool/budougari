from pathlib import Path


REPORTS = Path("reports")


SECTIONS = [
    ("姪浜 本日", "juggler_today.md"),
    ("アウトバーン 本日", "outbound_juggler_today.md"),
    ("最新掲載ぶどう推定", "grape_estimates.md"),
]


def top_part(markdown, line_limit=32):
    lines = markdown.splitlines()
    if "## 機種別 狙い台" in lines:
        lines = lines[: lines.index("## 機種別 狙い台")]
    return "\n".join(lines[:line_limit]).strip()


def main():
    out = ["# 姪浜・アウトバーン 合同ジャグラー狙い台", ""]
    for title, filename in SECTIONS:
        path = REPORTS / filename
        out.extend([f"## {title}", ""])
        if path.exists():
            out.append(top_part(path.read_text(encoding="utf-8")))
        else:
            out.append(f"{filename} がまだありません。")
        out.append("")

    out.extend(
        [
            "## 詳細レポート",
            "",
            "- 姪浜 本日: `reports/juggler_today.md`",
            "- 姪浜 傾向: `reports/juggler_pattern_analysis.md`",
            "- アウトバーン 本日: `reports/outbound_juggler_today.md`",
            "- アウトバーン 傾向: `reports/outbound_juggler_pattern_analysis.md`",
            "- 最新掲載ぶどう推定: `reports/grape_estimates.md`",
        ]
    )

    output = REPORTS / "combined_juggler_report.md"
    output.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
