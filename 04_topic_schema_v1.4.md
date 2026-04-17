# 话题 Schema v1.4 — 定型版

> 累积了前三份设计文档和两个走查案例（油价 + 明星绯闻）之后的话题对象定义。
>
> 这份 schema 是整套系统的数据契约。所有管道（发现/抓取/打分/输出）都按它来读写。

---

## 变更记录

| 版本 | 日期 | 关键变更 | 来源 |
|---|---|---|---|
| v1.0 | 初版 | 话题 = 一行 YAML（查询+类别） | 初步构思 |
| v1.1 | +Reddit | 加 Reddit 讨论量为热度信号 | 用户反馈 |
| v1.2 | +YouTube | 加 YouTube 频道源 | 用户反馈 |
| v1.3 | +RSTUH | 可下注性五维 + 结算源表 + FactChecker | 反思轮① |
| **v1.4** | **本版** | **五项结构性补丁** | **走查轮② 挖掘** |

---

## v1.4 的五项补丁（对照前版）

### 补丁 1：veto_dimensions 改为数组

**来源**：明星绯闻案例里 S 和 U 同时为 0。

```yaml
# 旧：
veto_dimension: "S"        # 单值

# 新：
veto_dimensions: ["S", "U"]  # 数组
```

展示给用户时，每个 veto 维度都要单独给原因，不能合并。

### 补丁 2：disposition 增加 DROP_BUT_DIGEST 档位

**来源**：高热度被 veto 的话题不应浪费，进"今日热议"非市场板块。

```yaml
disposition: TOP | CANDIDATE | WATCH | DROP | DROP_BUT_DIGEST
```

判定规则：`veto_dimensions contains 'S' or 'U'` AND `heat_score >= 0.7` → `DROP_BUT_DIGEST`。

### 补丁 3：加 cadence 字段

**来源**：油价案例暴露"永续话题"现有生命周期覆盖不了。

```yaml
cadence: one-shot | weekly | monthly | quarterly | annual | continuous
```

- `one-shot`：弹劾案、某场选举——有 `expires_at`，结算后进 ARCHIVED
- `weekly`：油价、汇率周度——永续，不走 COOLING→ARCHIVED 路径
- `continuous`：台风季、火山警戒——事件驱动，每次触发派生一个子市场

生命周期状态机按 cadence 分叉：

```
one-shot:    DISCOVERED → WATCHING → ACTIVE → COOLING → ARCHIVED
recurring:   DISCOVERED → WATCHING → ACTIVE ⟲ (永续循环，每周/月重置)
continuous:  DORMANT ⇄ ACTIVE (事件触发激活，结束回休眠)
```

### 补丁 4：market_templates 是数组，不是单对象

**来源**：油价案例派生出 5-8 个子市场。

```yaml
market_templates:
  - id: weekly-diesel-direction
    type: binary
    ...
  - id: weekly-gasoline-magnitude
    type: numeric-bucket
    ...
  - id: monthly-subsidy
    type: binary
    ...
```

一个话题 = 一组市场。这是产品核心——30 个精选话题养 150+ 市场。

### 补丁 5：隐含概率有历史

**来源**：油价 implied_prob 每天会随原油期货变动。

```yaml
bettability:
  U:
    score: 2
    implied_prob: 0.52       # 今日估值
    implied_prob_history:    # 30 天滚动窗口
      - {date: 2026-04-14, prob: 0.48}
      - {date: 2026-04-13, prob: 0.55}
```

用于：趋势图、结算前 momentum 分析、对比竞品赔率。

---

## 完整话题对象 Schema v1.4

```yaml
# ═══════════════════════════════════════════════════
# 身份与分类
# ═══════════════════════════════════════════════════
topic_id: string                     # 全局唯一，kebab-case
topic_name: string                   # 人类可读名称
category: politics | economy | geopolitics | disaster | social | entertainment | sports
subcategory: string
cadence: one-shot | weekly | monthly | quarterly | annual | continuous
language_primary: en | tl | bilingual

# ═══════════════════════════════════════════════════
# 生命周期
# ═══════════════════════════════════════════════════
status: DISCOVERED | WATCHING | ACTIVE | COOLING | ARCHIVED | DORMANT
discovered_by: manual | headline-cluster | entity-surge | calendar | reddit-surge
created_at: ISO8601
last_active_at: ISO8601              # 最近一次热度达标
expires_at: ISO8601 | null           # 只有 one-shot 必填

# ═══════════════════════════════════════════════════
# 发现与抓取
# ═══════════════════════════════════════════════════
queries:
  google_news:
    en: [string]                     # 查询字符串数组
    tl: [string]
  reddit:
    - feed_url: string
      subreddit: string
  factcheck:
    - source: "rappler" | "verafiles" | "tsek"
      filter_keywords: [string]

canonical_entities:                  # 关联的规范实体（防重复话题）
  - entity_id: "person:sara-duterte"
    aliases: ["Sara Duterte", "Inday Sara", "VP Duterte"]

# ═══════════════════════════════════════════════════
# 结算（从 Sheet 8 映射过来）
# ═══════════════════════════════════════════════════
resolution:
  primary_source: string             # 例："Department of Energy (DOE)"
  primary_url: string
  secondary_sources: [string]
  publication_schedule: string
  dispute_risk: low | medium | high
  dispute_notes: string

# ═══════════════════════════════════════════════════
# 可下注性评分（由分类器每日更新）
# ═══════════════════════════════════════════════════
bettability:
  R: {score: 0|1|2, reason: string}
  S: {score: 0|1|2, reason: string, proposed_source: string}
  T: {score: 0|1|2, reason: string, proposed_deadline: ISO8601}
  U:
    score: 0|1|2
    reason: string
    implied_prob: float              # 0.0-1.0
    implied_prob_history:            # 30 天滚动
      - {date: ISO8601, prob: float}
  H: {score: 0|1|2, reason: string}
  total: integer                     # 0-10
  veto_dimensions: [string]          # 可为空数组
  disposition: TOP | CANDIDATE | WATCH | DROP | DROP_BUT_DIGEST
  last_scored_at: ISO8601

# ═══════════════════════════════════════════════════
# 热度信号（每日抓取后更新，30 天滚动）
# ═══════════════════════════════════════════════════
heat_history:
  - date: ISO8601
    google_news_24h: integer
    google_news_7d: integer
    momentum_ratio: float            # 24h / (7d/7)
    reddit_posts_24h: integer
    reddit_top_upvotes: integer
    factcheck_mentions_7d: integer
    source_diversity: integer        # 独立媒体数
    bilingual_hot: boolean
    heat_score: float                # 0.0-1.0 综合分

# ═══════════════════════════════════════════════════
# 派生市场（一个话题多个市场）
# ═══════════════════════════════════════════════════
market_templates:
  - template_id: string
    type: binary | numeric-bucket | multi-outcome | scalar
    question_template: string        # 带 {placeholder}
    resolution_rule: string          # 给结算员的明确指令
    buckets: [string]                # 仅 numeric-bucket
    cadence: matches parent.cadence or subset
    submit_deadline: string
    resolve_deadline: string
    min_liquidity_required: float    # USD, 挂市场的门槛
    historical_baseline:             # 基础概率参考（防 U=0）
      source: string
      frequency: float

# ═══════════════════════════════════════════════════
# 跨话题关联
# ═══════════════════════════════════════════════════
related_topics: [topic_id]

# ═══════════════════════════════════════════════════
# 反馈回路（市场结算后回写）
# ═══════════════════════════════════════════════════
market_outcomes: [market_outcome_id] # 指向 market_outcomes.csv 的行
```

---

## 系统输出规则（更新）

### 每日报告四区 + 一个侧边栏

```
┌──────────────────────────────────────────────────────┐
│ 🟢 TOP PICKS                                          │
│    (total ≥ 9 AND veto_dimensions = [])              │
├──────────────────────────────────────────────────────┤
│ 🟡 CANDIDATES                                         │
│    (7 ≤ total ≤ 8 AND veto_dimensions = [])          │
├──────────────────────────────────────────────────────┤
│ 👀 WATCHING                                           │
│    (5-6 OR total ≥ 7 with only T veto)               │
├──────────────────────────────────────────────────────┤
│ ❄️ COOLING                                            │
│    (已挂市场但 heat_score 跌破阈值)                  │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🔥 Hot Digest (非市场，导流用)                       │
│    (DROP_BUT_DIGEST: veto 但 heat_score ≥ 0.7)       │
└──────────────────────────────────────────────────────┘
```

### Excel 每日文件命名与结构

```
daily_YYYY-MM-DD.xlsx
├─ 0_Summary         # 一页总览，指标 + 今日变化
├─ 1_Top_Picks       # TOP 档，每条一行
├─ 2_Candidates      # CANDIDATE 档
├─ 3_Watching        # WATCH 档 + 新发现待审
├─ 4_Cooling         # 建议结算的已挂市场
└─ 5_Hot_Digest      # DROP_BUT_DIGEST，非市场
```

---

## 分类器调用（完整 prompt 结构）

```
[SYSTEM]
你是预测市场话题可下注性评估员。遵循 RSTUH 五维度打分。
严格使用以下 few-shot examples 作为校准：
{{classifier_calibration_examples.json 内容}}

规则：
- 任一维度 = 0 → veto_dimensions 包含该维度
- S=0 或 U=0 且 heat_score ≥ 0.7 → DROP_BUT_DIGEST
- 其他 veto → 按 disposition_mapping 决定

[USER]
评估以下话题：
topic_id: ...
topic_description: ...
raw_signals: {{今日抓取数据}}
related_canonical_entities: {{从 entity registry 拉取}}

输出严格 JSON，按 examples 的结构。
```

---

## 下一步建议优先级

schema 定型了，可以开始码真东西。推荐顺序：

1. **MVP 最小可运行版本**
   - 手动写 5 个话题的初始 YAML（含油价、BSP 利率、南海冲突、台风、Sara 弹劾）
   - 写一个 Python 脚本：对每个话题跑 Google News + Reddit 抓取
   - 跑一次分类器（用 Anthropic API + classifier_calibration_examples.json）
   - 输出 daily_YYYY-MM-DD.xlsx

2. **MVP 跑通后 2 周内**
   - 接入 Fact-Checker feeds
   - 实现话题状态机（状态转移规则）
   - 加发现管道（headline-cluster）

3. **MVP 稳定后 1 月内**
   - 规范实体表 (canonical entity registry)
   - Bing News 备份源
   - 反馈回路（市场结果回写）

这三步走完，工具就从"文档"变成"产品"了。
