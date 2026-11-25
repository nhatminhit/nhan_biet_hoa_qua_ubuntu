"""Read-only FastAPI dashboard for logs produced by the desktop GUI."""

import json
import re
import time
import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from report_generator import generate_session_report
from fastapi.staticfiles import StaticFiles
from warehouse_manager import WarehouseManager

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
STATE_PATH = OUTPUT_DIR / "dashboard_state.json"
LOG_PATH = OUTPUT_DIR / "production_log.jsonl"
WAREHOUSE_PATH = OUTPUT_DIR / "warehouse_inventory.json"
REJECTED_DIR = OUTPUT_DIR / "rejected_products"
EXPLANATIONS_DIR = OUTPUT_DIR / "explanations"
REPORTS_DIR = OUTPUT_DIR / "reports"
WEB_DIST = BASE_DIR / "web" / "dist"

warehouse = WarehouseManager(WAREHOUSE_PATH, LOG_PATH)

EMPTY_STATE = {
    "running": False, "source": "GUI chưa hoạt động", "total": 0,
    "good": 0, "rejected": 0, "defect_rate": 0.0,
    "active_tracks": 0, "fps": 0.0, "latency_ms": 0.0,
    "uptime_seconds": 0, "events": [], "updated_at": None,
    "batch": {"id": "DEMO-001", "fruit": "Trái cây"},
    "fruit_breakdown": {},
    "waste_kg": 0.0, "estimated_loss_vnd": 0,
}


def read_history(limit=120, batch_id=None):
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
            if batch_id is None or record.get("batch_id") == batch_id:
                records.append(record)
        except (ValueError, TypeError):
            continue
    return records


def all_records():
    return read_history(limit=1_000_000)


def summarize_sessions():
    sessions = {}
    for record in all_records():
        batch_id = record.get("batch_id") or "LEGACY"
        session = sessions.setdefault(batch_id, {
            "batch_id": batch_id, "batch_fruit": "Trái cây",
            "started_at": record.get("created_at"), "ended_at": record.get("created_at"),
            "total": 0, "good": 0, "rejected": 0,
            "waste_kg": 0.0, "estimated_loss_vnd": 0, "events": 0,
        })
        timestamps = [value for value in [session["started_at"], record.get("created_at")] if value]
        if timestamps:
            session["started_at"] = min(timestamps)
            session["ended_at"] = max(timestamps)
        session["total"] = max(session["total"], int(record.get("total", 0)))
        session["good"] = max(session["good"], int(record.get("good", 0)))
        session["rejected"] = max(session["rejected"], int(record.get("rejected", 0)))
        session["waste_kg"] = max(session["waste_kg"], float(record.get("waste_kg", 0)))
        session["estimated_loss_vnd"] = max(
            session["estimated_loss_vnd"], int(record.get("estimated_loss_vnd", 0))
        )
        session["events"] += 1
    for session in sessions.values():
        session["defect_rate"] = round(
            session["rejected"] / session["total"] * 100, 1
        ) if session["total"] else 0.0
    return sorted(sessions.values(), key=lambda item: item.get("ended_at") or "", reverse=True)


def read_state():
    state = dict(EMPTY_STATE)
    try:
        state.update(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass
    updated_at = state.get("updated_at_epoch", 0)
    state["gui_online"] = bool(updated_at and time.time() - updated_at < 5)
    state["history"] = read_history(batch_id=state.get("batch", {}).get("id"))
    return state


app = FastAPI(title="Fruit Conveyor & Warehouse API", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
)


class WarehouseImportRequest(BaseModel):
    fruit_type: str = "apple"
    qty: int
    shelf_life_days: float | None = None
    batch_id: str | None = None
    note: str = ""


class WarehouseDispatchRequest(BaseModel):
    qty: int
    fruit_type: str | None = None
    lot_id: str | None = None
    note: str = ""


class WarehouseLotActionRequest(BaseModel):
    note: str = ""


@app.get("/api/health")
def health():
    state = read_state()
    return {"status": "ok", "mode": "read_only_log", "gui_online": state["gui_online"]}


@app.get("/api/stats")
def stats():
    return read_state()


@app.get("/api/logs")
def logs(limit: int = 100):
    return read_history(max(1, min(limit, 500)))[::-1]


@app.get("/api/sessions")
def sessions():
    return summarize_sessions()


@app.get("/api/sessions/{batch_id}/logs")
def session_logs(batch_id: str):
    records = [
        record for record in all_records()
        if (record.get("batch_id") or "LEGACY") == batch_id
    ]
    return [{**record, "fruit_type": "fruit"} for record in records[::-1]]


@app.get("/api/sessions/{batch_id}/export.csv")
def export_session_csv(batch_id: str):
    records = [
        record for record in all_records()
        if (record.get("batch_id") or "LEGACY") == batch_id
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["BÁO CÁO PHÂN LOẠI PHIÊN - FRUITGUARD AI"])
    writer.writerow(["Mã lô", batch_id])
    writer.writerow(["Thời điểm xuất", datetime.now().strftime("%d/%m/%Y %H:%M:%S")])
    writer.writerow([])
    writer.writerow([
        "STT",
        "Thời gian",
        "Mã lô",
        "Nguồn video / camera",
        "Kết quả phân loại",
        "Độ tin cậy (%)",
        "Sự kiện",
        "Tổng đã kiểm tra",
        "Số quả đạt",
        "Số quả hỏng",
        "Khối lượng hỏng (kg)",
        "Thất thoát ước tính (VNĐ)",
    ])
    quality_map = {
        "good": "Quả lành — Đạt chuẩn",
        "rejected": "Quả hỏng — Loại bỏ",
    }
    for idx, rec in enumerate(records, start=1):
        created = rec.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass
        conf = rec.get("confidence")
        conf_pct = f"{min(100, round(float(conf) * 100, 1))}%" if conf is not None else ""
        writer.writerow([
            idx,
            created,
            rec.get("batch_id", ""),
            rec.get("source", ""),
            quality_map.get(rec.get("quality"), "Không xác định"),
            conf_pct,
            rec.get("event", ""),
            rec.get("total", 0),
            rec.get("good", 0),
            rec.get("rejected", 0),
            rec.get("waste_kg", 0),
            rec.get("estimated_loss_vnd", 0),
        ])
    content = "\ufeff" + output.getvalue()
    safe_batch = "".join(char for char in batch_id if char.isalnum() or char in "-_").strip() or "Phien"
    fruit_slug_map = {"apple": "Tao", "banana": "Chuoi", "orange": "Cam"}
    fruit_counts = {"apple": 0, "banana": 0, "orange": 0}
    max_total = 0
    for rec in records:
        ft = rec.get("fruit_type")
        if ft in fruit_counts:
            fruit_counts[ft] += 1
        max_total = max(max_total, int(rec.get("total", 0)))
    top_fruit = max(fruit_counts, key=lambda k: fruit_counts[k])
    fruit_part = fruit_slug_map[top_fruit] if fruit_counts[top_fruit] > 0 else "NongSan"
    stamp = datetime.now().strftime("%d-%m-%Y_%Hh%M")
    filename = f"FruitGuard_PhanLoai_Lo-{safe_batch}_{fruit_part}_{max_total}Qua_{stamp}.csv"
    return Response(
        content=content, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{batch_id}/report.html")
def session_report(batch_id: str):
    report_path = generate_session_report(batch_id, LOG_PATH, REPORTS_DIR)
    return FileResponse(report_path, media_type="text/html; charset=utf-8")


_BATCH_IMG_RE = re.compile(r"^loai_batch_([A-Za-z0-9-]+)_\d{8}_\d{6}")


def _session_time_windows():
    windows = []
    for session in summarize_sessions():
        try:
            start = datetime.fromisoformat(session["started_at"]).timestamp() if session.get("started_at") else None
            end = datetime.fromisoformat(session["ended_at"]).timestamp() if session.get("ended_at") else None
        except ValueError:
            continue
        if start is not None and end is not None:
            windows.append((session["batch_id"], start - 5.0, end + 15.0))
    return windows


def _infer_rejection_batch_id(item: Path, mtime: float, windows):
    match = _BATCH_IMG_RE.match(item.stem)
    if match:
        return match.group(1)
    for batch_id, start_ts, end_ts in windows:
        if start_ts <= mtime <= end_ts:
            return batch_id
    return None


@app.get("/api/rejections")
def rejections(limit: int = 24, batch_id: str | None = None):
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(REJECTED_DIR.glob("*.jpg"), key=lambda item: item.stat().st_mtime, reverse=True)
    windows = _session_time_windows()
    target_batch = (batch_id or "").strip() or None
    max_items = max(1, min(limit, 500))
    results = []
    for item in files:
        mtime = item.stat().st_mtime
        img_batch = _infer_rejection_batch_id(item, mtime, windows)
        if target_batch is not None and img_batch != target_batch:
            continue
        explanation_file = item.name.replace("loai_", "giai_thich_", 1)
        results.append({
            "name": item.name,
            "url": f"/evidence/{item.name}",
            "batch_id": img_batch,
            "fruit_type": "fruit",
            "explanation_url": (
                f"/explanations/{explanation_file}"
                if (EXPLANATIONS_DIR / explanation_file).exists()
                else None
            ),
            "created_at": datetime.fromtimestamp(mtime).isoformat(),
        })
        if len(results) >= max_items:
            break
    return results


@app.get("/api/warehouse")
def get_warehouse():
    return warehouse.get_state()


@app.post("/api/warehouse/import")
def warehouse_import(payload: WarehouseImportRequest):
    try:
        return warehouse.import_lot(
            fruit_type=payload.fruit_type,
            qty=payload.qty,
            shelf_life_days=payload.shelf_life_days,
            batch_id=payload.batch_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/warehouse/dispatch")
def warehouse_dispatch(payload: WarehouseDispatchRequest):
    try:
        return warehouse.dispatch_stock(
            qty=payload.qty,
            fruit_type=payload.fruit_type,
            lot_id=payload.lot_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/warehouse/lots/{lot_id}/inspect")
def warehouse_inspect_lot(lot_id: str, payload: WarehouseLotActionRequest):
    try:
        return warehouse.inspect_lot(lot_id=lot_id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/warehouse/lots/{lot_id}/dispose")
def warehouse_dispose_lot(lot_id: str, payload: WarehouseLotActionRequest):
    try:
        return warehouse.dispose_lot(lot_id=lot_id, note=payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/warehouse/export.csv")
def export_warehouse_csv():
    state = warehouse.get_state()
    summary = state["summary"]
    content = warehouse.export_csv()
    stamp = datetime.now().strftime("%d-%m-%Y_%Hh%M")
    status_tag = (
        f"CANHBAO-{summary['alert_lots_count']}Lo"
        if summary["alert_lots_count"] > 0
        else f"{summary['active_lots_count']}Lo-{summary['total_in_stock']}Qua"
    )
    filename = f"FruitGuard_BaoCaoTonKho_{status_tag}_{stamp}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REJECTED_DIR.mkdir(parents=True, exist_ok=True)
EXPLANATIONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(REJECTED_DIR)), name="evidence")
app.mount("/explanations", StaticFiles(directory=str(EXPLANATIONS_DIR)), name="explanations")
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="dashboard")
