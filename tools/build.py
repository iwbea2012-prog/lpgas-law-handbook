#!/usr/bin/env python3
"""液石法ハンドブック ビルダー.

raw/*.xml（e-Gov 法令API）と MulmoClaude wiki の液石法ページから
単体の index.html を生成する。

  python3 tools/build.py [--fetch]

--fetch を付けると e-Gov から最新の条文 XML を取り直す。
"""
import json
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
WIKI = ROOT.parent.parent / "data" / "wiki"
TEMPLATE = ROOT / "tools" / "template.html"
OUT = ROOT / "index.html"

LAWS = [
    ("法", "342AC0000000149", "液化石油ガスの保安の確保及び取引の適正化に関する法律"),
    ("令", "343CO0000000014", "同 施行令"),
    ("規則", "409M50000400011", "同 施行規則"),
]
WIKI_PAGES = ["lpgas-law-basics", "lpgas-trade-practice-reform", "lpgas-law-qa-log"]


def fetch():
    RAW.mkdir(exist_ok=True)
    for _, law_id, _ in LAWS:
        url = f"https://laws.e-gov.go.jp/api/1/lawdata/{law_id}"
        print("fetch", url)
        data = urllib.request.urlopen(url, timeout=180).read()
        (RAW / f"{law_id}.xml").write_bytes(data)


def text_of(el):
    """Ruby の読み(Rt)を除いて文字列化。"""
    if el is None:
        return ""
    parts = []

    def walk(e):
        if e.tag == "Rt":
            if e.tail:
                parts.append(e.tail)
            return
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
        if e.tail and e is not el:
            parts.append(e.tail)

    walk(el)
    return re.sub(r"[ \t\r\n]+", "", "".join(parts))


def sentence_text(el):
    """Sentence / Column をまとめて 1 行に。"""
    if el is None:
        return ""
    cols = el.findall("Column")
    if cols:
        return "　".join(text_of(c) for c in cols)
    return "".join(text_of(s) for s in el.iter("Sentence"))


def table_lines(tbl, depth):
    lines = []
    for row in tbl.iter("TableRow"):
        cells = [text_of(c) for c in row.findall("TableColumn")]
        lines.append({"d": depth, "t": "｜".join(cells), "tb": 1})
    return lines


ITEM_TAGS = ["Item"] + [f"Subitem{i}" for i in range(1, 11)]


def item_lines(el, depth):
    lines = []
    title = el.find(el.tag + "Title")
    sent = el.find(el.tag + "Sentence")
    t = (text_of(title) + "　" if title is not None and text_of(title) else "") + sentence_text(sent)
    if t:
        lines.append({"d": depth, "t": t})
    for child in el:
        if child.tag in ITEM_TAGS:
            lines += item_lines(child, depth + 1)
        elif child.tag == "TableStruct":
            lines += table_lines(child, depth + 1)
        elif child.tag == "List":
            for ls in child.iter("ListSentence"):
                lines.append({"d": depth + 1, "t": sentence_text(ls)})
    return lines


def parse_article(art):
    lines = []
    for para in art.findall("Paragraph"):
        num = text_of(para.find("ParagraphNum"))
        sent = sentence_text(para.find("ParagraphSentence"))
        lines.append({"d": 0, "t": (num + "　" if num else "") + sent, "p": 1})
        for child in para:
            if child.tag == "Item":
                lines += item_lines(child, 1)
            elif child.tag == "TableStruct":
                lines += table_lines(child, 1)
            elif child.tag == "List":
                for ls in child.iter("ListSentence"):
                    lines.append({"d": 1, "t": sentence_text(ls)})
    return lines


def parse_law(key, law_id, name):
    root = ET.parse(RAW / f"{law_id}.xml").getroot()
    main = root.find(".//MainProvision")
    arts = []
    last_caption = ""

    def walk(el, path):
        nonlocal last_caption
        for child in el:
            tag = child.tag
            if tag in ("Part", "Chapter", "Section", "Subsection", "Division"):
                title = text_of(child.find(tag + "Title"))
                last_caption = ""  # 見出しの引き継ぎは章・節をまたがない
                walk(child, path + [title])
                last_caption = ""
            elif tag == "Article":
                cap = text_of(child.find("ArticleCaption"))
                inherited = False
                if cap:
                    last_caption = cap
                else:
                    cap = last_caption
                    inherited = True
                title = text_of(child.find("ArticleTitle"))
                lines = parse_article(child)
                deleted = len(lines) == 1 and lines[0]["t"].endswith("削除")
                arts.append({
                    "id": f"{key}-{child.get('Num')}",
                    "law": key,
                    "num": child.get("Num"),
                    "title": title,
                    "cap": cap,
                    "capInh": inherited,
                    "path": " / ".join(p for p in path if p),
                    "lines": lines,
                    "del": deleted,
                })

    walk(main, [])
    return arts


def strip_frontmatter(md):
    title = ""
    if md.startswith("---"):
        end = md.find("\n---", 3)
        fm = md[3:end]
        m = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", fm, re.M)
        if m:
            title = m.group(1)
        md = md[end + 4:]
    md = md.split("<!-- journal-session-backlinks -->")[0]
    return title, md.strip()


def load_wiki():
    pages = []
    for slug in WIKI_PAGES:
        p = WIKI / "pages" / f"{slug}.md"
        if not p.exists():
            continue
        title, body = strip_frontmatter(p.read_text(encoding="utf-8"))
        # 原文控えへの相対リンクは e-Gov に差し替える
        body = re.sub(r"\[([^\]]+)\]\(\.\./sources/[^)]+\)", r"\1（このアプリの条文検索で確認できます）", body)
        pages.append({"id": slug, "title": title, "md": body})
    return pages


CASES_PAGE = "lpgas-case-studies"


def load_cases():
    """wiki のケーススタディページを構造化する（## C番号 ごと）。"""
    p = WIKI / "pages" / f"{CASES_PAGE}.md"
    if not p.exists():
        return []
    _, body = strip_frontmatter(p.read_text(encoding="utf-8"))
    body = body.split("## Related Pages")[0]
    cases = []
    for block in re.split(r"^## (?=C\d+ )", body, flags=re.M)[1:]:
        head, _, rest = block.partition("\n")
        cid, _, title = head.strip().partition(" ")
        meta = dict(re.findall(r"^- ([^:：]+)[:：]\s*(.+)$", rest.split("### ")[0], flags=re.M))
        secs = {}
        for s in re.split(r"^### ", rest, flags=re.M)[1:]:
            name, _, txt = s.partition("\n")
            secs[name.strip()] = txt.strip()
        refs = []
        for law, a, sub in re.findall(r"(法|令|規則)\s*(\d+)条(?:の(\d+))?", meta.get("根拠", "")):
            rid = f"{law}-{a}" + (f"_{sub}" if sub else "")
            if rid not in refs:
                refs.append(rid)
        cases.append({
            "id": cid, "title": title.strip(), "theme": meta.get("テーマ", ""),
            "verdict": meta.get("判定", "").strip(), "basis": meta.get("根拠", ""),
            "kind": meta.get("出典区分", ""), "src": meta.get("出典", ""), "refs": refs,
            "scene": secs.get("場面", ""), "expl": secs.get("解説", ""), "tips": secs.get("実務ポイント", ""),
        })
    return cases


def main():
    if "--fetch" in sys.argv or not RAW.exists():
        fetch()
    laws = []
    for key, law_id, name in LAWS:
        arts = parse_law(key, law_id, name)
        laws.append({"key": key, "id": law_id, "name": name, "arts": arts})
        print(key, len(arts), "articles")
    data = {
        "built": date.today().isoformat(),
        "laws": laws,
        "wiki": load_wiki(),
        "cases": load_cases(),
    }
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js = js.replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    OUT.write_text(html, encoding="utf-8")
    print("cases", len(data["cases"]))
    print("wrote", OUT, f"{OUT.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
