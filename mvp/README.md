# PH Prediction Market News MVP

每日分析菲律宾话题，给预测市场挂单挑选候选。基于 [Schema v1.4](../04_topic_schema_v1.4.md)。

## 快速开始

### 1. 环境

```bash
pip install feedparser pyyaml openpyxl google-generativeai
```

### 2. Mock 模式（无需网络 / API key）

```bash
python run_daily.py --mock
```

跑完生成 `reports/daily_YYYY-MM-DD.xlsx`。用于开发测试和样例展示。

### 3. 真实模式（需要网络）

```bash
python run_daily.py
```

会访问 `news.google.com` 和 `www.reddit.com`。Reddit 有 User-Agent 限速，遇到 429 就放慢。

### 4. 启用 Gemini Flash 评 U 维度（推荐）

免费层：[aistudio.google.com](https://aistudio.google.com/app/apikey) 申请 API key。

```bash
export GEMINI_API_KEY=your_key_here
python run_daily.py
```

只有 R/S/T/H 规则没触发 veto 的话题才会调 LLM，MVP 规模下完全在免费配额内。

## 目录结构

```
mvp/
├── topics/                     # 话题库（每个 yaml 一个话题）
│   ├── ph-fuel-weekly.yaml
│   ├── ph-bsp-rate.yaml
│   ├── ph-south-china-sea.yaml
│   ├── ph-typhoon-season.yaml
│   └── ph-sara-impeachment.yaml
├── fetchers.py                 # Google News + Reddit 抓取（含 mock 数据）
├── scorer.py                   # RSTUH 评分（规则 + LLM）
├── reporter.py                 # Excel 报告生成
├── run_daily.py                # 主入口
└── reports/                    # 每日报告输出（自动生成）
    └── daily_YYYY-MM-DD.xlsx
```

## 加新话题

复制任意一个 `topics/*.yaml` 改字段。关键必填：

- `topic_id`（全局唯一，kebab-case）
- `category`（economy/politics/geopolitics/disaster/social）
- `cadence`（weekly/monthly/one-shot/continuous）
- `queries.google_news.en` 和 `queries.reddit`
- `resolution.primary_source` 和 `resolution.primary_url`
- 至少一个 `market_templates`

放进 `topics/` 自动被加载，无需改代码。

## 每日运行（cron 建议）

Mac/Linux：
```bash
# 每天早上 8:00 PHT 跑
0 8 * * * cd /path/to/mvp && /usr/bin/python3 run_daily.py >> run.log 2>&1
```

也可以挂到 Cowork 的 schedule 里（见 `schedule` 技能）。

## 输出说明

Excel 报告有 6 个 Sheet：

| Sheet | 内容 |
|---|---|
| 0_Summary | 当日话题数量、各档位分布 |
| 1_Top_Picks | 🟢 总分 ≥9 无 veto，立即挂市场 |
| 2_Candidates | 🟡 总分 7-8，人工审核后可挂 |
| 3_Watching | 👀 5-6 或仅 T veto，明日复查 |
| 4_Cooling | ❄️ 已挂市场但热度跌，建议结算 |
| 5_Hot_Digest | 🔥 热度高但被 S/U veto，非市场板块 |

## 当前局限（下一轮迭代项）

- [ ] 话题状态机未实装（ACTIVE/WATCHING/ARCHIVED 转换）
- [ ] 发现管道未实装（自动发现新话题）
- [ ] Bing News 备份源未加
- [ ] Fact-Checker feed 未接入热度信号
- [ ] 反馈回路（市场结果回写）未实装
- [ ] 规范实体表未建立

这些都在 `../04_topic_schema_v1.4.md` 的 Phase 2/3 里，MVP 稳定运行 2 周后再做。

## 故障排查

**Q: Google News 返回 0 条？**
检查 User-Agent 是否被设；部分网络环境需要代理。

**Q: Reddit 429 限速？**
`fetchers.py` 里的 `time.sleep(2)` 可以加长，或换住宅 IP。

**Q: Gemini 429 或配额不足？**
Flash 免费层是 15 req/min, 1500 req/day。MVP 5 话题远在配额内。如超限可：
1. 切换 Anthropic / OpenAI（改 `scorer.classify_with_gemini()`）
2. 用 `--no-llm` 退回纯启发式
