from dataclasses import dataclass


@dataclass
class Decision:
    """Slip-matching decision output."""
    action: str  # "attach_pay" | "ask" | "ignore"
    payment_id: int | None = None
    reply_text: str | None = None
    slip_path: str | None = None


class PendingStore:
    """Stores slip image + candidate IDs awaiting user clarification."""
    TTL = 600

    def __init__(self):
        self._slot = {}

    def put(self, group_id: str, path: str, candidate_ids: list[int], ts: float) -> None:
        """Store slip + candidates; overwrite any prior entry."""
        self._slot[group_id] = {"path": path, "candidate_ids": candidate_ids, "ts": ts}

    def take(self, group_id: str, now_ts: float) -> dict | None:
        """Return + clear non-expired entry; delete stale; return None if absent or expired."""
        entry = self._slot.get(group_id)
        if entry is None:
            return None
        if now_ts - entry["ts"] > self.TTL:
            self._slot.pop(group_id, None)
            return None
        return self._slot.pop(group_id, None)


def _confirm(name: str, number: int, total: int, amount: float) -> str:
    """Format confirmation message."""
    return f"✅ บันทึกสลิป + จ่ายแล้ว — {name} งวดที่ {number}/{total} ฿{amount:,.2f}"


def decide(
    outstanding: list[dict],
    saved_slip_path: str | None,
    text: str | None,
    group_id: str,
    pending: PendingStore,
    now_ts: float,
) -> Decision:
    """Decide whether slip auto-attaches, asks for clarification, or is ignored."""

    # ──── Image event path (slip image uploaded) ────
    if saved_slip_path is not None:
        if not outstanding:
            return Decision("ignore", reply_text="ℹ️ ไม่มีงวดค้างชำระในขณะนี้")
        if len(outstanding) == 1:
            p = outstanding[0]
            return Decision(
                "attach_pay",
                p["id"],
                _confirm(p["name"], p["installment_number"], p["num_installments"], p["amount"]),
                saved_slip_path,
            )
        # Multiple outstanding: ask which one
        pending.put(group_id, saved_slip_path, [p["id"] for p in outstanding], now_ts)
        names = "\n".join(f"  • {p['name']}" for p in outstanding)
        return Decision(
            "ask",
            reply_text=f"❓ มีหลายรายการค้างชำระ พิมพ์ชื่อรายการที่จ่ายนะ:\n{names}",
            slip_path=saved_slip_path,
        )

    # ──── Text event path (user clarification text) ────
    if text is not None:
        entry = pending.take(group_id, now_ts)
        if entry is None:
            return Decision("ignore")

        # Match text against the candidate names — require exactly one
        matched = [
            p for p in outstanding
            if p["id"] in entry["candidate_ids"] and p["name"] in text
        ]
        if len(matched) == 1:
            p = matched[0]
            return Decision(
                "attach_pay",
                p["id"],
                _confirm(p["name"], p["installment_number"], p["num_installments"], p["amount"]),
                entry["path"],
            )

        # Zero or many matches: re-arm pending so the user can try again within the TTL
        pending.put(group_id, entry["path"], entry["candidate_ids"], now_ts)
        return Decision("ask", reply_text="❓ ไม่พบชื่อรายการที่ตรง พิมพ์ชื่อให้ชัดเจนนะ", slip_path=entry["path"])

    # Should not reach here
    return Decision("ignore")
