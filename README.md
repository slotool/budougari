# 最新ジャグラーぶどう逆算

みんレポの最新掲載日から、以下2店舗のジャグラー各機種だけを取得し、台番別にぶどう確率を逆算します。

- パーラーゾーン姪浜
- アウトバーンブリッツ

## GitHub Actions

Actions の `latest grape estimates` を手動実行すると、最新掲載日のレポートを取得して GitHub Pages 用の HTML を更新します。

初期設定はアクセス間隔 `10秒` です。サイト側に負荷をかけないため、短くしすぎないでください。

## 出力

- `reports/grape_estimates.md`
- `exports/latest_grapes.csv`
- `site/grape_estimates.html`
- `site/index.html`

## 前提

ぶどう逆算は BB/RB、差枚、G数、リプレイ確率、チェリー・ベル・ピエロの公表値前提で推定します。
チェリー、ベル、ピエロを実測取得しているわけではありません。