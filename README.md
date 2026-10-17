# 最新ジャグラーぶどう逆算

みんレポの最新掲載日から、以下4店舗のジャグラー各機種だけを取得し、台番別にぶどう確率を逆算します。

- パーラーゾーン姪浜
- アウトバーンブリッツ
- ワンダーランド西新
- プラザ長浜

## GitHub Actions

Actions の `latest grape estimates` を手動実行すると、最新掲載日のレポートを取得して GitHub Pages 用の HTML を更新します。

初期設定はアクセス間隔 `10秒` です。サイト側に負荷をかけないため、短くしすぎないでください。

## 出力

- `reports/grape_estimates.md`
- `exports/latest_grapes.csv`
- `site/grape_estimates.html`
- `site/index.html`

## ジャグラー日次分析

`daily juggler analysis and picks` は毎日10:05 JSTに実行します。
最新掲載日の台データを保存し、初回は未取得期間を30店舗日ずつ保存しながら最大9回補完します。1年分の掲載日一覧を確認し、空白日だけ取得します。
過去日の補完は全台一覧を1日1回だけ取得し、最新の未取得日だけBB/RB詳細も取得します。

- `data/juggler_history.csv`: 台番別の日次実績
- `data/juggler_predictions.csv`: 当日予想と翌日の答え合わせ
- `reports/juggler_analysis.md`: 曜日・日付末尾の傾向
- `reports/juggler_picks.md`: 機種ごとの当日狙い台と根拠
- `site/juggler_analysis.html`: スマホ用の過去傾向
- `site/juggler_picks.html`: スマホ用の当日狙い台

当たりは2,000G以上かつ差枚+1,000枚以上です。条件未満も削除せず、差枚・G数・BB/RBをそのまま学習材料にします。
100G未満は短期履歴上の低稼働として記録します。0Gは差枚0・出率100%です。

## 前提

ぶどう逆算は BB/RB、差枚、G数、リプレイ確率、チェリー・ベル・ピエロの公表値前提で推定します。
チェリー、ベル、ピエロを実測取得しているわけではありません。
