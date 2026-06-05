"""Bridge-shadow spread lifetime telemetry (Phase 2).

Collects per-sweep cycle observations for M8-sourced routes and aggregates
first_positive -> last_positive lifetime for each cycle_id / token mirror pair.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from m9.graph_arb.models import CycleQuoteResult

DEFAULT_SPREAD_LIFETIME_PATH = "data/tmp/m9_spread_lifetime_latest.json"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exotic_tokens_from_cycle(qr: CycleQuoteResult) -> List[str]:
    """Return non-anchor token addresses on the cycle (heuristic: not USDC/WETH)."""
    anchors = frozenset({"USDC", "USDBC", "USDbC", "DAI", "WETH", "ETH"})
    out: List[str] = []
    for e in qr.cycle.edges:
        if e.token_in_sym.upper() not in anchors and e.token_in_addr:
            out.append(e.token_in_addr.lower())
        if e.token_out_sym.upper() not in anchors and e.token_out_addr:
            out.append(e.token_out_addr.lower())
    return list(dict.fromkeys(out))


def _gross_counts_for_evidence(qr: CycleQuoteResult) -> bool:
    if qr.gross_bps <= 0:
        return False
    try:
        from monitoring.sniper_honeypot import positive_gross_counts_as_evidence

        return positive_gross_counts_as_evidence(_exotic_tokens_from_cycle(qr))
    except Exception:
        return qr.gross_bps > 0


@dataclass
class _CycleSpreadState:
    cycle_id: str
    token: str
    mirror_pair: str
    mechanic_pair: str
    cross_mechanic: bool
    uses_m8_pool: bool
    first_positive_ts: Optional[float] = None
    last_positive_ts: Optional[float] = None
    peak_gross_bps: float = 0.0
    positive_sweeps: int = 0


@dataclass
class SpreadLifetimeTracker:
    """Accumulates bridge-shadow per-sweep telemetry and lifetime aggregates."""

    run_timestamp: str
    sweep_observations: List[Dict[str, Any]] = field(default_factory=list)
    _by_cycle: Dict[str, _CycleSpreadState] = field(default_factory=dict)

    def record_sweep(
        self,
        *,
        sweep_number: int,
        sweep_ts: float,
        results: List[CycleQuoteResult],
        m8_pool_addrs: frozenset[str],
        cross_mechanic_pool_addrs: frozenset[str],
    ) -> None:
        for qr in results:
            uses_m8 = any(e.pool_address.lower() in m8_pool_addrs for e in qr.cycle.edges)
            cross_mech = any(
                e.pool_address.lower() in cross_mechanic_pool_addrs for e in qr.cycle.edges
            )
            if not uses_m8 and not cross_mech:
                continue
            cid = qr.cycle.cycle_id
            exotic_addrs = _exotic_tokens_from_cycle(qr)
            token = exotic_addrs[0] if exotic_addrs else qr.cycle.start_token_sym
            pair_syms = sorted({e.pair_id for e in qr.cycle.edges if e.pair_id})
            mirror_pair = pair_syms[0] if pair_syms else ""
            dexes = sorted({e.dex_id for e in qr.cycle.edges})
            mechanic_pair = "+".join(dexes)
            gross_evidence = _gross_counts_for_evidence(qr)

            self.sweep_observations.append(
                {
                    "sweep_number": sweep_number,
                    "timestamp_utc": datetime.fromtimestamp(
                        sweep_ts, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "cycle_id": cid,
                    "gross_bps": round(qr.gross_bps, 4),
                    "gross_bps_evidence": gross_evidence,
                    "status": qr.status,
                    "m8_pool": uses_m8,
                    "cross_mechanic": cross_mech,
                    "mirror_pair": mirror_pair,
                }
            )

            st = self._by_cycle.get(cid)
            if st is None:
                st = _CycleSpreadState(
                    cycle_id=cid,
                    token=token,
                    mirror_pair=mirror_pair,
                    mechanic_pair=mechanic_pair,
                    cross_mechanic=cross_mech,
                    uses_m8_pool=uses_m8,
                )
                self._by_cycle[cid] = st
            if gross_evidence:
                st.positive_sweeps += 1
                if st.first_positive_ts is None or sweep_ts < st.first_positive_ts:
                    st.first_positive_ts = sweep_ts
                if st.last_positive_ts is None or sweep_ts > st.last_positive_ts:
                    st.last_positive_ts = sweep_ts
                st.peak_gross_bps = max(st.peak_gross_bps, qr.gross_bps)

    def build_summary(self) -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        lifetimes: List[float] = []
        for st in self._by_cycle.values():
            if st.first_positive_ts is None or st.last_positive_ts is None:
                continue
            lifetime_s = max(0.0, st.last_positive_ts - st.first_positive_ts)
            lifetimes.append(lifetime_s)
            entries.append(
                {
                    "token": st.token,
                    "mirror_pair": st.mirror_pair,
                    "mechanic_pair": st.mechanic_pair,
                    "cycle_id": st.cycle_id,
                    "cross_mechanic": st.cross_mechanic,
                    "m8_pool": st.uses_m8_pool,
                    "first_positive_ts": datetime.fromtimestamp(
                        st.first_positive_ts, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "last_positive_ts": datetime.fromtimestamp(
                        st.last_positive_ts, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "lifetime_s": round(lifetime_s, 3),
                    "peak_gross_bps": round(st.peak_gross_bps, 4),
                    "positive_sweeps": st.positive_sweeps,
                }
            )
        median_lifetime: Optional[float] = None
        if lifetimes:
            median_lifetime = round(statistics.median(lifetimes), 3)
        return {
            "entries": entries,
            "entry_count": len(entries),
            "median_lifetime_s": median_lifetime,
            "sweep_observation_count": len(self.sweep_observations),
        }

    def to_artifact_block(self) -> Dict[str, Any]:
        summary = self.build_summary()
        return {
            "run_timestamp": self.run_timestamp,
            "spread_lifetime": summary,
            "sweep_telemetry_sample": self.sweep_observations[:200],
        }

    def write_sidecar(self, path: str = DEFAULT_SPREAD_LIFETIME_PATH) -> Path:
        summary = self.build_summary()
        payload = {
            "schema_version": "m9_spread_lifetime_v1",
            "generated_at_utc": _iso_now(),
            "run_timestamp": self.run_timestamp,
            "entries": summary["entries"],
            "median_lifetime_s": summary["median_lifetime_s"],
            "sweep_observation_count": summary["sweep_observation_count"],
        }
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return out
