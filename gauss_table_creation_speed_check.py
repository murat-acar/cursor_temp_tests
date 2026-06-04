"""
GaussDB table-creation speed check.

Only this Python file is needed. In main(), run your existing .sh (zsql),
parse stdout, and return monitoring alert dicts.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAG = "高斯表创建速度过快检查"
HANDLER = "d00606891"

# Path to your zsql shell script (override with GAUSS_CHECK_SH or argv[1])
DEFAULT_SH = os.environ.get("GAUSS_CHECK_SH", "check_gauss_table_creation_speed.sh")

WINDOW_DESC = {
    "LAST_24H": "24小时内创建数{prefix_cnt}个",
    "HOURS_24_TO_48": "24-48小时内创建数{prefix_cnt}个",
}


@dataclass(frozen=True)
class SqlRow:
    owner_name: str
    prefix_6: str
    creation_window: str
    recent_same_prefix_cnt: int
    total_table_cnt: int


def _strip_border(line: str) -> str:
    return line.strip().strip("|").strip()


def _split_row(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in _strip_border(line).split("|")]
    return re.split(r"\s{2,}", line.strip())


def _is_separator(line: str) -> bool:
    s = line.strip()
    return not s or set(s) <= {"+", "-", "|", " ", "\t"}


def parse_zsql_output(stdout: str) -> list[SqlRow]:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
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

    headers = [h.lower() for h in _split_row(lines[header_idx])]
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
        if _is_separator(line):
            continue
        parts = _split_row(line)
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


def build_alerts(rows: list[SqlRow]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for row in rows:
        window_key = row.creation_window.strip().upper()
        window_part = WINDOW_DESC.get(window_key)
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
                "title": f"【{TAG}】{owner}表创建速度过快",
                "tag": TAG,
                "handler": HANDLER,
                "deduplication": (
                    f"【{TAG}】{owner}表名前缀{prefix}6个字符相同"
                ),
                "dts_enabled": False,
                "dts_level": "Major",
            }
        )
    return alerts


def main(sh_path: str | None = None) -> list[dict[str, Any]]:
    """Run shell script, parse zsql output, return alert list."""
    script = Path(sh_path or DEFAULT_SH)
    if not script.is_file():
        raise FileNotFoundError(f"Shell script not found: {script}")

    completed = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Shell check failed (exit {completed.returncode}): {err}"
        )

    return build_alerts(parse_zsql_output(completed.stdout))


if __name__ == "__main__":
    try:
        sh_arg = sys.argv[1] if len(sys.argv) > 1 else None
        result = main(sh_arg)
    except Exception as exc:
        print(f"gauss table creation speed check error: {exc}")
        result = []

    print(json.dumps(result, ensure_ascii=False, indent=2))
