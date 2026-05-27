"""Angle plugin registry.

Each market-question angle lives in its own module here. The orchestration
in cluster.cluster_with_llm() picks them up via the lists below.

Adding a new angle:
1. Drop a new file in mvp/angles/, defining a class with a `name`
   attribute and a `generate(groups, client, model, region_cfg)` method.
2. Add an instance to either PHASE_1_ANGLES (runs before region guard /
   cluster attachment; affects disposition) or PHASE_2_ANGLES (runs after,
   reads from group["clusters"]).

That's it -- cluster.py and gen_html.py don't need changes to surface the
new angle in JSON. Rendering a new angle as a card slot requires a CSS +
template addition in gen_html.py.
"""
from __future__ import annotations

from .serious import SeriousAngle
from .reddit import RedditAngle
from .tiktok import TikTokAngle


# Phase 1: runs BEFORE region guard / cluster attach. Required for any angle
# whose output drives disposition or other orchestration. Today: just serious.
PHASE_1_ANGLES = [SeriousAngle()]

# Phase 2: runs AFTER groups have clusters[] attached. Reads cluster_title /
# summary / keywords. Today: reddit + tiktok.
PHASE_2_ANGLES = [RedditAngle(), TikTokAngle()]

ALL_ANGLES = PHASE_1_ANGLES + PHASE_2_ANGLES
