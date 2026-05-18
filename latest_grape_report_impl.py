from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener


BASE_URL = "https://min-repo.com"
JST = timezone(timedelta(hours=9))
REPLAY_DENOM = 7.298
WEEKDAY_INDEX = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    display: str
    big_payout: int
    reg_payout: int
    grape_denoms: tuple[float, float, float, float, float, float]
    cherry_denom: float
    bell_denom: float
    pierrot_denom: float
    cherry_payout: int = 2


MODEL_SPECS = (
    ModelSpec("マイジャグラー", "マイジャグラーV", 240, 96, (5.910, 5.870, 5.830, 5.800, 5.760, 5.670), 34.657, 1024.0, 1024.0),
    ModelSpec("ネオアイム", "ネオアイムジャグラーEX", 252, 96, (6.024, 6.020, 6.016, 6.012, 6.008, 5.848), 35.617, 1092.267, 1092.267),
    ModelSpec("アイムジャグラー", "アイムジャグラーEX", 252, 96, (6.024, 6.020, 6.016, 6.012, 6.008, 5.848), 35.617, 1092.267, 1092.267),
    ModelSpec("ゴーゴージャグラー", "ゴーゴージャグラー3", 240, 96, (6.2499, 6.2002, 6.1502, 6.0698, 5.9998, 5.9201), 33.20, 1092.267, 1092.267),
    ModelSpec("ファンキー", "��ァンキージャグラー2", 240, 96, (5.94, 5.9298, 5.8798, 5.8301, 5.8000, 5.7700), 35.62, 1092.27, 1092.27),
    ModelSpec("ハッピー", "ハッピージャグラーVIII", 240, 96, (6.04, 6.01, 5.98, 5.86, 5.84, 5.82), 56.55, 655.36, 655.36, 4),
    ModelSpec("ジャグラーガールズ", "ジャグラーガールズSS", 252, 96, (6.01, 6.01, 6.01, 6.01, 5.92, 5.89), 33.301, 1092.267, 1092.267),
    ModelSpec("ミスタージャグラー", "ミスタージャグラー", 240, 96, (6.24212, 6.18381, 6.13690, 6.09807, 6.05973, 6.01689), 37.236, 655.36, 2173.04),
    ModelSpec("ウルトラミラクル", "ウルトラミラクルジャグラー", 240, 96, (5.940, 5.938, 5.936, 5.934, 5.933, 5.929), 34.86, 1024.0, 1024.0),
)


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_cell = False
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] = []
        self._links: list[str] = []

