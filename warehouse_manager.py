"""JSON-backed warehouse inventory management with 2-day expiry alerts and FEFO dispatch."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

WARN_BEFORE_DAYS = 2.0
AVG_FRUIT_WEIGHT_KG = 0.18

FRUIT_CONFIG: dict[str, dict[str, Any]] = {
    "apple": {
        "label": "Táo tươi",
        "zone_id": "ZONE_A",
        "shelf_life_days": 14,
    },
    "banana": {
        "label": "Chuối tươi",
        "zone_id": "ZONE_B",
        "shelf_life_days": 4,
    },
    "orange": {
        "label": "Cam tươi",
        "zone_id": "ZONE_C",
        "shelf_life_days": 10,
    },
}

DEFAULT_ZONES: dict[str, dict[str, Any]] = {
    "ZONE_A": {
        "id": "ZONE_A",
        "name": "Khu A — Táo tươi",
        "fruit_type": "apple",
        "temp": "2–4°C",
        "capacity": 200,
    },
    "ZONE_B": {
        "id": "ZONE_B",
        "name": "Khu B — Chuối tươi",
        "fruit_type": "banana",
        "temp": "12–14°C",
        "capacity": 200,
    },
    "ZONE_C": {
        "id": "ZONE_C",
        "name": "Khu C — Cam tươi",
        "fruit_type": "orange",
        "temp": "4–8°C",
        "capacity": 200,
    },
    "ZONE_REJECT": {
        "id": "ZONE_REJECT",
        "name": "Khu D — Hàng loại chờ xử lý",
        "fruit_type": "rejected",
        "temp": "Nhiệt độ thường",
        "capacity": 100,
    },
}


def _now() -> datetime:
    return datetime.now()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_remaining(hours_left: float) -> str:
    if hours_left <= 0:
        overdue_hours = abs(hours_left)
        if overdue_hours >= 24:
            return f"Quá hạn {overdue_hours / 24:.1f} ngày"
        return f"Quá hạn {max(1, round(overdue_hours))} giờ"
    if hours_left < 24:
        return f"Còn {max(1, round(hours_left))} giờ"
    return f"Còn {hours_left / 24:.1f} ngày"


def _normalize_fruit(raw_fruit: str | None) -> str:
    text = (raw_fruit or "").strip().lower()
    if "banana" in text or "chuoi" in text or "chuối" in text:
        return "banana"
    if "orange" in text or "cam" in text:
        return "orange"
    return "apple"


class WarehouseManager:
    """Thread-safe JSON warehouse store synced with conveyor production logs."""

    def __init__(self, warehouse_path: Path, log_path: Path):
        self.warehouse_path = warehouse_path
        self.log_path = log_path
        self._lock = threading.Lock()

    def _default_data(self) -> dict[str, Any]:
        return {
            "version": 1,
            "warn_before_days": WARN_BEFORE_DAYS,
            "updated_at": _now().isoformat(),
            "zones": json.loads(json.dumps(DEFAULT_ZONES)),
            "lots": [],
            "transactions": [],
        }

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.warehouse_path.exists():
            return self._default_data()
        try:
            data = json.loads(self.warehouse_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return self._default_data()
        except (OSError, ValueError, TypeError):
            return self._default_data()

        data.setdefault("version", 1)
        data.setdefault("warn_before_days", WARN_BEFORE_DAYS)
        data.setdefault("zones", json.loads(json.dumps(DEFAULT_ZONES)))
        for zone_id, zone_cfg in DEFAULT_ZONES.items():
            data["zones"].setdefault(zone_id, dict(zone_cfg))
        data.setdefault("lots", [])
        data.setdefault("transactions", [])
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        self.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = _now().isoformat()
        tmp_path = self.warehouse_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.warehouse_path)

    def _append_tx(
        self,
        data: dict[str, Any],
        tx_type: str,
        lot_id: str,
        fruit_type: str,
        qty: int,
        note: str,
    ) -> dict[str, Any]:
        tx = {
            "id": f"TX-{uuid.uuid4().hex[:8].upper()}",
            "type": tx_type,
            "lot_id": lot_id,
            "fruit_type": fruit_type,
            "fruit_label": FRUIT_CONFIG.get(fruit_type, {}).get("label", "Nông sản"),
            "qty": int(qty),
            "note": note,
            "created_at": _now().isoformat(),
        }
        data["transactions"].insert(0, tx)
        data["transactions"] = data["transactions"][:200]
        return tx

    def _read_production_batches(self) -> dict[str, dict[str, Any]]:
        if not self.log_path.exists():
            return {}
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}

        batches: dict[str, dict[str, Any]] = {}
        for line in lines:
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            batch_id = str(rec.get("batch_id") or "").strip()
            if not batch_id:
                continue
            info = batches.setdefault(
                batch_id,
                {
                    "batch_id": batch_id,
                    "good": 0,
                    "rejected": 0,
                    "started_at": rec.get("created_at"),
                    "ended_at": rec.get("created_at"),
                    "fruit_counts": {"apple": 0, "banana": 0, "orange": 0},
                    "batch_fruit": rec.get("batch_fruit") or "",
                },
            )
            info["good"] = max(info["good"], int(rec.get("good", 0)))
            info["rejected"] = max(info["rejected"], int(rec.get("rejected", 0)))
            ts = rec.get("created_at")
            if ts:
                if not info["started_at"] or ts < info["started_at"]:
                    info["started_at"] = ts
                if not info["ended_at"] or ts > info["ended_at"]:
                    info["ended_at"] = ts
            ft = rec.get("fruit_type")
            if ft in info["fruit_counts"]:
                info["fruit_counts"][ft] += 1

        return batches

    def _is_conveyor_in_tx(self, tx: dict[str, Any]) -> bool:
        if tx.get("type") != "IN":
            return False
        if tx.get("auto_conveyor"):
            return True
        note = str(tx.get("note") or "").lower()
        return "từ băng chuyền" in note and ("tự động" in note or "bổ sung" in note)

    def _upsert_conveyor_tx(
        self,
        data: dict[str, Any],
        lot_id: str,
        batch_id: str,
        fruit_type: str,
        total_qty: int,
    ) -> dict[str, Any]:
        txs = data.setdefault("transactions", [])
        note = f"Tự động nhập kho từ băng chuyền (lô {batch_id})"
        fruit_label = FRUIT_CONFIG.get(fruit_type, {}).get("label", "Nông sản")
        now_iso = _now().isoformat()

        existing_idx = next(
            (i for i, t in enumerate(txs) if t.get("lot_id") == lot_id and self._is_conveyor_in_tx(t)),
            None,
        )
        if existing_idx is not None:
            tx = txs.pop(existing_idx)
            tx["fruit_type"] = fruit_type
            tx["fruit_label"] = fruit_label
            tx["qty"] = int(total_qty)
            tx["note"] = note
            tx["auto_conveyor"] = True
            tx["created_at"] = now_iso
            txs.insert(0, tx)
            return tx

        tx = {
            "id": f"TX-{uuid.uuid4().hex[:8].upper()}",
            "type": "IN",
            "lot_id": lot_id,
            "fruit_type": fruit_type,
            "fruit_label": fruit_label,
            "qty": int(total_qty),
            "note": note,
            "auto_conveyor": True,
            "created_at": now_iso,
        }
        txs.insert(0, tx)
        data["transactions"] = txs[:200]
        return tx

    def _compact_conveyor_transactions_unlocked(self, data: dict[str, Any]) -> bool:
        """Gộp các dòng log nhập kho tự động lẻ (+1 quả) của cùng một lô thành 1 dòng tổng."""
        txs = data.get("transactions") or []
        if not txs:
            return False

        compacted: list[dict[str, Any]] = []
        seen_by_lot: dict[str, dict[str, Any]] = {}
        changed = False

        for tx in txs:
            if self._is_conveyor_in_tx(tx) and tx.get("lot_id"):
                lot_id = tx["lot_id"]
                if lot_id in seen_by_lot:
                    seen_by_lot[lot_id]["qty"] = int(seen_by_lot[lot_id].get("qty", 0)) + int(tx.get("qty", 0))
                    changed = True
                else:
                    merged = dict(tx)
                    merged["auto_conveyor"] = True
                    batch_id = lot_id[4:] if lot_id.startswith("LOT-") else lot_id
                    merged["note"] = f"Tự động nhập kho từ băng chuyền (lô {batch_id})"
                    if merged.get("note") != tx.get("note") or not tx.get("auto_conveyor"):
                        changed = True
                    seen_by_lot[lot_id] = merged
                    compacted.append(merged)
            else:
                compacted.append(tx)

        if changed:
            data["transactions"] = compacted[:200]
        return changed

    def _sync_from_logs_unlocked(self, data: dict[str, Any]) -> bool:
        changed = self._compact_conveyor_transactions_unlocked(data)
        batches = self._read_production_batches()
        if not batches:
            return changed

        lots_by_batch = {
            lot.get("batch_id"): lot
            for lot in data["lots"]
            if lot.get("source") == "conveyor" and lot.get("batch_id")
        }

        for batch_id, b in batches.items():
            if b["good"] <= 0 and b["rejected"] <= 0:
                continue

            dominant_fruit = max(b["fruit_counts"], key=lambda k: b["fruit_counts"][k])
            if b["fruit_counts"][dominant_fruit] == 0:
                dominant_fruit = _normalize_fruit(b.get("batch_fruit"))
            fruit_cfg = FRUIT_CONFIG[dominant_fruit]

            existing = lots_by_batch.get(batch_id)
            if existing is None:
                imported_dt = _parse_iso(b.get("started_at")) or _now()
                shelf_days = fruit_cfg["shelf_life_days"]
                expires_dt = imported_dt + timedelta(days=shelf_days)
                lot_id = f"LOT-{batch_id}"
                lot = {
                    "lot_id": lot_id,
                    "batch_id": batch_id,
                    "source": "conveyor",
                    "fruit_type": dominant_fruit,
                    "fruit_label": fruit_cfg["label"],
                    "zone_id": fruit_cfg["zone_id"],
                    "imported_qty": b["good"],
                    "remaining_qty": b["good"],
                    "rejected_qty": b["rejected"],
                    "synced_good": b["good"],
                    "shelf_life_days": shelf_days,
                    "imported_at": imported_dt.isoformat(),
                    "expires_at": expires_dt.isoformat(),
                    "status": "in_stock" if b["good"] > 0 else "empty",
                    "inspected_at": None,
                    "inspection_note": "",
                    "note": "Đồng bộ tự động từ băng chuyền",
                }
                data["lots"].append(lot)
                if b["good"] > 0:
                    self._upsert_conveyor_tx(
                        data,
                        lot_id,
                        batch_id,
                        dominant_fruit,
                        b["good"],
                    )
                changed = True
            else:
                prev_synced = int(existing.get("synced_good", existing.get("imported_qty", 0)))
                delta_good = b["good"] - prev_synced
                if delta_good > 0:
                    existing["imported_qty"] = int(existing.get("imported_qty", 0)) + delta_good
                    if existing.get("status") != "disposed":
                        existing["remaining_qty"] = int(existing.get("remaining_qty", 0)) + delta_good
                        if existing["remaining_qty"] > 0:
                            existing["status"] = "in_stock"
                    existing["synced_good"] = b["good"]
                    self._upsert_conveyor_tx(
                        data,
                        existing["lot_id"],
                        batch_id,
                        existing["fruit_type"],
                        existing["imported_qty"],
                    )
                    changed = True
                if b["rejected"] > int(existing.get("rejected_qty", 0)):
                    existing["rejected_qty"] = b["rejected"]
                    changed = True

        return changed

    def _enrich_state(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        warn_days = float(data.get("warn_before_days", WARN_BEFORE_DAYS))

        enriched_lots: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        zone_used: dict[str, int] = {z_id: 0 for z_id in data["zones"]}
        total_rejected_hold = 0

        for raw_lot in data["lots"]:
            lot = dict(raw_lot)
            remaining = int(lot.get("remaining_qty", 0))
            rejected = int(lot.get("rejected_qty", 0))
            total_rejected_hold += rejected

            expires_dt = _parse_iso(lot.get("expires_at"))
            hours_left = (expires_dt - now).total_seconds() / 3600.0 if expires_dt else 9999.0
            days_left = round(hours_left / 24.0, 1)

            if lot.get("status") == "disposed":
                expiry_state = "disposed"
                needs_inspection = False
            elif remaining <= 0:
                expiry_state = "empty"
                needs_inspection = False
            elif hours_left <= 0:
                expiry_state = "expired"
                needs_inspection = True
            elif hours_left <= warn_days * 24.0:
                expiry_state = "expiring_soon"
                needs_inspection = True
            else:
                expiry_state = "fresh"
                needs_inspection = False

            if remaining > 0 and lot.get("status") != "disposed":
                z_id = lot.get("zone_id", "ZONE_A")
                zone_used[z_id] = zone_used.get(z_id, 0) + remaining

            lot["weight_kg"] = round(remaining * AVG_FRUIT_WEIGHT_KG, 2)
            lot["days_left"] = days_left
            lot["hours_left"] = round(hours_left, 1)
            lot["remaining_text"] = _format_remaining(hours_left) if remaining > 0 and lot.get("status") != "disposed" else "—"
            lot["expiry_state"] = expiry_state
            lot["needs_inspection"] = needs_inspection
            lot["inspected"] = bool(lot.get("inspected_at"))
            enriched_lots.append(lot)

            if expiry_state == "expired":
                alerts.append({
                    "id": f"ALERT-EXP-{lot['lot_id']}",
                    "severity": "critical",
                    "kind": "expired",
                    "lot_id": lot["lot_id"],
                    "fruit_label": lot.get("fruit_label", "Nông sản"),
                    "zone_id": lot.get("zone_id"),
                    "remaining_qty": remaining,
                    "days_left": days_left,
                    "remaining_text": lot["remaining_text"],
                    "inspected": lot["inspected"],
                    "inspected_at": lot.get("inspected_at"),
                    "message": (
                        f"Lô {lot['lot_id']} ({lot.get('fruit_label')}) đã quá hạn ({lot['remaining_text']}), "
                        f"còn {remaining} quả — cần kiểm tra và xử lý ngay."
                    ),
                })
            elif expiry_state == "expiring_soon":
                alerts.append({
                    "id": f"ALERT-WARN-{lot['lot_id']}",
                    "severity": "warning",
                    "kind": "expiring_soon",
                    "lot_id": lot["lot_id"],
                    "fruit_label": lot.get("fruit_label", "Nông sản"),
                    "zone_id": lot.get("zone_id"),
                    "remaining_qty": remaining,
                    "days_left": days_left,
                    "remaining_text": lot["remaining_text"],
                    "inspected": lot["inspected"],
                    "inspected_at": lot.get("inspected_at"),
                    "message": (
                        f"Lô {lot['lot_id']} ({lot.get('fruit_label')}) sắp hết hạn ({lot['remaining_text']}, "
                        f"cảnh báo trước {int(warn_days)} ngày), còn {remaining} quả — cần kiểm tra chất lượng."
                    ),
                })

        zone_used["ZONE_REJECT"] = total_rejected_hold

        zones_list: list[dict[str, Any]] = []
        total_capacity = 0
        total_good_used = 0
        for zone_id, z_cfg in data["zones"].items():
            used = zone_used.get(zone_id, 0)
            cap = max(1, int(z_cfg.get("capacity", 200)))
            pct = round(min(100.0, used / cap * 100.0), 1)
            zone_item = {
                **z_cfg,
                "id": zone_id,
                "used": used,
                "capacity": cap,
                "utilization_pct": pct,
                "weight_kg": round(used * AVG_FRUIT_WEIGHT_KG, 2),
                "near_full": pct >= 85.0,
            }
            zones_list.append(zone_item)
            if zone_id != "ZONE_REJECT":
                total_capacity += cap
                total_good_used += used
            if pct >= 85.0:
                alerts.append({
                    "id": f"ALERT-CAP-{zone_id}",
                    "severity": "warning",
                    "kind": "zone_capacity",
                    "lot_id": None,
                    "zone_id": zone_id,
                    "message": f"{z_cfg['name']} đã đạt {pct}% sức chứa ({used}/{cap} quả).",
                })

        # Sort lots: expired -> expiring_soon -> fresh (FEFO by expires_at) -> empty/disposed
        state_order = {"expired": 0, "expiring_soon": 1, "fresh": 2, "empty": 3, "disposed": 4}
        enriched_lots.sort(
            key=lambda item: (
                state_order.get(item["expiry_state"], 5),
                item.get("expires_at") or "9999",
            )
        )

        # Sort alerts: critical first, uninspected first
        alerts.sort(
            key=lambda a: (
                0 if a["severity"] == "critical" else 1,
                0 if not a.get("inspected") else 1,
                a.get("days_left", 99),
            )
        )

        active_lots = [l for l in enriched_lots if l["remaining_qty"] > 0 and l["expiry_state"] != "disposed"]
        expiring_lots = [l for l in active_lots if l["expiry_state"] in ("expiring_soon", "expired")]
        uninspected_expiring = [l for l in expiring_lots if not l["inspected"]]

        summary = {
            "total_in_stock": total_good_used,
            "total_weight_kg": round(total_good_used * AVG_FRUIT_WEIGHT_KG, 2),
            "active_lots_count": len(active_lots),
            "expiring_soon_count": sum(1 for l in active_lots if l["expiry_state"] == "expiring_soon"),
            "expired_count": sum(1 for l in active_lots if l["expiry_state"] == "expired"),
            "alert_lots_count": len(expiring_lots),
            "uninspected_alert_count": len(uninspected_expiring),
            "rejected_hold_qty": total_rejected_hold,
            "utilization_pct": round(min(100.0, total_good_used / max(1, total_capacity) * 100.0), 1),
            "warn_before_days": int(warn_days),
        }

        return {
            "updated_at": data.get("updated_at"),
            "summary": summary,
            "zones": zones_list,
            "alerts": alerts,
            "lots": enriched_lots,
            "transactions": data.get("transactions", [])[:50],
        }

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            changed = self._sync_from_logs_unlocked(data)
            if changed or not self.warehouse_path.exists():
                self._save_unlocked(data)
            return self._enrich_state(data)

    @staticmethod
    def _next_manual_batch_id(data: dict[str, Any], prefix: str = "MAN") -> str:
        """Tự động sinh mã lô nhập kho tăng dần (MAN-001, MAN-002, ...)."""
        pattern = re.compile(rf"^(?:LOT-)?{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
        max_num = 0
        for lot in data.get("lots", []):
            for field in (lot.get("batch_id"), lot.get("lot_id")):
                match = pattern.match(str(field or "").strip())
                if match:
                    max_num = max(max_num, int(match.group(1)))
        return f"{prefix}-{max_num + 1:03d}"

    def import_lot(
        self,
        fruit_type: str,
        qty: int,
        shelf_life_days: float | None = None,
        batch_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        if qty <= 0:
            raise ValueError("Số lượng nhập kho phải lớn hơn 0.")
        fruit = _normalize_fruit(fruit_type)
        cfg = FRUIT_CONFIG[fruit]
        days = float(shelf_life_days) if shelf_life_days is not None else float(cfg["shelf_life_days"])
        if days <= 0:
            raise ValueError("Hạn sử dụng phải lớn hơn 0 ngày.")

        with self._lock:
            data = self._load_unlocked()
            self._sync_from_logs_unlocked(data)

            now = _now()
            clean_batch = self._next_manual_batch_id(data)
            lot_id = f"LOT-{clean_batch}"
            if any(l.get("lot_id") == lot_id for l in data["lots"]):
                lot_id = f"{lot_id}-{uuid.uuid4().hex[:4].upper()}"

            expires_dt = now + timedelta(days=days)
            lot = {
                "lot_id": lot_id,
                "batch_id": clean_batch,
                "source": "manual",
                "fruit_type": fruit,
                "fruit_label": cfg["label"],
                "zone_id": cfg["zone_id"],
                "imported_qty": int(qty),
                "remaining_qty": int(qty),
                "rejected_qty": 0,
                "synced_good": 0,
                "shelf_life_days": days,
                "imported_at": now.isoformat(),
                "expires_at": expires_dt.isoformat(),
                "status": "in_stock",
                "inspected_at": None,
                "inspection_note": "",
                "note": note.strip() or "Nhập kho thủ công",
            }
            data["lots"].append(lot)
            self._append_tx(
                data,
                "IN",
                lot_id,
                fruit,
                int(qty),
                note.strip() or f"Nhập kho thủ công (HSD {days:g} ngày)",
            )
            self._save_unlocked(data)
            return self._enrich_state(data)

    def dispatch_stock(
        self,
        qty: int,
        fruit_type: str | None = None,
        lot_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        if qty <= 0:
            raise ValueError("Số lượng xuất kho phải lớn hơn 0.")
        clean_note = (note or "").strip()
        if not clean_note:
            raise ValueError("Vui lòng nhập Ghi chú / Đơn vị nhận trước khi xuất kho.")

        with self._lock:
            data = self._load_unlocked()
            self._sync_from_logs_unlocked(data)

            if lot_id:
                candidates = [
                    l for l in data["lots"]
                    if l.get("lot_id") == lot_id and int(l.get("remaining_qty", 0)) > 0 and l.get("status") != "disposed"
                ]
                if not candidates:
                    raise ValueError(f"Không tìm thấy lô {lot_id} còn hàng trong kho.")
            else:
                fruit = _normalize_fruit(fruit_type)
                candidates = [
                    l for l in data["lots"]
                    if l.get("fruit_type") == fruit and int(l.get("remaining_qty", 0)) > 0 and l.get("status") != "disposed"
                ]
                # FEFO: earliest expiration date first
                candidates.sort(key=lambda l: l.get("expires_at") or "9999")

            available = sum(int(l.get("remaining_qty", 0)) for l in candidates)
            if available <= 0:
                raise ValueError("Hiện không còn hàng tồn kho cho loại nông sản này để xuất.")
            if qty > available:
                raise ValueError(
                    f"Số lượng xuất ({qty} quả) không được vượt quá số lượng tồn kho hiện có ({available} quả)."
                )

            to_take = int(qty)
            for lot in candidates:
                if to_take <= 0:
                    break
                rem = int(lot.get("remaining_qty", 0))
                take = min(rem, to_take)
                lot["remaining_qty"] = rem - take
                if lot["remaining_qty"] == 0:
                    lot["status"] = "empty"
                to_take -= take
                mode_label = "Xuất đích danh" if lot_id else "Xuất tự động FEFO"
                tx_note = f"{mode_label} — {note.strip()}" if note.strip() else mode_label
                self._append_tx(data, "OUT", lot["lot_id"], lot["fruit_type"], take, tx_note)

            self._save_unlocked(data)
            return self._enrich_state(data)

    def inspect_lot(self, lot_id: str, note: str = "") -> dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            target = next((l for l in data["lots"] if l.get("lot_id") == lot_id), None)
            if target is None:
                raise ValueError(f"Không tìm thấy lô {lot_id}.")

            now = _now()
            target["inspected_at"] = now.isoformat()
            target["inspection_note"] = note.strip() or "Đã kiểm tra chất lượng — đạt điều kiện xuất ưu tiên"
            self._append_tx(
                data,
                "INSPECT",
                lot_id,
                target.get("fruit_type", "apple"),
                int(target.get("remaining_qty", 0)),
                target["inspection_note"],
            )
            self._save_unlocked(data)
            return self._enrich_state(data)

    def dispose_lot(self, lot_id: str, note: str = "") -> dict[str, Any]:
        with self._lock:
            data = self._load_unlocked()
            target = next((l for l in data["lots"] if l.get("lot_id") == lot_id), None)
            if target is None:
                raise ValueError(f"Không tìm thấy lô {lot_id}.")

            removed_qty = int(target.get("remaining_qty", 0))
            target["remaining_qty"] = 0
            target["status"] = "disposed"
            target["rejected_qty"] = int(target.get("rejected_qty", 0)) + removed_qty
            dispose_note = note.strip() or "Hủy lô quá hạn / không đạt kiểm tra"
            self._append_tx(
                data,
                "DISPOSE",
                lot_id,
                target.get("fruit_type", "apple"),
                removed_qty,
                dispose_note,
            )
            self._save_unlocked(data)
            return self._enrich_state(data)

    def export_csv(self) -> str:
        state = self.get_state()
        summary = state["summary"]
        zones_by_id = {z["id"]: z for z in state["zones"]}

        def fmt_dt(iso_str: str | None) -> str:
            dt = _parse_iso(iso_str)
            return dt.strftime("%d/%m/%Y %H:%M") if dt else ""

        state_labels = {
            "fresh": "Còn hạn tốt",
            "expiring_soon": "Sắp hết hạn (<= 2 ngày)",
            "expired": "Đã quá hạn",
            "empty": "Đã xuất hết",
            "disposed": "Đã hủy",
        }
        tx_labels = {
            "IN": "Nhập kho",
            "OUT": "Xuất kho",
            "INSPECT": "Kiểm tra chất lượng",
            "DISPOSE": "Hủy lô",
        }

        output = io.StringIO()
        writer = csv.writer(output)

        # Phần tổng quan đầu báo cáo
        writer.writerow(["BÁO CÁO TỒN KHO NÔNG SẢN - FRUITGUARD AI"])
        writer.writerow(["Thời điểm xuất báo cáo", _now().strftime("%d/%m/%Y %H:%M:%S")])
        writer.writerow(["Tổng tồn kho đạt chuẩn", f"{summary['total_in_stock']} quả ({summary['total_weight_kg']} kg)"])
        writer.writerow(["Số lô đang lưu kho", f"{summary['active_lots_count']} lô"])
        writer.writerow(["Số lô sắp hết hạn (<= 2 ngày)", f"{summary['expiring_soon_count']} lô"])
        writer.writerow(["Số lô đã quá hạn", f"{summary['expired_count']} lô"])
        writer.writerow(["Tỷ lệ lấp đầy kho lạnh", f"{summary['utilization_pct']}%"])
        writer.writerow([])

        # Bảng 1: Danh sách lô hàng
        writer.writerow(["1. DANH SÁCH LÔ HÀNG TRONG KHO"])
        writer.writerow([
            "STT",
            "Mã lô",
            "Loại nông sản",
            "Khu lưu trữ",
            "Nguồn nhập",
            "SL nhập (quả)",
            "Tồn hiện tại (quả)",
            "Khối lượng tồn (kg)",
            "Ngày nhập kho",
            "Hạn sử dụng",
            "Thời gian còn lại",
            "Trạng thái hạn dùng",
            "Tình trạng kiểm tra",
            "Thời điểm kiểm tra",
            "Ghi chú",
        ])

        for idx, lot in enumerate(state["lots"], start=1):
            zone = zones_by_id.get(lot.get("zone_id"), {})
            zone_name = f"{zone.get('name', lot.get('zone_id', ''))} ({zone.get('temp', '')})".strip()
            source_label = "Băng chuyền AI" if lot.get("source") == "conveyor" else "Nhập thủ công"
            expiry_text = state_labels.get(lot.get("expiry_state"), "Không rõ")

            if lot.get("inspected"):
                inspect_status = "Đã kiểm tra"
            elif lot.get("needs_inspection"):
                inspect_status = "CẦN KIỂM TRA NGAY"
            else:
                inspect_status = "Bình thường"

            note = lot.get("inspection_note") or lot.get("note") or ""
            writer.writerow([
                idx,
                lot.get("lot_id", ""),
                lot.get("fruit_label", ""),
                zone_name,
                source_label,
                lot.get("imported_qty", 0),
                lot.get("remaining_qty", 0),
                lot.get("weight_kg", 0),
                fmt_dt(lot.get("imported_at")),
                fmt_dt(lot.get("expires_at")),
                lot.get("remaining_text", "—"),
                expiry_text,
                inspect_status,
                fmt_dt(lot.get("inspected_at")) or "Chưa kiểm tra",
                note,
            ])

        writer.writerow([])

        # Bảng 2: Lịch sử giao dịch kho
        writer.writerow(["2. LỊCH SỬ NHẬP - XUẤT - KIỂM TRA GẦN ĐÂY"])
        writer.writerow([
            "STT",
            "Thời gian",
            "Loại giao dịch",
            "Mã lô",
            "Loại nông sản",
            "Số lượng (quả)",
            "Ghi chú",
        ])
        for idx, tx in enumerate(state["transactions"], start=1):
            writer.writerow([
                idx,
                fmt_dt(tx.get("created_at")),
                tx_labels.get(tx.get("type"), tx.get("type", "")),
                tx.get("lot_id", ""),
                tx.get("fruit_label", ""),
                tx.get("qty", 0),
                tx.get("note", ""),
            ])

        return "\ufeff" + output.getvalue()
