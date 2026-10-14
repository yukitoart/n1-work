# #001 実写素材のショットリスト

下のファイル名で `youtube/assets/footage/` に置くと、次のビルドから自動で実写に差し替わる
（置かないあいだは、同じ位置にモーショングラフィックスが入る）。

- 使ってよい素材：商用利用可のストック（Pexels / Pixabay など）、自分で撮影したもの、自分で生成した AI 映像
- 使ってはいけない素材：テレビ・他人の YouTube 動画、サイゼリヤの公式写真・ロゴ・店内の無断撮影
- 推奨：横長 1920x1080 以上、5〜15秒、人物の顔がはっきり映らないもの

| ファイル名 | 使う場面 | 検索キーワード（Pexels / Pixabay） |
|---|---|---|
| `gratin_steam.mp4` | 冒頭「ミラノ風ドリア、300円」 | gratin steam, baked cheese close up, doria |
| `family_restaurant.mp4` | 冒頭「こんなに安くて利益が出る？」 | family restaurant interior, casual dining busy |
| `japan_old_street.mp4` | 原点「1967年、本八幡」 | old japanese shopping street, showa street |
| `shanghai_night.mp4` | 日本とアジア | shanghai skyline night, china city aerial |
| `food_factory.mp4` | カラクリ① 製造直販 | food factory production line, food processing |
| `dairy_farm.mp4` | カラクリ① ホワイトソース・オーストラリア | australia dairy farm, cows pasture |
| `kitchen_plating.mp4` | カラクリ② 店で料理しない | restaurant kitchen plating, commercial kitchen |
| `supermarket_prices.mp4` | カラクリ③ 物価高 | supermarket price tags, grocery shopping inflation |
| `stock_chart.mp4` | 値上げ発表で株価ストップ高 | stock market chart screen, trading screen |

自動で取得したい場合は、環境のネットワーク設定で `pexels.com`・`images.pexels.com`・`videos.pexels.com`
（Pixabay なら `pixabay.com`・`cdn.pixabay.com`）を許可し、各サービスの無料 API キーを環境変数に設定する。
