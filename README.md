# 液石法ハンドブック

液化石油ガス法・施行令・施行規則の条文（e-Gov）と、液石法まとめ（MulmoClaude wiki）を、スマホで検索・閲覧できる単体HTMLアプリ。

- 公開URL（GitHub Pages）: https://iwbea2012-prog.github.io/lpgas-law-handbook/
- 中身は公開情報（法令・行政資料）と、個人のまとめのみ。取引先名などの業務情報は入れない。

## 更新のしかた

```
python3 tools/build.py --fetch   # 条文を e-Gov から取り直して index.html を再生成
python3 tools/build.py           # wiki だけ更新したとき
```

生成物は `index.html` と `icon.png` の2ファイル。GitHub の Upload files で差し替えれば反映される。
