# PATH: strategy/execution/accounting.py
"""
Accounting stub (STEP 10).

Post-trade record keeping:
- Trade execution records
- PnL tracking
- Gas cost tracking
- Slippage tracking

All recording is disabled in M4.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class TradeRecord:
    """Single trade execution record."""
    trade_id: str
    spread_id: str
    timestamp: str = ""
    chain_id: int = 0
    dex_buy: str = ""
    dex_sell: str = ""
    token_in: str = ""
    token_out: str = ""
    amount_in: str = "0"
    amount_out: str = "0"
    gross_pnl_usdc: str = "0"
    gas_actual_usdc: str = "0"
    slippage_actual_bps: int = 0
    net_pnl_usdc: str = "0"
    tx_hash_buy: Optional[str] = None
    tx_hash_sell: Optional[str] = None
    status: str = "PENDING"
    error: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "spread_id": self.spread_id,
            "timestamp": self.timestamp,
            "chain_id": self.chain_id,
            "dex_buy": self.dex_buy,
            "dex_sell": self.dex_sell,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "gross_pnl_usdc": self.gross_pnl_usdc,
            "gas_actual_usdc": self.gas_actual_usdc,
            "slippage_actual_bps": self.slippage_actual_bps,
            "net_pnl_usdc": self.net_pnl_usdc,
            "tx_hash_buy": self.tx_hash_buy,
            "tx_hash_sell": self.tx_hash_sell,
            "status": self.status,
            "error": self.error,
        }


class AccountingStub:
    """
    Accounting stub for trade records.
    
    M4: All recording is disabled (no trades).
    M5: Will enable paper trade recording.
    M6: Will enable real trade recording.
    """

    def __init__(self, enabled: bool = False, output_dir: Optional[Path] = None):
        self._enabled = enabled
        self._output_dir = output_dir
        self._records: List[TradeRecord] = []
        self._total_gross_pnl = Decimal("0")
        self._total_gas = Decimal("0")
        self._total_net_pnl = Decimal("0")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def trade_count(self) -> int:
        return len(self._records)

    @property
    def total_gross_pnl(self) -> Decimal:
        return self._total_gross_pnl

    @property
    def total_gas(self) -> Decimal:
        return self._total_gas

    @property
    def total_net_pnl(self) -> Decimal:
        return self._total_net_pnl

    def record_trade(self, record: TradeRecord) -> bool:
        """
        Record a trade execution.
        
        M4: Always returns False (recording disabled).
        """
        if not self._enabled:
            return False

        self._records.append(record)

        try:
            self._total_gross_pnl += Decimal(record.gross_pnl_usdc)
            self._total_gas += Decimal(record.gas_actual_usdc)
            self._total_net_pnl += Decimal(record.net_pnl_usdc)
        except Exception:
            pass

        return True

    def save(self, path: Optional[Path] = None) -> bool:
        """Save records to file."""
        if not self._enabled:
            return False

        output_path = path or (self._output_dir / "trade_records.json" if self._output_dir else None)
        if not output_path:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "trade_count": self.trade_count,
            "total_gross_pnl_usdc": str(self._total_gross_pnl),
            "total_gas_usdc": str(self._total_gas),
            "total_net_pnl_usdc": str(self._total_net_pnl),
            "records": [r.to_dict() for r in self._records],
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        return True

    def get_summary(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "trade_count": self.trade_count,
            "total_gross_pnl_usdc": str(self._total_gross_pnl),
            "total_gas_usdc": str(self._total_gas),
            "total_net_pnl_usdc": str(self._total_net_pnl),
        }
