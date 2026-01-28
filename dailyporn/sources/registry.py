from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..config import DailyPornConfig
from ..services.http import HttpService
from .base import BaseSource
from .beeg import BeegSource
from .eporner import EPornerSource
from .hanime import HanimeSource
from .hqporner import HQPornerSource
from .hentaigem import HentaiGemSource
from .mmdhub import MmdHubSource
from .missav import MissAVSource
from .noodlemagazine import NoodleMagazineSource
from .pornhub import PornhubSource
from .porntrex import PornTrexSource
from .sexcom import SexComSource
from .rule34video import Rule34VideoSource
from .spankbang import SpankBangSource
from .three_d_porndude import ThreeDPornDudeSource
from .three_dporn import ThreeDPornSource
from .vip91 import Vip91Source
from .xfreehd import XFreeHDSource
from .xhamster import XHamsterSource
from .xnxx import XNXXSource
from .xvideos import XVideosSource
from .xview import XViewSource
from .xxxgfporn import XXXGFPornSource


@dataclass(frozen=True)
class SourceInfo:
    source_id: str
    display_name: str
    sections: set[str]
    enabled: bool


class SourceRegistry:
    MANUAL_ONLY_SOURCE_IDS = {"hqporner", "missav"}

    def __init__(self, http: HttpService, cfg: DailyPornConfig):
        self._http = http
        self._cfg = cfg
        self._sources: dict[str, BaseSource] = {
            "3dporn": ThreeDPornSource(http),
            "3dporndude": ThreeDPornDudeSource(http),
            "beeg": BeegSource(http),
            "eporner": EPornerSource(http),
            "hanime": HanimeSource(http),
            "hqporner": HQPornerSource(http),
            "mmdhub": MmdHubSource(http),
            "missav": MissAVSource(http),
            "pornhub": PornhubSource(http),
            "porntrex": PornTrexSource(http),
            "sexcom": SexComSource(http),
            "hentaigem": HentaiGemSource(http),
            "rule34video": Rule34VideoSource(http),
            "spankbang": SpankBangSource(http),
            "noodlemagazine": NoodleMagazineSource(http),
            "91vip": Vip91Source(http),
            "xfreehd": XFreeHDSource(http),
            "xhamster": XHamsterSource(http),
            "xnxx": XNXXSource(http),
            "xvideos": XVideosSource(http),
            "xview": XViewSource(http),
            "xxxgfporn": XXXGFPornSource(http),
        }

    def list_sources(self) -> list[SourceInfo]:
        out: list[SourceInfo] = []
        for sid, src in sorted(self._sources.items(), key=lambda x: x[0]):
            out.append(
                SourceInfo(
                    source_id=sid,
                    display_name=src.display_name,
                    sections=set(src.sections),
                    enabled=self._cfg.is_source_enabled(sid),
                )
            )
        return out

    def iter_enabled_sources(self, section: str) -> Iterable[BaseSource]:
        for sid, src in self._sources.items():
            if not src.supports(section):
                continue
            if sid in self.MANUAL_ONLY_SOURCE_IDS:
                continue
            if not self._cfg.is_source_enabled(sid):
                continue
            yield src

    def iter_all_sources(self) -> Iterable[BaseSource]:
        return self._sources.values()

    def get_source(self, source_id: str) -> BaseSource | None:
        return self._sources.get(source_id)
