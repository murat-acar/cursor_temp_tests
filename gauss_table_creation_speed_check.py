"""
GaussDB table-creation speed check.

DataProcessor parses zsql stdout (string) and builds monitoring alert dicts.
main() accepts that string directly (no shell execution).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SqlRow:
    owner_name: str
    prefix_6: str
    creation_window: str
    recent_same_prefix_cnt: int
    total_table_cnt: int


class DataProcessor:
    TAG = "高斯表创建速度过快检查"
    HANDLER = "d00606891"
    WINDOW_DESC = {
        "LAST_24H": "24小时内创建数{prefix_cnt}个",
        "HOURS_24_TO_48": "24-48小时内创建数{prefix_cnt}个",
    }

    def __init__(self, data: str) -> None:
        self.data = data

    @staticmethod
    def _strip_border(line: str) -> str:
        return line.strip().strip("|").strip()

    def _split_row(self, line: str) -> list[str]:
        if "|" in line:
            return [c.strip() for c in self._strip_border(line).split("|")]
        return re.split(r"\s{2,}", line.strip())

    @staticmethod
    def _is_separator(line: str) -> bool:
        s = line.strip()
        return not s or set(s) <= {"+", "-", "|", " ", "\t"}

    def parse(self) -> list[SqlRow]:
        lines = [ln for ln in self.data.splitlines() if ln.strip()]
        if not lines:
            return []

        header_idx = None
        for i, line in enumerate(lines):
            lower = line.lower()
            if "owner_name" in lower and "prefix_6" in lower:
                header_idx = i
                break
        if header_idx is None:
            return []

        headers = [h.lower() for h in self._split_row(lines[header_idx])]
        col = {name: idx for idx, name in enumerate(headers)}
        required = (
            "owner_name",
            "prefix_6",
            "creation_window",
            "recent_same_prefix_cnt",
            "total_table_cnt",
        )
        if any(k not in col for k in required):
            return []

        rows: list[SqlRow] = []
        for line in lines[header_idx + 1 :]:
            if self._is_separator(line):
                continue
            parts = self._split_row(line)
            if len(parts) < len(headers):
                continue
            try:
                rows.append(
                    SqlRow(
                        owner_name=parts[col["owner_name"]],
                        prefix_6=parts[col["prefix_6"]],
                        creation_window=parts[col["creation_window"]],
                        recent_same_prefix_cnt=int(
                            parts[col["recent_same_prefix_cnt"]]
                        ),
                        total_table_cnt=int(parts[col["total_table_cnt"]]),
                    )
                )
            except (ValueError, IndexError):
                continue
        return rows

    def build_alerts(self, rows: list[SqlRow]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for row in rows:
            window_key = row.creation_window.strip().upper()
            window_part = self.WINDOW_DESC.get(window_key)
            if not window_part:
                continue

            owner = row.owner_name
            prefix = row.prefix_6
            total = row.total_table_cnt
            prefix_cnt = row.recent_same_prefix_cnt

            alerts.append(
                {
                    "desc": (
                        f"问题描述：{owner}表创建过快，总表数{total}，"
                        f"{window_part.format(prefix_cnt=prefix_cnt)}"
                    ),
                    "title": f"【{self.TAG}】{owner}表创建速度过快",
                    "tag": self.TAG,
                    "handler": self.HANDLER,
                    "deduplication": (
                        f"【{self.TAG}】{owner}表名前缀{prefix}6个字符相同"
                    ),
                    "dts_enabled": False,
                    "dts_level": "Major",
                }
            )
        return alerts

    def process(self) -> list[dict[str, Any]]:
        return self.build_alerts(self.parse())


def main(data: str) -> list[dict[str, Any]]:
    """Parse zsql output string and return alert dicts."""
    return DataProcessor(data).process()


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 2:
            raw = Path(sys.argv[1]).read_text(encoding="utf-8")
        else:
            raw = Path(__file__).with_name(
                "gauss_check_sample_output.txt"
            ).read_text(encoding="utf-8")
        result = main(raw)
    except Exception as exc:
        print(f"gauss table creation speed check error: {exc}")
        result = []

    print(json.dumps(result, ensure_ascii=False, indent=2))
