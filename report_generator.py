"""Generate a self-contained, printable end-of-session HTML report."""

import html
import json
from pathlib import Path


def generate_session_report(batch_id, log_path, output_dir):
    log_path = Path(log_path)
    records = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                if record.get("batch_id") == batch_id:
                    records.append(record)
            except (ValueError, TypeError):
                continue

    total = max((int(item.get("total", 0)) for item in records), default=0)
    good = max((int(item.get("good", 0)) for item in records), default=0)
    rejected = max((int(item.get("rejected", 0)) for item in records), default=0)
    waste = max((float(item.get("waste_kg", 0)) for item in records), default=0)
    loss = max((int(item.get("estimated_loss_vnd", 0)) for item in records), default=0)
    defect = rejected / total * 100 if total else 0
    rows = "".join(
        f"<tr>"
        f"<td class='mono'>{html.escape(str(item.get('created_at', '')))}</td>"
        f"<td><span class='pill {'bad' if item.get('quality') == 'rejected' else 'good'}'>"
        f"{'Quả hỏng — Loại bỏ' if item.get('quality') == 'rejected' else 'Quả lành — Đạt chuẩn'}</span></td>"
        f"<td class='mono'>{min(100, round(float(item.get('confidence', 0)) * 100))}%</td>"
        f"</tr>"
        for item in records
    ) or "<tr><td colspan='3' class='empty'>Chưa có sản phẩm qua vạch đếm.</td></tr>"

    document = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Báo cáo kiểm tra lô {html.escape(batch_id)} — FruitGuard</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif;
      color: #0f172a;
      background: #ffffff;
      margin: 40px auto;
      padding: 0 24px;
      max-width: 980px;
      font-size: 14px;
      line-height: 1.5;
    }}
    .mono {{ font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; font-size: 12.5px; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      padding-bottom: 18px;
      border-bottom: 2px solid #0f172a;
      margin-bottom: 24px;
    }}
    .doc-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #0f766e; }}
    h1 {{ margin: 4px 0 0; font-size: 28px; letter-spacing: -0.02em; font-family: ui-monospace, Consolas, monospace; }}
    header p {{ margin: 4px 0 0; color: #475569; font-size: 13px; }}
    .loss-box {{ text-align: right; }}
    .loss-box span {{ display: block; font-size: 12px; color: #64748b; }}
    .loss-box strong {{ font-size: 20px; color: #b91c1c; font-variant-numeric: tabular-nums; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin-bottom: 28px;
    }}
    .metric {{
      border: 1px solid #e2e6ec;
      background: #f8fafc;
      padding: 14px;
      border-radius: 8px;
    }}
    .metric span {{ display: block; font-size: 12px; color: #64748b; }}
    .metric b {{ display: block; font-size: 22px; margin-top: 6px; font-variant-numeric: tabular-nums; }}
    .metric.good b {{ color: #15803d; }}
    .metric.bad b {{ color: #b91c1c; }}
    .metric.warn b {{ color: #b45309; }}
    h2 {{ font-size: 15px; font-weight: 600; margin: 0 0 12px; color: #0f172a; }}
    table {{ width: 100%; border-collapse: collapse; border: 1px solid #e2e6ec; }}
    th, td {{ padding: 10px 14px; border-bottom: 1px solid #e2e6ec; text-align: left; }}
    th {{
      background: #f1f5f9;
      color: #475569;
      font-size: 11.5px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .pill.good {{ background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }}
    .pill.bad {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
    .empty {{ text-align: center; color: #64748b; padding: 24px; }}
    footer {{
      margin-top: 28px;
      padding-top: 14px;
      border-top: 1px solid #e2e6ec;
      color: #64748b;
      font-size: 12px;
      display: flex;
      justify-content: space-between;
    }}
    @media print {{
      body {{ margin: 12px auto; }}
      .metric {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="doc-label">FruitGuard · Báo cáo kiểm tra chất lượng</div>
      <h1>{html.escape(batch_id)}</h1>
      <p>Hệ thống phân loại nhị phân trên băng chuyền (Quả lành / Quả hỏng)</p>
    </div>
    <div class="loss-box">
      <span>Giá trị thất thoát ước tính</span>
      <strong>{loss:,.0f} VNĐ</strong>
    </div>
  </header>

  <section class="metrics">
    <div class="metric"><span>Tổng kiểm tra</span><b>{total:,}</b></div>
    <div class="metric good"><span>Đạt chuẩn</span><b>{good:,}</b></div>
    <div class="metric bad"><span>Loại bỏ</span><b>{rejected:,}</b></div>
    <div class="metric bad"><span>Tỷ lệ hỏng</span><b>{defect:.1f}%</b></div>
    <div class="metric warn"><span>Nguy cơ lãng phí</span><b>{waste:.2f} kg</b></div>
  </section>

  <h2>Nhật ký kiểm tra chi tiết</h2>
  <table>
    <thead>
      <tr><th>Thời gian</th><th>Kết quả phân loại</th><th>Độ tin cậy</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>

  <footer>
    <span>Tạo tự động bởi hệ thống FruitGuard</span>
    <span>Có thể in trực tiếp hoặc lưu PDF từ trình duyệt</span>
  </footer>
</body>
</html>"""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char for char in batch_id if char.isalnum() or char in "-_ ").strip() or "session"
    report_path = output_dir / f"bao_cao_{safe_name}.html"
    report_path.write_text(document, encoding="utf-8")
    return report_path
