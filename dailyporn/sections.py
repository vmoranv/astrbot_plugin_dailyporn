from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Section:
    key: str
    display: str


SECTIONS: list[Section] = [
    Section("3d", "3D"),
    Section("2.5d", "2.5D"),
    Section("real", "真人"),
]


_ALIASES = {
    "3d": {"3d", "3D", "3d区", "3d专区", "3d分区", "3d榜"},
    "2.5d": {"2.5d", "2.5D", "2d", "2D", "2.5d区", "2.5d专区", "2.5d分区", "2.5d榜"},
    "real": {"real", "真人", "真人区", "真人专区", "真人分区", "真人榜"},
    "all": {"all", "全部", "综合", "总榜"},
}


def normalize_section(value: str) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    lower = v.lower()
    for key, names in _ALIASES.items():
        if v in names or lower in {n.lower() for n in names}:
            return key
    for sec in SECTIONS:
        if lower == sec.key:
            return sec.key
    return None


def section_display(key: str) -> str:
    for sec in SECTIONS:
        if sec.key == key:
            return sec.display
    return key
