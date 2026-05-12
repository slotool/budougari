# GitHub Actions + Pages でスマホ実行する手順

## 初回設定

1. このフォルダを GitHub リポジトリへ push します。
2. GitHub の `Settings > Pages` を開きます。
3. `Build and deployment` の `Source` を `GitHub Actions` にします。
4. `Actions` タブで `minrepo reports` を開きます。

## スマホから実行

1. GitHub アプリ、またはスマホブラウザでリポジトリを開きます。
2. `Actions` タブを開きます。
3. `minrepo reports` を選びます。
4. `Run workflow` を押します。
5. 基本は初期値のままで実行します。

入力項目:

- `report_date`: 空欄なら日本時間の今日。店休日がある場合も、取得済みの最新掲載日を使います。
- `collect_latest`: 最新のみんレポ一覧・詳細を取得します。
- `collect_bonus`: ジャグラーのBB/RB、マイナス差枚込みの機種別一覧を取得します。
- `delay_seconds`: みんレポへのアクセス間隔です。通常は `15` 秒のままにします。

## 結果確認

実行が終わると GitHub Pages に `site/` が公開されます。

主に見るページ:

- `grape_estimates.html`: 逆算ぶどう
- `combined_juggler.html`: 姪浜・アウトバーン合同
- `juggler_today.html`: 姪浜
- `outbound_juggler_today.html`: アウトバーン

## 注意

- 自動スケジュールは入れていません。スマホから手動実行します。
- `collect_bonus` は `_d2` Cookie を取得してから再アクセスするため、最初の1機種だけ追加で1回アクセスします。
- アクセス過多を避けるため、`delay_seconds` は下げすぎないでください。
