# 工作案例：菲律宾油价话题全流程走查

> 目的：把前几版设计的所有组件（话题对象、发现管道、查询、热度评分、可下注性分类、结算源、市场题目）在一个真实话题上跑一遍。
>
> 这份文档既是演示，也是**未来写 bettable_topics.yaml 时的填写模板**。

---

## 为什么选"菲律宾油价"做第一个案例

这是菲律宾预测市场的"五星级"标的，五维度全部满分：

- **R**（可判定）：DOE（能源部）每周公布精确到小数点后两位的泵价
- **S**（结算源）：DOE 官网 + 各大油企（Petron/Shell/Caltex 等）公告，三源交叉
- **T**（时间节点）：每周一下午 DOE 公告，周二凌晨生效——**每周一个结算点**
- **U**（结果不确定）：方向基本 50/50，涨跌幅度更难猜
- **H**（热度）：菲律宾 jeepney 司机 + tricycle 司机 + OFW 汇款家庭全关注。每次油价公告 Facebook 刷屏、Reddit r/Philippines 必有热帖

外加一个产品优势：**高频 + 永续**。每周一个结算点意味着用户养成定期下注习惯，市场永远不缺标的。这是其他话题（弹劾案、选举）没有的优势。

---

## Step 1 — 话题对象定义

```yaml
topic_id: ph-fuel-weekly-2026

# ——— 分类 / 生命周期 ———
status: ACTIVE
category: economy
subcategory: energy-prices
discovered_by: manual          # manual / headline-cluster / entity-surge / calendar
created_at: 2026-04-15
expires_at: null               # 永续话题，不设截止；个别子市场才有

# ——— 发现与抓取 ———
queries:
  en:
    - '"fuel price" Philippines (rollback OR hike) when:7d'
    - 'diesel pump price Philippines DOE when:7d'
    - '"oil price" Philippines when:24h'
  tl:
    - 'presyo ng gasolina (taas OR baba) when:7d'
    - 'diesel rollback Pilipinas when:7d'
  reddit:
    - 'https://www.reddit.com/r/Philippines/search/.rss?q=fuel+price+OR+gasoline+OR+diesel&restrict_sr=on&sort=new'
    - 'https://www.reddit.com/r/phinvest/search/.rss?q=oil+OR+fuel&restrict_sr=on&sort=new'
  factcheck:
    - 'https://www.rappler.com/newsbreak/fact-check/feed/'   # 过滤含 "fuel"/"gas" 的条目

# ——— 结算 ———
resolution:
  primary_source: "Department of Energy (DOE) - Weekly Oil Price Monitoring"
  primary_url: "https://www.doe.gov.ph/energy-statistics/oil-monitor"
  secondary_sources:
    - "Petron Corp official pump price advisory"
    - "Pilipinas Shell official pump price advisory"
  publication_schedule: "DOE 公告每周一 15:00 左右；生效每周二 00:01"
  dispute_risk: low
  dispute_notes: "DOE 数据与各油企有 0.01-0.05 PHP/L 微小差异，挂市场时需预先指定口径（建议用 DOE 周报的中位价）"

# ——— 可下注性分数（由分类器生成）———
bettability:
  R: 2     # 精确到小数点的数值
  S: 2     # DOE 是法定唯一来源
  T: 2     # 每周一个锚点
  U: 2     # 方向 + 幅度都不确定
  H: 2     # 菲律宾普通人最关心的数字之一
  total: 10
  disposition: TOP
  veto_dimension: null
  last_scored_at: 2026-04-15

# ——— 热度信号（30 天滚动）———
heat_history: []   # 每日 cron 填充

# ——— 相关话题 ———
related_topics:
  - ph-php-usd-weekly       # 汇率直接影响进口成本
  - ph-inflation-monthly    # 油价是 CPI 重要权重
  - ph-transport-strike     # 油价暴涨常诱发交通罢工

# ——— 市场模板（一个话题可派生多个市场）———
market_templates:
  - id: weekly-diesel-direction
    type: binary
    question_template: "Will Philippine pump diesel prices see a NET INCREASE (hike > rollback) in the week of {week_start}?"
    resolution_rule: "Resolved YES if DOE's 'Common Pump Price Monitoring' shows net change > 0 PHP/L for diesel (Metro Manila average) for the week ending {week_end}. Source: DOE weekly bulletin."
    cadence: weekly
    submit_deadline: "每周日 23:59 PHT"
    resolve_deadline: "每周二 06:00 PHT"

  - id: weekly-gasoline-magnitude
    type: numeric-bucket
    question_template: "What will be the net change in Metro Manila RON95 gasoline pump price for the week of {week_start}?"
    buckets: ["< -1.0", "-1.0 to -0.3", "-0.3 to +0.3", "+0.3 to +1.0", "> +1.0"]  # PHP/L
    resolution_rule: "同上，但针对 RON95 汽油"
    cadence: weekly

  - id: monthly-subsidy-announcement
    type: binary
    question_template: "Will the DOE/DSWD announce a new fuel subsidy program for {month}?"
    resolution_rule: "Official announcement from DOE OR DSWD before month end"
    cadence: monthly
```

---

## Step 2 — 发现管道怎么找到这个话题

**手动添加**（本次演示）：直接挂进 ACTIVE。

假设是**自动发现**，路径会是：

1. `headline-cluster` 管道：连续抓到 5 篇以上标题含 "fuel price" / "rollback" / "diesel hike" 的文章没匹配到任何现存话题 → 进候选池
2. LLM 聚类：把这些标题喂给 LLM，它会说"这是关于菲律宾每周油价调整的话题"，自动生成上面的 queries 骨架
3. 人工审批（模式 B）：你看到候选池里这条，秒批，进 ACTIVE

---

## Step 3 — 模拟一天的抓取与打分

**假设今天是 2026-04-15（周三）**，cron 跑的结果（数字是示意）：

### 3.1 Google News 查询

| 查询 | 24h 返回 | 7d 返回 | 动量比 | 主要媒体 |
|---|---|---|---|---|
| `"fuel price" Philippines when:24h` | 12 篇 | 38 篇 | 0.32 | Inquirer, Rappler, BusinessWorld, Philstar, GMA |
| `diesel pump price Philippines DOE` | 8 篇 | 22 篇 | 0.36 | 同上 + PNA（官媒） |
| `presyo ng gasolina Pilipinas` | 5 篇 | 14 篇 | 0.36 | Bandera, Abante, Tagalog 版 |

**解读**：动量 ~0.35 意味着"平稳发酵中"——不是爆炸性事件，但每天都有报道。典型的周期性话题形态。

### 3.2 Reddit

- r/Philippines 近 24h 相关帖：**3 帖**，最高 847 赞（一条关于 jeepney 司机抗议的帖子）
- r/phinvest 近 24h：**1 帖**，讨论油价对 PSEi 能源股影响，220 赞
- r/Philippines_Expats：**2 帖**，OFW 家属抱怨家用成本

### 3.3 Fact-Checker 信号

- Rappler Fact Check 本周辟谣 1 条："假的油价回落通知书"在 FB 广传 → **极强 FB 热度信号**（骗子只会仿冒最多人关心的东西）
- VERA Files 无相关

### 3.4 综合 heat_score

```
heat_components:
  google_news_24h: 25 (合计三条查询去重后)
  reddit_24h_upvotes: 1289
  factcheck_mentions: 1 (Rappler)
  momentum_7d: 0.34 (24h/7d 平均)
  multi_source_media: 7 家不同媒体
  bilingual: True (英文+Tagalog 都有热度)

heat_score = 0.88   # 高
```

---

## Step 4 — 可下注性分类器输出

```json
{
  "topic_id": "ph-fuel-weekly-2026",
  "scored_at": "2026-04-15T08:00:00+08:00",
  "R": {
    "score": 2,
    "reason": "DOE publishes exact peso/liter figures; verifiable via official bulletin"
  },
  "S": {
    "score": 2,
    "reason": "DOE is the sole authoritative source under Philippine Oil Deregulation Law; oil companies cross-verify",
    "proposed_source": "DOE Weekly Oil Price Monitoring Bulletin"
  },
  "T": {
    "score": 2,
    "reason": "Weekly cycle; every Tuesday implementation",
    "proposed_deadline": "next Tuesday 00:01 PHT"
  },
  "U": {
    "score": 2,
    "reason": "Both direction and magnitude show weekly variance; no clear prior favorite",
    "implied_prob_hike": 0.52
  },
  "H": {
    "score": 2,
    "reason": "Multi-source coverage, Reddit engagement, fact-check disinfo activity = public attention high"
  },
  "total": 10,
  "veto_dimension": null,
  "disposition": "TOP",
  "suggested_market_question": "Will Philippine pump diesel prices see a net INCREASE in the week of Apr 21, 2026?",
  "market_template_match": "weekly-diesel-direction"
}
```

---

## Step 5 — 进每日报告长什么样

在 Excel 的 `TOP PICKS` 区，这个话题的一行：

| 字段 | 值 |
|---|---|
| 排名 | #3 |
| 话题 | 菲律宾油价周调整 |
| 市场建议 | Will PH diesel prices see a NET INCREASE in the week of Apr 21? |
| 类型 | Binary (Yes/No) |
| 结算源 | DOE Weekly Oil Price Monitoring Bulletin |
| 结算时间 | 2026-04-22 06:00 PHT |
| R/S/T/U/H | 2/2/2/2/2 = 10 |
| 24h 热度 | 25 篇新闻, 1,289 Reddit 赞, 1 FB 辟谣 |
| 动量 | 平稳 (0.34) |
| 相关新闻 Top 3 | [链接] [链接] [链接] |
| 当前隐含概率 | 52% Hike / 48% Rollback |
| 操作按钮 | [挂市场] [加入观察] [暂缓] |

---

## Step 6 — 一周后验证闭环

**假设你在 04-15 挂了这个市场，04-22 DOE 公告**：

- 实际结果：diesel 净涨 0.85 PHP/L → YES 胜出
- 市场数据：24h 交易量 $2,400、78 笔订单、最终赔率稳定在 54-46
- 结算：自动从 DOE 官网抓数据，**无争议**

写入 `market_outcomes.csv`：
```
topic_id,market_id,opened_at,resolved_at,volume_usd,n_trades,final_odds_yes,outcome,dispute_count
ph-fuel-weekly-2026,weekly-diesel-direction-0421,2026-04-15,2026-04-22,2400,78,0.54,YES,0
```

**下周重复**，换 week_start 参数即可。永续话题只需维护一次。

---

## Step 7 — 这个话题派生的其他市场机会

一个好话题能养活多个市场。除了上面的 `weekly-diesel-direction`：

1. **幅度市场**（numeric-bucket）：下周变化在哪个区间
2. **月度累计**：4 月累计净涨跌
3. **交叉品类**：汽油 vs 柴油哪个涨幅大
4. **政策响应**：下个月是否新增燃油补贴（DSWD Pantawid Pasada）
5. **极端事件**：周涨幅是否 > 3 PHP/L（绑定 OPEC 会议、中东冲突）

光油价一条话题线，可以同时挂 5-8 个不同市场，覆盖不同风险偏好的用户。

---

## Step 8 — 反思：这个案例暴露的系统问题

走一遍发现三个之前没想到的细节：

1. **永续话题需要特殊支持**：之前的生命周期模型（ACTIVE → COOLING → ARCHIVED）是给一次性事件设计的。油价这类 rolling topic 永远不会 COOLING——每周重置。需要给话题对象加 `cadence: one-shot | weekly | monthly | quarterly` 字段，生命周期规则按此分叉。

2. **隐含概率要持续更新**：U 维度的 `implied_prob` 不是一次性填的，应该每天重新估算。油价下周涨的概率会随原油期货实时变化。需要一个 `implied_prob_history` 字段。

3. **市场模板是话题的下级对象**：一个话题派生多个市场（见 Step 7），每个市场独立挂载和结算。数据结构要从"话题 = 市场"变成"话题包含多个市场模板"——这个上面的 yaml 我已经体现了，但之前几版设计没明确。

这三点是今天这轮走查的增量发现。后续加到话题 schema 里。

---

## 下一步可选

- A. 把 Step 8 的三点增补写进话题 schema，更新 v1.4
- B. 再跑一个**对比案例**——选一个"看起来火但可下注性差"的话题（比如某明星八卦），展示分类器会怎么 veto 它，强化判断力
- C. 写一段 Python 伪代码，把这个案例的打分流程实装
