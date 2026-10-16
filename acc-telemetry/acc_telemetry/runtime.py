"""Wires settings, source (real or mock), store, sampler and the telemetry service together."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import PROJECT_DIR, Settings
from .sampler import Sampler
from .store import Store
from .tools import Telemetry
from .tracks import load_track

log = logging.getLogger("acc.runtime")


@dataclass
class Runtime:
    cfg: Settings
    store: Store
    sampler: Sampler
    telemetry: Telemetry
    mock: bool

    def start(self) -> None:
        self.sampler.start()

    def stop(self) -> None:
        self.sampler.stop()
        self.store.close()


def build(mock: bool = False, data_dir: Optional[Path] = None, mock_speed: float = 6.0, seed_laps: int = 6,
          trace_hz: Optional[float] = None) -> Runtime:
    """Mock mode keeps its own database (data/mock) so demo laps never mix with real ones."""
    cfg = Settings()
    if data_dir:
        cfg.data_dir = Path(data_dir)
    elif mock:
        cfg.data_dir = PROJECT_DIR / "data" / "mock"
    if trace_hz:
        cfg.trace_hz = trace_hz
    store = Store(cfg.db_path)
    if mock:
        from . import mock as mock_mod
        track = load_track("spa")
        sampler = Sampler(None, store, cfg)
        have = len(store.list_laps(limit=1000))
        if have < seed_laps and seed_laps:
            # fill the store through the normal pipeline, offline, so the dashboard has laps at once
            mock_mod.seed(sampler, track, seed_laps - have)
            sampler = Sampler(None, store, cfg)
            have = seed_laps
        sampler.source = mock_mod.MockSource(track, speedup=mock_speed, skip_laps=have)
    else:
        from .acc_shm import ShmReader
        sampler = Sampler(ShmReader(), store, cfg)
    return Runtime(cfg, store, sampler, Telemetry(sampler, store, cfg), mock)
