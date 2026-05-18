"""Region configuration for the prediction-market news pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionConfig:
    slug: str
    site_name: str
    flag: str
    country_code: str
    language_code: str
    locale: str
    country_name: str
    country_adjective: str
    country_label_en: str
    country_name_zh: str
    timezone_label: str
    feeds: dict[str, str]

    @property
    def reports_subdir(self) -> str:
        return "" if self.slug == "ph" else self.slug


_PH_TOPIC_BASE = "https://news.google.com/rss/topics"


REGIONS: dict[str, RegionConfig] = {
    "ph": RegionConfig(
        slug="ph",
        site_name="PHNews",
        flag="🇵🇭",
        country_code="PH",
        language_code="en",
        locale="en-PH",
        country_name="the Philippines",
        country_adjective="Philippine",
        country_label_en="Philippines",
        country_name_zh="菲律宾",
        timezone_label="PHT",
        feeds={
            "Top Stories": "https://news.google.com/rss?gl=PH&hl=en-PH&ceid=PH:en",
            "Nation": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFZxYUdjU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
            "Business": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
            "World": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=PH&hl=en-PH&ceid=PH:en",
        },
    ),
    "id": RegionConfig(
        slug="id",
        site_name="IDNews",
        flag="🇮🇩",
        country_code="ID",
        language_code="id",
        locale="id",
        country_name="Indonesia",
        country_adjective="Indonesian",
        country_label_en="Indonesia",
        country_name_zh="印尼",
        timezone_label="WIB",
        feeds={
            "Top Stories": "https://news.google.com/rss?gl=ID&hl=id&ceid=ID:id",
            "Nation": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFZxYUdjU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=ID&hl=id&ceid=ID:id",
            "Business": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=ID&hl=id&ceid=ID:id",
            "World": f"{_PH_TOPIC_BASE}/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKUVNDZ0FQAQ?gl=ID&hl=id&ceid=ID:id",
        },
    ),
}


def get_region(slug: str | None) -> RegionConfig:
    key = (slug or "ph").lower()
    try:
        return REGIONS[key]
    except KeyError as exc:
        valid = ", ".join(sorted(REGIONS))
        raise ValueError(f"unknown region '{slug}'. Valid regions: {valid}") from exc


def reports_dir(base_reports_dir: str, region: RegionConfig):
    from pathlib import Path

    path = Path(base_reports_dir)
    if region.reports_subdir:
        path = path / region.reports_subdir
    return path
