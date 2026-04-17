"""一次性脚本：把手动分析的聚类结果写入 JSON。"""
import json

groups = [
    {
        "name": "PH Fuel & Energy Crisis",
        "name_zh": "菲律宾能源危机",
        "entry_ids": [0,1,13,14,16,29,34,58,68,70,80,99,152,159],
        "density": 14,
        "narrative": (
            "Philippines faces fuel supply crunch as US-Iran tensions disrupt Strait of Hormuz. "
            "DOE monitors weekly rollbacks, Congress debates excise tax suspension, "
            "Maharlika Fund eyes oil depot investment, Manila seeks US waiver to keep Russian oil imports."
        ),
        "R": 2, "R_reason": "DOE weekly bulletin announces exact price changes per liter",
        "S": 2, "S_reason": "DOE official weekly bulletin, BSP, and Palace press releases",
        "T": 2, "T_reason": "Weekly cadence — next bulletin April 22, 2026",
        "U": 2, "U_reason": "Direction and magnitude of rollback genuinely uncertain: oil markets volatile, Iran talks ongoing",
        "H": 2, "H_reason": "14 entries across Top Stories, Nation, Business, World — dominant story of the day",
        "bettable": True,
        "suggested_question": "Will the DOE announce a fuel price rollback exceeding P3/liter for the week of April 22, 2026?",
        "resolution_source": "DOE weekly oil price bulletin",
    },
    {
        "name": "Sara Duterte Impeachment Trial",
        "name_zh": "Sara Duterte弹劾审判",
        "entry_ids": [5,6,8,9,12,74,83],
        "density": 7,
        "narrative": (
            "Senate impeachment proceedings against VP Sara Duterte intensify. "
            "New survey shows majority of Filipinos support trial. "
            "House hearings clarify key allegations; Sara challenges COA findings and denies law school irregularities."
        ),
        "R": 2, "R_reason": "Senate vote or formal scheduling decision is an observable, objective event",
        "S": 2, "S_reason": "Senate official records; Inquirer, Rappler, Philstar cover proceedings live",
        "T": 2, "T_reason": "Marcos allies push for June start; meaningful deadline within ~45 days",
        "U": 2, "U_reason": "Trial timing contested between allies and opposition; outcome uncertain",
        "H": 2, "H_reason": "7 entries from Nation/Top Stories; survey data amplifies public engagement",
        "bettable": True,
        "suggested_question": "Will the Senate formally open Sara Duterte's impeachment trial before June 1, 2026?",
        "resolution_source": "Senate of the Philippines official calendar / press release",
    },
    {
        "name": "PH Inflation Data",
        "name_zh": "菲律宾通胀数据",
        "entry_ids": [17,65,84,104,123,142],
        "density": 6,
        "narrative": (
            "Consumer prices surging as oil shock feeds through to food and transport. "
            "OCBC forecasts BSP rate hike; S&P flags $180B downside risk for PH banks; "
            "Palace economic team scrambling to cushion impact on middle class."
        ),
        "R": 2, "R_reason": "PSA publishes official monthly CPI figure — exact number, unambiguous",
        "S": 2, "S_reason": "Philippine Statistics Authority official release",
        "T": 2, "T_reason": "PSA releases April 2026 inflation data in early May — known schedule",
        "U": 2, "U_reason": "Oil-driven shock makes direction uncertain; economists split on outcome",
        "H": 2, "H_reason": "6 entries spanning expert forecasts, explainers, and banking resilience coverage",
        "bettable": True,
        "suggested_question": "Will PH headline inflation for April 2026 exceed 4.0% year-on-year?",
        "resolution_source": "Philippine Statistics Authority (PSA) monthly CPI release",
    },
    {
        "name": "Metro Manila Transport Strike",
        "name_zh": "交通罢工/学校停课",
        "entry_ids": [3,66,71,76,129],
        "density": 5,
        "narrative": (
            "Transport strike forces school closures until April 17. "
            "DOLE rolls out emergency livelihood programs for jeepney drivers; "
            "House probes ride-hailing commission rates; Angkas cuts rider commission by 2%."
        ),
        "R": 2, "R_reason": "School resumption or continuation of strike is an observable public fact",
        "S": 1, "S_reason": "DepEd announcement expected; multi-agency confirmation",
        "T": 2, "T_reason": "April 17 is the announced deadline — resolution within 24 hours",
        "U": 2, "U_reason": "Strike resolution depends on government concessions not yet announced",
        "H": 2, "H_reason": "5 entries; affects millions of commuters and students in NCR",
        "bettable": True,
        "suggested_question": "Will Metro Manila in-person classes resume as scheduled on April 17, 2026?",
        "resolution_source": "DepEd official advisory / major PH news outlets",
    },
    {
        "name": "BSP Monetary Policy Decision",
        "name_zh": "BSP利率决议",
        "entry_ids": [15,62,103],
        "density": 3,
        "narrative": (
            "BSP faces pressure from surging consumer prices: OCBC economists see rate hike incoming, "
            "BSP plans stricter bank rules for high-value payments, "
            "PSEi flat as market awaits Monetary Board guidance."
        ),
        "R": 2, "R_reason": "BSP Monetary Board announces binary cut/hold/hike decision — fully resolvable",
        "S": 2, "S_reason": "BSP official press conference and statement",
        "T": 2, "T_reason": "Next Monetary Board meeting is a fixed scheduled date",
        "U": 2, "U_reason": "Market split: inflation pushes for hike but growth concerns favor hold",
        "H": 1, "H_reason": "3 entries — moderate but financially sophisticated coverage",
        "bettable": True,
        "suggested_question": "Will BSP raise its benchmark interest rate at its next Monetary Board meeting?",
        "resolution_source": "Bangko Sentral ng Pilipinas official press release",
    },
    {
        "name": "NBA Playoffs",
        "name_zh": "NBA季后赛",
        "entry_ids": [43,44,46,79,90],
        "density": 5,
        "narrative": (
            "NBA play-in and first-round action: Curry leads Warriors comeback over Clippers, "
            "Embiid carries 76ers into playoffs. "
            "Filipino fans closely follow as PH is one of the biggest NBA markets globally."
        ),
        "R": 2, "R_reason": "Game results and series outcomes are fully objective",
        "S": 2, "S_reason": "NBA official standings and game results",
        "T": 2, "T_reason": "Series schedule is known; games in coming days/weeks",
        "U": 2, "U_reason": "Competitive matchups — Warriors vs Clippers genuinely contested",
        "H": 2, "H_reason": "5 entries; PH is one of biggest NBA markets globally, massive audience",
        "bettable": True,
        "suggested_question": "Will the Golden State Warriors win their first-round 2026 NBA Playoff series?",
        "resolution_source": "NBA official website",
    },
    {
        "name": "US-Iran Crisis & Middle East Oil",
        "name_zh": "美伊危机/中东局势",
        "entry_ids": [2,7,87,91,114,157,158],
        "density": 7,
        "narrative": (
            "US begins naval patrols in Strait of Hormuz, shutting down Iran maritime trade. "
            "Trump signals talks could resume for a grand bargain; "
            "oil prices swing on diplomacy signals directly impacting PH fuel costs."
        ),
        "R": 1, "R_reason": "Ceasefire continuation is observable but criteria for holding are fuzzy",
        "S": 2, "S_reason": "Reuters, BBC, AP report official statements from US/Iran governments",
        "T": 1, "T_reason": "Ceasefire has approximate two-week window but no fixed end date",
        "U": 2, "U_reason": "Talks optimistic per some officials but US simultaneously escalating sanctions",
        "H": 2, "H_reason": "7 entries across World, Nation, Business; directly drives PH oil prices",
        "bettable": True,
        "suggested_question": "Will the US and Iran agree to extend their ceasefire beyond April 30, 2026?",
        "resolution_source": "Reuters / BBC international news reporting",
    },
    {
        "name": "South China Sea Territorial Dispute",
        "name_zh": "南海领土争端",
        "entry_ids": [11,28,75],
        "density": 3,
        "narrative": (
            "China moves to block entrance to disputed South China Sea shoal per Reuters satellite imagery. "
            "PH-US Balikatan 2026 exercise kicks off in Tacloban; "
            "Bureau of Immigration probes illegal foreign entry near Subic."
        ),
        "R": 1, "R_reason": "Protest filing is observable but diplomatic response timing is uncertain",
        "S": 2, "S_reason": "DFA official statements; Reuters satellite evidence",
        "T": 1, "T_reason": "No fixed deadline for diplomatic response",
        "U": 2, "U_reason": "PH government response under pressure but timing unpredictable",
        "H": 1, "H_reason": "3 entries; high geopolitical stakes but moderate daily coverage",
        "bettable": True,
        "suggested_question": "Will the Philippines formally file a diplomatic protest over China's blockade of the disputed shoal within 7 days?",
        "resolution_source": "DFA (Department of Foreign Affairs) official statement",
    },
    {
        "name": "Alex Eala Tennis",
        "name_zh": "Alex Eala网球",
        "entry_ids": [45,78],
        "density": 2,
        "narrative": (
            "Filipino tennis star Alex Eala lost at Stuttgart Open but now seeks redemption at Madrid Open. "
            "Filipino community in Germany rallied behind her — she is becoming PH's biggest tennis story."
        ),
        "R": 2, "R_reason": "Match win/loss is objectively determined",
        "S": 2, "S_reason": "WTA official results",
        "T": 2, "T_reason": "Madrid Open draw and schedule published",
        "U": 2, "U_reason": "Playing against top-ranked opponents; outcome genuinely in doubt",
        "H": 1, "H_reason": "2 entries but both 5src/4src; strong Filipino national interest angle",
        "bettable": True,
        "suggested_question": "Will Alex Eala win at least one match at the 2026 Madrid Open?",
        "resolution_source": "WTA Tour official website",
    },
    {
        "name": "Peso-Dollar Exchange Rate",
        "name_zh": "比索汇率",
        "entry_ids": [103,114,124],
        "density": 3,
        "narrative": (
            "Peso weakens as investors await BSP guidance; "
            "dollar drifts amid US-Iran peace talk signals; "
            "currency market in flux tied to both domestic monetary policy and geopolitical risk."
        ),
        "R": 2, "R_reason": "Exchange rate is a precise daily-published figure from BSP and market data",
        "S": 2, "S_reason": "BSP reference rate / Bloomberg / Metrobank",
        "T": 2, "T_reason": "End-of-April deadline is natural and clear",
        "U": 2, "U_reason": "Both BSP rate uncertainty and Middle East risk create genuine uncertainty",
        "H": 1, "H_reason": "3 entries; strong interest among financially-aware PH users",
        "bettable": True,
        "suggested_question": "Will the Philippine peso weaken past PHP 57.00 per USD by April 30, 2026?",
        "resolution_source": "Bangko Sentral ng Pilipinas reference rate",
    },
    {
        "name": "Government Relief & Social Programs",
        "name_zh": "政府社会救助计划",
        "entry_ids": [24,25,26,27,32,66,86,123],
        "density": 8,
        "narrative": (
            "Government mobilizes P60B+ in relief: SSS loan condonation, early pension hike, "
            "DSWD tricycle driver subsidies, P20 rice programs, CHED OFW education support."
        ),
        "R": 1, "R_reason": "Individual program milestones observable but overall success is fuzzy",
        "S": 1, "S_reason": "Multiple agencies, distributed announcements",
        "T": 1, "T_reason": "Rolling implementation, no single deadline",
        "U": 1, "U_reason": "Already announced — question is implementation speed",
        "H": 2, "H_reason": "8 entries; directly affects millions of PH households",
        "bettable": False,
        "suggested_question": None,
        "resolution_source": "",
    },
    {
        "name": "PH Celebrity & Entertainment",
        "name_zh": "名人娱乐/逝者悼念",
        "entry_ids": [39,40,41,42,89,92],
        "density": 6,
        "narrative": (
            "Filipino indie film icon Sue Prado dies at 44; fans mourn Nora Aunor anniversary; "
            "BINI makes Vogue Coachella outfits list; Post Malone PH concert tickets announced."
        ),
        "R": 0, "R_reason": "No bettable outcome — celebrity events are not resolvable markets",
        "S": 0, "S_reason": "N/A",
        "T": 0, "T_reason": "N/A",
        "U": 0, "U_reason": "N/A",
        "H": 2, "H_reason": "6 entries; highest emotional resonance with Filipino general audience",
        "bettable": False,
        "suggested_question": None,
        "resolution_source": "",
    },
    {
        "name": "OFW Remittances",
        "name_zh": "OFW海外汇款",
        "entry_ids": [116,131],
        "density": 2,
        "narrative": (
            "February OFW remittances hit $2.79B; "
            "GCash extends transfer fee waiver for Middle East workers as conflict disrupts payment channels."
        ),
        "R": 2, "R_reason": "BSP publishes exact monthly remittance figure",
        "S": 2, "S_reason": "Bangko Sentral ng Pilipinas official statistical release",
        "T": 2, "T_reason": "March 2026 data due in mid-May; known release schedule",
        "U": 1, "U_reason": "Feb was $2.79B; March likely similar unless Middle East crisis worsens sharply",
        "H": 1, "H_reason": "2 entries; steady topic but not breaking news today",
        "bettable": True,
        "suggested_question": "Will OFW remittances for March 2026 exceed $2.8 billion?",
        "resolution_source": "Bangko Sentral ng Pilipinas monthly remittances report",
    },
]

noise = [
    23,30,35,36,37,38,47,48,49,50,51,52,53,54,57,59,60,
    69,72,73,77,82,85,88,91,93,94,95,96,97,98,100,101,102,
    105,106,107,108,109,110,111,112,113,115,117,118,119,120,
    121,122,125,126,127,128,130,132,133,134,135,136,137,138,
    139,140,141,143,144,145,146,147,148,149,150,151,153,154,155,156
]

result = {
    "clustered_at": "2026-04-16T00:00:00",
    "total_entries": 165,
    "noise_count": len(noise),
    "groups": groups,
    "noise": noise,
}

with open("reports/clusters_2026-04-16.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Saved {len(groups)} groups, {len(noise)} noise entries")
bettable = [g for g in groups if g["bettable"]]
top = [g for g in bettable if g["R"]+g["S"]+g["T"]+g["U"]+g["H"] >= 9]
print(f"Bettable: {len(bettable)}  |  TOP (>=9): {len(top)}")
for g in sorted(bettable, key=lambda x: -(x["R"]+x["S"]+x["T"]+x["U"]+x["H"])):
    total = g["R"]+g["S"]+g["T"]+g["U"]+g["H"]
    print(f"  [{g['density']}] {g['name_zh']} total={total}  {g['suggested_question'][:60]}")
