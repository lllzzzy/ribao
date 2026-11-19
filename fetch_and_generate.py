import os
import json
import time
import hashlib
import re
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from openai import OpenAI

# ================= 配置区 =================
# 优先读取 GitHub Actions Secrets 环境变量，如未设置则使用默认配置
API_KEY = os.environ.get("LLM_API_KEY", "sk-9938bd4276d64fba9d2ee59096f32c03")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.environ.get("LLM_MODEL", "deepseek-chat")

OUTPUT_FILE = "data/articles.json"
MAX_ARTICLES_POOL = 300  # 云端文章池最大保留篇数
BATCH_COUNT = 15         # 每次生成的深度长文篇数

# 5大核心分类领域（与前端 Tab 强对齐）
VALID_DOMAINS = ["社会热点", "科技产业", "历史纵深", "设计与文化", "游戏机制"]

# 公共 RSSHub 镜像列表（多节点轮询重试）
RSSHUB_MIRRORS = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://hub.slarker.me",
    "https://rsshub.monika.love"
]

# 信源列表
SOURCES = [
    {"name": "微博热搜", "path": "/weibo/search/hot"},
    {"name": "知乎热榜", "path": "/zhihu/hot"},
    {"name": "央视要闻", "path": "/cctv/world"},
    {"name": "人民网社会", "path": "/people/society"},
    {"name": "小黑盒热门", "path": "/xiaoheihe/news"}
]

# 备用种子话题库（防止所有公共 RSSHub 节点瞬时超时或被墙时生成流程中断）
FALLBACK_TOPICS = [
    {"source": "科技产业", "title": "全球半导体先进制程竞争白热化与封装产能瓶颈", "summary": "先进制程与先进封装成为各大芯片巨头角逐焦点，产业链上下游投资与供需结构发生深刻变革。"},
    {"source": "社会热点", "title": "一线城市青年租赁消费向市郊轨道节点迁移趋势", "summary": "随着生活节奏与职住平衡诉求变化，年轻人开始从核心商圈向远郊地铁沿线品质社区扩散。"},
    {"source": "游戏机制", "title": "自走棋与卡牌构筑玩法在跨平台新作中的数值融合", "summary": "现代独立游戏将轻度概率博弈与强数值连携机制相结合，创造出粘性极高的单局循环体验。"},
    {"source": "设计与文化", "title": "物理实体按键在当代数码汽车与家电界面的再回归", "summary": "触控屏泛滥后的盲操安全隐患与质感缺失，促使顶尖工业设计师重新探索物理机械旋钮的触觉价值。"},
    {"source": "历史纵深", "title": "十九世纪末城市下水道体系建设与公共卫生秩序重构", "summary": "近代大都市在霍乱肆虐背景下启动巨型地下管网工程，推动现代城市公共治理制度的确立。"},
    {"source": "科技产业", "title": "生成式大模型在企业内部工作流落地中的幻觉控制难题", "summary": "通用大模型进入垂直工业与金融场景面临准确性门槛，检索增强生成与本地微调方案成为主流探索。"},
    {"source": "社会热点", "title": "近郊徒步与城市微度假对传统周末商业街区的客流重构", "summary": "年轻一代周末出游半径发生变化，轻量户外装备与露营经济持续重塑城郊商业形态。"},
    {"source": "游戏机制", "title": "硬核生存游戏中的资源惩罚机制与沉没成本心理", "summary": "死亡全掉落与不可逆存档机制如何通过放大挫败感与危机感，构建出极致的沉浸体验。"}
]
# ==========================================

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
CST = timezone(timedelta(hours=8))


def fetch_raw_topics():
    """从多个信源抓取最新热点话题标题与简介"""
    collected = []
    for src in SOURCES:
        fetched = False
        for mirror in RSSHUB_MIRRORS:
            url = f"{mirror}{src['path']}"
            try:
                resp = requests.get(
                    url,
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                if resp.status_code == 200 and resp.text.strip():
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries[:8]:
                        title = entry.get("title", "").strip()
                        summary = entry.get("summary", "").strip()
                        summary = re.sub(r"<[^>]+>", "", summary)[:200]
                        if title and len(title) >= 4:
                            collected.append({
                                "source": src["name"],
                                "title": title,
                                "summary": summary
                            })
                    if feed.entries:
                        fetched = True
                        break
            except Exception:
                continue
        if not fetched:
            print(f"[提示] 信源 {src['name']} 暂时无法通过镜像连接，已尝试下一个")

    if len(collected) < 6:
        print("[备用方案] 外部 RSS 抓取条数偏少，混合注入通用深度研判话题库")
        collected.extend(FALLBACK_TOPICS)

    return collected


def load_existing_articles():
    """读取历史已生成的文章库，用于去重和增量追加"""
    if not os.path.exists(OUTPUT_FILE):
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[警告] 读取历史文章库失败: {e}")
        return []


def call_deepseek_batch(topics_text, recent_titles_text, domain_plan, batch_num, total_batches):
    domain_req_text = "、".join([f"{k}（{v}篇）" for k, v in domain_plan.items()])
    target_count = sum(domain_plan.values())

    system_prompt = f"""你是一位顶级深度调查报道主编。你的任务是从多平台实时热点与时代切面中，挑选出极具社会切面、纵深感和讨论价值的话题，撰写高密度的跨领域深度新闻长文。

你必须严格遵守以下不可违背的铁律：
1. 本批次恰好输出 {target_count} 篇深度报道，领域严格按照分配要求：{domain_req_text}。
2. domain 字段必须严格为指定的 5 大类之一（社会热点 / 科技产业 / 历史纵深 / 设计与文化 / 游戏机制），严禁自行创造大类！category 为更微观的具体切面标签（如：高带宽存储周期 / 独立游戏概率构筑 / 县域商业毛细血管 等）。
3. 【字数扩充铁律】：每篇文章必须由 4 到 5 个扎实充实的自然中文段落组成，总字数严格控制在 1050 到 1350 字之间（每段约 250~320 字）。
   - 第1段：现实切面与事件背景纵深，勾勒宏观场景（约250字）。
   - 第2段：底层因果机制、产业链与商业利益/社会结构深度拆解（约280字）。
   - 第3段：多方博弈冲突、深层张力与次生连锁反应（约280字）。
   - 第4/5段：长远制度变迁、行业生态重构与克制冷峻的现实思考（约280字）。
4. 绝对禁止在正文中出现任何小标题、加粗引导词、编号（1. 2. 3.）或分点符号（• / -）。
5. 绝对禁止使用“综上所述”、“总而言之”、“值得注意的是”、“引发了广泛关注”等模板化 AI 总结腔，不提及平台名称，直接以沉稳克制、透彻扎实的客观深度报道口吻叙事。
6. 标题长度严格控制在 18 到 28 个汉字之间，克制、精炼、信息量充实。
7. 严格以合法的 JSON 对象格式输出，格式如下：
{{
  "articles": [
    {{
      "domain": "指定的领域名称",
      "category": "细分切面标签",
      "title": "克制有信息量的长文标题（18-28字）",
      "paragraphs": [
        "第一段正文（约250字）...",
        "第二段正文（约280字）...",
        "第三段正文（约280字）...",
        "第四段正文（约280字）..."
      ]
    }}
  ]
}} """

    user_prompt = f"""以下是实时抓取到的热点与时代话题素材：
{topics_text}

以下是近期已发布过的标题（请务必避开重复选题）：
{recent_titles_text}

请现在精心撰写第 {batch_num}/{total_batches} 批次深度报道（本批次共 {target_count} 篇，严格按照领域：{domain_req_text}，每篇严格1050~1350字），返回标准 JSON。"""

    print(f"   [批次 {batch_num}/{total_batches}] 正在调用 DeepSeek 撰写 {target_count} 篇千字深度报道（{domain_req_text}）...")
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=8192
    )

    raw_content = response.choices[0].message.content.strip()
    if raw_content.startswith("```"):
        lines = raw_content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw_content = "\n".join(lines).strip()

    result = json.loads(raw_content)
    return result.get("articles", [])


def generate_long_articles(raw_topics, existing_titles):
    """分批次调用 DeepSeek 撰写扩充版千字深度长文，规避单次 Token 上限"""
    topics_text = "\n".join(
        [f"- [{t['source']}] {t['title']}：{t.get('summary', '')}" for t in raw_topics[:35]]
    )
    recent_titles_text = "\n".join(existing_titles[:50])

    all_articles = []

    # 批次 1：8 篇（社会热点 3 篇、科技产业 3 篇、历史纵深 2 篇）
    plan_1 = {"社会热点": 3, "科技产业": 3, "历史纵深": 2}
    try:
        b1 = call_deepseek_batch(topics_text, recent_titles_text, plan_1, 1, 2)
        all_articles.extend(b1)
    except Exception as e:
        print(f"   [错误] 批次 1 生成失败: {e}")

    # 批次 2：7 篇（历史纵深 1 篇、设计与文化 3 篇、游戏机制 3 篇）
    plan_2 = {"历史纵深": 1, "设计与文化": 3, "游戏机制": 3}
    try:
        # 将批次 1 生成的标题也加入去重列表
        b1_titles = [a.get("title", "") for a in all_articles if a.get("title")]
        extended_recent = "\n".join(b1_titles + existing_titles[:40])
        b2 = call_deepseek_batch(topics_text, extended_recent, plan_2, 2, 2)
        all_articles.extend(b2)
    except Exception as e:
        print(f"   [错误] 批次 2 生成失败: {e}")

    return all_articles


def sanitize_article(item, now_str):
    """清洗单篇文章数据，确保与前端渲染格式完全兼容"""
    domain = item.get("domain", "").strip()
    if domain not in VALID_DOMAINS:
        # 兜底映射
        domain = "社会热点"
        for v in VALID_DOMAINS:
            if v in str(item):
                domain = v
                break

    category = item.get("category", "深度观察").strip()
    title = item.get("title", "").strip()
    paragraphs = [p.strip() for p in item.get("paragraphs", []) if p.strip()]

    if len(paragraphs) < 3 or len(title) < 6:
        return None

    uid = hashlib.md5(title.encode("utf-8")).hexdigest()[:12]

    return {
        "id": f"live_{uid}",
        "domain": domain,
        "category": category,
        "title": title,
        "publishedAt": now_str,
        "paragraphs": paragraphs
    }


def main():
    print("=" * 50)
    print("《日报》后端自动化抓取与 DeepSeek 深度撰写引擎启动")
    print(f"当前时间 (CST): {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print("1. 正在抓取多平台实时热点素材...")
    raw_topics = fetch_raw_topics()
    print(f"   采集到有效素材: {len(raw_topics)} 条")

    existing_articles = load_existing_articles()
    existing_titles = [a.get("title", "") for a in existing_articles]
    print(f"   已载入历史文章库: {len(existing_articles)} 篇")

    print("2. 调用 DeepSeek API 生成 15 篇深度长文...")
    try:
        new_items = generate_long_articles(raw_topics, existing_titles)
    except Exception as e:
        print(f"[错误] DeepSeek 生成失败: {e}")
        return

    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    formatted_new = []
    for item in new_items:
        clean_art = sanitize_article(item, now_str)
        if clean_art:
            formatted_new.append(clean_art)

    print(f"   成功生成并格式化: {len(formatted_new)} 篇深度报道")

    if not formatted_new:
        print("[警告] 本次没有有效文章生成，退出")
        return

    # 3. 增量合并与去重，新文章排在最前
    seen_ids = set()
    seen_titles = set()
    merged = []

    for art in formatted_new:
        if art["id"] not in seen_ids and art["title"] not in seen_titles:
            seen_ids.add(art["id"])
            seen_titles.add(art["title"])
            merged.append(art)

    for art in existing_articles:
        art_id = art.get("id")
        art_title = art.get("title")
        if art_id and art_id not in seen_ids and art_title not in seen_titles:
            seen_ids.add(art_id)
            seen_titles.add(art_title)
            # 兼容历史数据补充 domain
            if "domain" not in art:
                art["domain"] = art.get("category", "社会热点")
            merged.append(art)

    # 截取最大池容量
    merged = merged[:MAX_ARTICLES_POOL]

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"3. 写入完成！已保存至 {OUTPUT_FILE}")
    print(f"   文章池最新总数: {len(merged)} 篇（本次新增: {len(formatted_new)} 篇）")
    print("=" * 50)


if __name__ == "__main__":
    main()
