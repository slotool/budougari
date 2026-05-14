from __future__ import annotations

import html
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


JST = timezone(timedelta(hours=9))
SMARTPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

TARGETS = [
    {
        "hall": "アウトバーンブリッツ",
        "url": "https://autobahn.pt.teramoba2.com/blitz/rack_info_kt/?kind_code=20",
        "referer": "https://autobahn.pt.teramoba2.com/",
    },
    {
        "hall": "パーラーゾーン姪浜",
        "url": "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c750701/cgi-bin/nc-v03-001.php?cd_ps=2",
        "referer": "https://p-town.dmm.com/",
    },
]


def fetch(url: str, referer: str) -> tuple[int | None, str, str | None]:
    req = Request(
        url,
        headers={
            "User-Agent": SMARTPHONE_UA,
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
        },
    )
    try:
        with urlopen(req, timeout=30) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            body = res.read().decode(charset, errors="replace")
            return res.status, body, None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body, f"HTTP {exc.code}"
    except URLError as exc:
        return None, "", f"URL error: {exc}"


def strip_tags(source: str) -> str:
    source = re.sub(r"<script\b.*?</script>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<style\b.*?</style>", " ", source, flags=re.I | re.S)
    source = re.sub(r"<[^>]+>", " ", source)
    return " ".join(html.unescape(source).split())


def probe_text(text: str) -> dict[str, object]:
    unit_numbers = sorted({int(x) for x in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", text) if 50 <= int(x) <= 9999})
    juggler_hits = re.findall(r".{0,12}(?:ジャグラー|アイム|ゴーゴー|マイジャグ|ファンキー|ハッピー|ミラクル).{0,12}", text)
    bonus_words = re.findall(r"(?:BB|RB|BIG|REG|大当|回転|ゲーム|G数|総回転)", text)
    return {
        "unit_count_guess": len(unit_numbers),
        "unit_samples": unit_numbers[:30],
        "juggler_hit_count": len(juggler_hits),
        "juggler_samples": juggler_hits[:12],
        "bonus_word_count": len(bonus_words),
    }


def main() -> None:
    Path("reports").mkdir(exist_ok=True)
    lines = [
        "# 当日台データ取得テスト",
        "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
        "",
        "スマホUser-Agentで各URLを1回だけ取得し、台番・ジャグラー・BB/RB系の文字がHTML内にあるか確認します。",
        "",
    ]

    for target in TARGETS:
        status, body, error = fetch(target["url"], target["referer"])
        text = strip_tags(body)
        probe = probe_text(text)
        lines.extend(
            [
                f"## {target['hall']}",
                "",
                f"- URL: {target['url']}",
                f"- HTTP: {status if status is not None else '-'}",
                f"- エラー: {error or '-'}",
                f"- HTMLサイズ: {len(body):,}",
                f"- テキストサイズ: {len(text):,}",
                f"- 台番候補数: {probe['unit_count_guess']}",
                f"- 台番候補サンプル: {probe['unit_samples']}",
                f"- ジャグラー系ヒット数: {probe['juggler_hit_count']}",
                f"- ジャグラー系サンプル: {probe['juggler_samples']}",
                f"- BB/RB/G数系ワード数: {probe['bonus_word_count']}",
                "",
                "```text",
                text[:1200],
                "```",
                "",
            ]
        )

    Path("reports/today_data_probe.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
