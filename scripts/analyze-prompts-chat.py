#!/usr/bin/env python3
import csv, io, json, re, urllib.request, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

CSV_URL = "https://raw.githubusercontent.com/f/prompts.chat/main/prompts.csv"
API_URL = "https://prompts.chat/api/prompts?perPage=1&page=1"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "agt-prompt-lab-analysis/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()

def provider(model):
    m = model.lower()
    if any(x in m for x in ("gpt", "o1", "o3", "o4", "openai")): return "OpenAI"
    if any(x in m for x in ("claude", "anthropic")): return "Anthropic"
    if any(x in m for x in ("gemini", "gemma", "google")): return "Google"
    if any(x in m for x in ("llama", "meta")): return "Meta"
    if any(x in m for x in ("mistral", "mixtral")): return "Mistral"
    if any(x in m for x in ("qwen", "alibaba")): return "Alibaba/Qwen"
    if "deepseek" in m: return "DeepSeek"
    if any(x in m for x in ("grok", "xai")): return "xAI"
    return "Other/Unknown"

raw = get(CSV_URL)
text = raw.decode("utf-8-sig", errors="replace")
reader = csv.DictReader(io.StringIO(text))
rows = list(reader)
fields = reader.fieldnames or []

def find_field(names):
    low = {f.lower(): f for f in fields}
    for n in names:
        if n.lower() in low: return low[n.lower()]
    return None

title_f = find_field(["title","name"])
content_f = find_field(["content","prompt","text"])
category_f = find_field(["category","category_name","categoryName"])
type_f = find_field(["type","prompt_type","promptType"])
model_f = find_field(["bestWithModels","best_with_models","models","model","supported_models","supportedModels"])

report = {
    "source": CSV_URL, "csv_bytes": len(raw), "csv_rows": len(rows),
    "columns": fields, "live_api": {}, "counts": {},
    "model_metadata": {}, "quality": {}, "samples": []
}

try:
    api = json.loads(get(API_URL).decode("utf-8"))
    report["live_api"] = {
        "url": API_URL, "total": api.get("total"),
        "page": api.get("page"), "perPage": api.get("perPage"),
        "totalPages": api.get("totalPages"), "status": "ok"
    }
except Exception as e:
    report["live_api"] = {"url": API_URL, "status": "error", "error": str(e)}

for label, f in [("category", category_f), ("type", type_f)]:
    if f:
        vals = Counter((r.get(f) or "").strip() for r in rows)
        vals.pop("", None)
        report["counts"][label] = vals.most_common(100)

models = Counter(); providers = Counter(); model_rows = 0
if model_f:
    for r in rows:
        rawv = (r.get(model_f) or "").strip()
        if not rawv: continue
        model_rows += 1
        parts = re.split(r"[,;|]\s*|\s{2,}", rawv)
        for m in parts:
            m = m.strip(" []\"'")
            if m:
                models[m] += 1
                providers[provider(m)] += 1

report["model_metadata"] = {
    "column": model_f, "rows_with_model_data": model_rows,
    "models": models.most_common(100), "providers": providers.most_common()
}

seen = defaultdict(list); empty_content = 0; word_counts = []; variable_count = Counter()
var_re = re.compile(r"(\$\{[^}]+\}|\{\{[^}]+\}|\[\[[^]]+\]\])")
for i, r in enumerate(rows):
    c = (r.get(content_f) if content_f else "") or ""
    n = norm(c)
    if not n: empty_content += 1
    else: seen[n].append(i)
    variable_count[len(var_re.findall(c))] += 1
    word_counts.append(len(c.split()))

dupes = [v for v in seen.values() if len(v) > 1]
report["quality"] = {
    "empty_content_rows": empty_content,
    "exact_duplicate_groups": len(dupes),
    "rows_in_exact_duplicate_groups": sum(len(x) for x in dupes),
    "variable_count_distribution": variable_count.most_common(),
    "avg_words": round(sum(word_counts)/len(word_counts), 1) if word_counts else 0,
    "min_words": min(word_counts) if word_counts else 0,
    "max_words": max(word_counts) if word_counts else 0
}

for i, r in enumerate(rows[:20]):
    report["samples"].append({
        "row": i + 2,
        "title": (r.get(title_f) or "")[:200] if title_f else None,
        "category": (r.get(category_f) or "")[:100] if category_f else None,
        "type": (r.get(type_f) or "")[:50] if type_f else None,
        "content_preview": re.sub(r"\s+", " ", (r.get(content_f) or ""))[:300] if content_f else None
    })

Path("reports").mkdir(exist_ok=True)
Path("reports/prompt-analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

md = ["# prompts.chat — Prompt Veri Analizi", "",
      f"- CSV satır sayısı: **{len(rows):,}**",
      f"- CSV boyutu: **{len(raw):,} bayt**"]
if report["live_api"].get("status") == "ok":
    md += [f"- Canlı public API toplamı: **{report['live_api'].get('total'):,}**",
           f"- API sayfa sayısı (100/sayfa): **{report['live_api'].get('totalPages'):,}**"]
md += [f"- CSV sütunları: `{', '.join(fields)}`", "", "## Model metadata"]
if model_f:
    md += [f"- Model alanı: `{model_f}`", f"- Model bilgisi bulunan satır: **{model_rows:,}**", "- Sağlayıcı dağılımı:"]
    md += [f"  - {k}: {v:,}" for k,v in providers.most_common()]
else:
    md += ["- CSV snapshot içinde ayrı bir model/provider alanı bulunamadı."]
md += ["", "## Kalite / tekrar kontrolü",
       f"- Boş içerik: **{empty_content:,}**",
       f"- Birebir normalize edilmiş duplicate grubu: **{len(dupes):,}**",
       f"- Duplicate gruplarındaki satır: **{sum(len(x) for x in dupes):,}**",
       f"- Ortalama kelime: **{report['quality']['avg_words']}**",
       f"- Kelime aralığı: **{report['quality']['min_words']}–{report['quality']['max_words']}**",
       "", "## İlk 20 örnek"]
for s in report["samples"]:
    md.append(f"- **{s['title']}** — {s['content_preview']}")
Path("reports/prompt-analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print(json.dumps({"csv_rows":len(rows),"live_api_total":report["live_api"].get("total"),"columns":fields,"model_column":model_f,"duplicate_groups":len(dupes)}, ensure_ascii=False))
