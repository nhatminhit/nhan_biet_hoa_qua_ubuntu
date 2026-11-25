import { useMemo, useState } from 'react'

const FRUIT_OPTIONS = [
  { value: 'apple', label: 'Táo tươi (Khu A · HSD 14 ngày)', defaultDays: 14 },
  { value: 'banana', label: 'Chuối tươi (Khu B · HSD 4 ngày)', defaultDays: 4 },
  { value: 'orange', label: 'Cam tươi (Khu C · HSD 10 ngày)', defaultDays: 10 },
]

function postJson(path, body) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async response => {
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'Thao tác kho thất bại')
    return data
  })
}

function expiryBadge(lot) {
  switch (lot.expiry_state) {
    case 'expired':
      return { text: 'Đã quá hạn', tone: 'bad' }
    case 'expiring_soon':
      return { text: 'Sắp hết hạn (≤ 2 ngày)', tone: 'warn' }
    case 'fresh':
      return { text: 'Còn hạn tốt', tone: 'good' }
    case 'disposed':
      return { text: 'Đã hủy', tone: 'neutral' }
    default:
      return { text: 'Đã xuất hết', tone: 'neutral' }
  }
}

function txBadge(type) {
  switch (type) {
    case 'IN':
      return { text: 'Nhập kho', tone: 'good' }
    case 'OUT':
      return { text: 'Xuất kho', tone: 'brand' }
    case 'INSPECT':
      return { text: 'Kiểm tra', tone: 'warn' }
    case 'DISPOSE':
      return { text: 'Hủy lô', tone: 'bad' }
    default:
      return { text: type, tone: 'neutral' }
  }
}

export default function WarehouseView({ data, onUpdate }) {
  const [filter, setFilter] = useState('all')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Dispatch form (FEFO)
  const [dispatchFruit, setDispatchFruit] = useState('apple')
  const [dispatchQty, setDispatchQty] = useState('10')
  const [dispatchNote, setDispatchNote] = useState('')

  // Quick lot dispatch modal state (requires recipient/note & qty <= remaining)
  const [quickDispatchLot, setQuickDispatchLot] = useState(null)
  const [quickDispatchQty, setQuickDispatchQty] = useState('1')
  const [quickDispatchNote, setQuickDispatchNote] = useState('')

  // Manual import form
  const [importFruit, setImportFruit] = useState('banana')
  const [importQty, setImportQty] = useState('25')
  const [importDays, setImportDays] = useState('2')
  const [importNote, setImportNote] = useState('')

  const summary = data?.summary || {
    total_in_stock: 0,
    total_weight_kg: 0,
    active_lots_count: 0,
    expiring_soon_count: 0,
    expired_count: 0,
    alert_lots_count: 0,
    uninspected_alert_count: 0,
    rejected_hold_qty: 0,
    utilization_pct: 0,
    warn_before_days: 2,
  }
  const zones = data?.zones || []
  const alerts = data?.alerts || []
  const lots = data?.lots || []
  const transactions = data?.transactions || []

  const availableByFruit = useMemo(() => {
    const totals = { apple: 0, banana: 0, orange: 0 }
    for (const lot of lots) {
      if (lot.expiry_state !== 'disposed' && lot.remaining_qty > 0 && lot.fruit_type in totals) {
        totals[lot.fruit_type] += Number(lot.remaining_qty || 0)
      }
    }
    return totals
  }, [lots])

  const maxDispatchQty = availableByFruit[dispatchFruit] || 0
  const parsedDispatchQty = parseInt(dispatchQty, 10) || 0
  const dispatchQtyExceeds = parsedDispatchQty > maxDispatchQty

  const expiryAlerts = useMemo(
    () => alerts.filter(a => a.kind === 'expired' || a.kind === 'expiring_soon'),
    [alerts]
  )

  const filteredLots = useMemo(() => {
    if (filter === 'alert') {
      return lots.filter(l => l.expiry_state === 'expired' || l.expiry_state === 'expiring_soon')
    }
    if (filter === 'fresh') {
      return lots.filter(l => l.expiry_state === 'fresh')
    }
    if (filter === 'closed') {
      return lots.filter(l => l.expiry_state === 'empty' || l.expiry_state === 'disposed')
    }
    return lots
  }, [lots, filter])

  const runAction = async (fn, successMsg) => {
    setBusy(true)
    setFeedback(null)
    try {
      const updated = await fn()
      onUpdate(updated)
      setFeedback({ tone: 'good', text: successMsg })
    } catch (err) {
      setFeedback({ tone: 'bad', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const handleDispatchSubmit = e => {
    e.preventDefault()
    const qty = parseInt(dispatchQty, 10)
    const note = dispatchNote.trim()
    if (!qty || qty <= 0) {
      setFeedback({ tone: 'bad', text: 'Vui lòng nhập số lượng xuất hợp lệ (> 0).' })
      return
    }
    if (qty > maxDispatchQty) {
      setFeedback({
        tone: 'bad',
        text: `Số lượng xuất (${qty} quả) không được vượt quá tồn kho hiện có (${maxDispatchQty} quả).`,
      })
      return
    }
    if (!note) {
      setFeedback({ tone: 'bad', text: 'Vui lòng nhập Ghi chú / Đơn vị nhận trước khi xuất kho.' })
      return
    }
    runAction(
      () =>
        postJson('/api/warehouse/dispatch', {
          fruit_type: dispatchFruit,
          qty,
          note,
        }),
      `Đã xuất ${qty} quả cho "${note}" theo thứ tự FEFO.`
    )
    setDispatchNote('')
  }

  const handleImportSubmit = e => {
    e.preventDefault()
    const qty = parseInt(importQty, 10)
    const days = parseFloat(importDays)
    if (!qty || qty <= 0 || !days || days <= 0) {
      setFeedback({ tone: 'bad', text: 'Số lượng và hạn sử dụng (ngày) phải lớn hơn 0.' })
      return
    }
    runAction(
      () =>
        postJson('/api/warehouse/import', {
          fruit_type: importFruit,
          qty,
          shelf_life_days: days,
          note: importNote,
        }),
      `Đã nhập lô mới (${qty} quả, HSD ${days} ngày).`
    )
    setImportNote('')
  }

  const handleInspect = lot => {
    runAction(
      () =>
        postJson(`/api/warehouse/lots/${encodeURIComponent(lot.lot_id)}/inspect`, {
          note: 'Đã kiểm tra chất lượng trước hạn — đủ điều kiện xuất ưu tiên',
        }),
      `Đã xác nhận kiểm tra lô ${lot.lot_id}.`
    )
  }

  const handleQuickDispatchLot = lot => {
    if (!lot.remaining_qty) return
    setQuickDispatchLot(lot)
    setQuickDispatchQty(String(lot.remaining_qty))
    setQuickDispatchNote('')
  }

  const confirmQuickDispatch = e => {
    e.preventDefault()
    if (!quickDispatchLot) return
    const qty = parseInt(quickDispatchQty, 10)
    const note = quickDispatchNote.trim()
    if (!qty || qty <= 0) {
      setFeedback({ tone: 'bad', text: 'Số lượng xuất phải lớn hơn 0.' })
      return
    }
    if (qty > quickDispatchLot.remaining_qty) {
      setFeedback({
        tone: 'bad',
        text: `Số lượng xuất (${qty} quả) không được vượt quá tồn của lô (${quickDispatchLot.remaining_qty} quả).`,
      })
      return
    }
    if (!note) {
      setFeedback({ tone: 'bad', text: 'Vui lòng nhập Ghi chú / Đơn vị nhận trước khi xuất kho.' })
      return
    }
    const targetLot = quickDispatchLot
    setQuickDispatchLot(null)
    setQuickDispatchNote('')
    runAction(
      () =>
        postJson('/api/warehouse/dispatch', {
          lot_id: targetLot.lot_id,
          qty,
          note,
        }),
      `Đã xuất ${qty} quả của lô ${targetLot.lot_id} cho "${note}".`
    )
  }

  const handleDispose = lot => {
    runAction(
      () =>
        postJson(`/api/warehouse/lots/${encodeURIComponent(lot.lot_id)}/dispose`, {
          note: 'Hủy lô quá hạn / không đạt kiểm tra chất lượng',
        }),
      `Đã chuyển lô ${lot.lot_id} sang trạng thái hủy.`
    )
  }

  return (
    <section className="warehouse-view">
      <div className="page-header">
        <div className="page-title-group">
          <h1>Quản lý kho nông sản</h1>
          <div className="meta-strip">
            <span>Lưu trữ JSON: <b className="mono">output/warehouse_inventory.json</b></span>
            <span className="meta-sep">·</span>
            <span>Cảnh báo hạn dùng: <b>Trước {summary.warn_before_days} ngày</b></span>
            <span className="meta-sep">·</span>
            <span>Nguyên tắc xuất: <b>FEFO (Hết hạn trước xuất trước)</b></span>
          </div>
        </div>
        <div className="header-telemetry">
          <a className="btn btn-secondary" href="/api/warehouse/export.csv">
            Xuất CSV tồn kho
          </a>
        </div>
      </div>

      {feedback && (
        <div className={`wh-feedback ${feedback.tone}`} role="status">
          <span>{feedback.text}</span>
          <button type="button" className="wh-feedback-close" onClick={() => setFeedback(null)}>
            Đóng
          </button>
        </div>
      )}

      {/* Prominent 2-day Expiry Inspection Alert Banner */}
      <section className={`expiry-alert-box ${expiryAlerts.length ? 'has-alerts' : 'all-clear'}`}>
        <div className="expiry-alert-head">
          <div>
            <h2>
              {expiryAlerts.length
                ? `Cảnh báo kiểm tra hạn sử dụng (${expiryAlerts.length} lô cần chú ý)`
                : 'Trạng thái hạn sử dụng ổn định'}
            </h2>
            <p>
              {expiryAlerts.length
                ? 'Các lô còn ≤ 2 ngày sử dụng hoặc đã quá hạn được tự động đánh dấu để nhân viên kiểm tra chất lượng trước khi xuất.'
                : 'Hiện chưa có lô hàng nào sắp hết hạn trong vòng 2 ngày tới.'}
            </p>
          </div>
          {summary.uninspected_alert_count > 0 && (
            <span className="alert-count-pill">
              {summary.uninspected_alert_count} lô chưa kiểm tra
            </span>
          )}
        </div>

        {expiryAlerts.length > 0 && (
          <div className="expiry-alert-list">
            {expiryAlerts.map(alert => {
              const lot = lots.find(l => l.lot_id === alert.lot_id)
              return (
                <div
                  key={alert.id}
                  className={`expiry-alert-item ${alert.severity} ${alert.inspected ? 'inspected' : ''}`}
                >
                  <div className="expiry-alert-info">
                    <div className="expiry-alert-title">
                      <span className={`result-pill ${alert.severity === 'critical' ? 'bad' : 'warn'}`}>
                        {alert.severity === 'critical' ? 'Quá hạn' : 'Sắp hết hạn ≤ 2 ngày'}
                      </span>
                      <strong className="mono">{alert.lot_id}</strong>
                      <span>· {alert.fruit_label}</span>
                      <span className="mono">({alert.remaining_qty} quả · {alert.remaining_text})</span>
                      {alert.inspected && (
                        <span className="inspected-tag">Đã kiểm tra</span>
                      )}
                    </div>
                    <p className="expiry-alert-msg">{alert.message}</p>
                  </div>
                  {lot && (
                    <div className="expiry-alert-actions">
                      {!alert.inspected && (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={busy}
                          onClick={() => handleInspect(lot)}
                        >
                          Đánh dấu đã kiểm tra
                        </button>
                      )}
                      {alert.severity !== 'critical' && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() => handleQuickDispatchLot(lot)}
                        >
                          Xuất ưu tiên
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        disabled={busy}
                        onClick={() => handleDispose(lot)}
                      >
                        Hủy lô
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* Warehouse KPIs */}
      <section className="kpi-grid wh-kpi-grid" aria-label="Chỉ số kho">
        <article className="kpi-card neutral">
          <div className="kpi-top">
            <span className="kpi-label">Tổng tồn kho đạt chuẩn</span>
          </div>
          <div className="kpi-value">{summary.total_in_stock.toLocaleString('vi-VN')}</div>
          <div className="kpi-detail">Khối lượng ước tính {summary.total_weight_kg} kg</div>
        </article>

        <article className="kpi-card good">
          <div className="kpi-top">
            <span className="kpi-label">Số lô đang lưu</span>
          </div>
          <div className="kpi-value">{summary.active_lots_count}</div>
          <div className="kpi-detail">Tự động đồng bộ từ băng chuyền</div>
        </article>

        <article className={`kpi-card ${summary.expired_count > 0 ? 'bad' : summary.expiring_soon_count > 0 ? 'warn' : 'good'}`}>
          <div className="kpi-top">
            <span className="kpi-label">Cảnh báo hạn dùng (≤ 2 ngày)</span>
            {summary.uninspected_alert_count > 0 && (
              <span className="kpi-badge warn">{summary.uninspected_alert_count} chưa KT</span>
            )}
          </div>
          <div className="kpi-value">{summary.alert_lots_count}</div>
          <div className="kpi-detail">
            {summary.expiring_soon_count} sắp hết hạn · {summary.expired_count} quá hạn
          </div>
        </article>

        <article className="kpi-card neutral">
          <div className="kpi-top">
            <span className="kpi-label">Tỷ lệ lấp đầy kho lạnh</span>
          </div>
          <div className="kpi-value">{summary.utilization_pct}%</div>
          <div className="kpi-detail">Hàng loại chờ xử lý: {summary.rejected_hold_qty} quả</div>
        </article>
      </section>

      {/* Cold Storage Zone Map */}
      <section className="panel wh-section">
        <div className="panel-header">
          <div className="panel-title">
            <h2>Sơ đồ sức chứa các khu kho lạnh</h2>
            <p>Phân bổ tự động theo loại nông sản và cổng phân loại trên băng chuyền</p>
          </div>
        </div>
        <div className="zone-grid">
          {zones.map(zone => {
            const barTone =
              zone.id === 'ZONE_REJECT'
                ? 'bad'
                : zone.utilization_pct >= 85
                ? 'warn'
                : 'good'
            return (
              <div key={zone.id} className={`zone-card ${zone.near_full ? 'near-full' : ''}`}>
                <div className="zone-top">
                  <strong>{zone.name}</strong>
                  <span className="zone-temp">{zone.temp}</span>
                </div>
                <div className="zone-numbers tnum">
                  <b>{zone.used}</b>
                  <span>/ {zone.capacity} quả ({zone.weight_kg} kg)</span>
                </div>
                <div className="zone-bar-track">
                  <div
                    className={`zone-bar-fill ${barTone}`}
                    style={{ width: `${Math.min(100, zone.utilization_pct)}%` }}
                  />
                </div>
                <div className="zone-foot">
                  <span>Lấp đầy {zone.utilization_pct}%</span>
                  {zone.near_full && <span className="zone-warn-text">Sắp đầy kho</span>}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* Quick Actions: FEFO Dispatch & Manual Import */}
      <section className="wh-actions-grid">
        <article className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <h2>Xuất kho tự động (FEFO)</h2>
              <p>Tự động ưu tiên trừ từ lô sắp hết hạn nhất trước</p>
            </div>
          </div>
          <form className="wh-form" onSubmit={handleDispatchSubmit}>
            <div className="wh-form-row">
              <label>
                <span>Loại nông sản</span>
                <select value={dispatchFruit} onChange={e => setDispatchFruit(e.target.value)}>
                  {FRUIT_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Số lượng xuất (tối đa {maxDispatchQty} quả)</span>
                <input
                  type="number"
                  min="1"
                  max={Math.max(1, maxDispatchQty)}
                  value={dispatchQty}
                  onChange={e => setDispatchQty(e.target.value)}
                  required
                />
                {maxDispatchQty === 0 ? (
                  <small className="field-error">Loại nông sản này hiện đã hết tồn kho.</small>
                ) : dispatchQtyExceeds ? (
                  <small className="field-error">
                    Không được vượt quá tồn kho hiện có ({maxDispatchQty} quả).
                  </small>
                ) : null}
              </label>
            </div>
            <label>
              <span>Ghi chú / Đơn vị nhận <b className="req-mark">*</b></span>
              <input
                type="text"
                placeholder="Bắt buộc — VD: Giao siêu thị WinMart, Đơn hàng #102..."
                value={dispatchNote}
                onChange={e => setDispatchNote(e.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !dispatchNote.trim() || maxDispatchQty <= 0 || parsedDispatchQty <= 0 || dispatchQtyExceeds}
            >
              Xuất kho theo FEFO
            </button>
          </form>
        </article>

        <article className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <h2>Nhập kho thủ công / Tạo lô kiểm thử</h2>
              <p>Nhập HSD ≤ 2 ngày để kiểm tra ngay cảnh báo sắp hết hạn</p>
            </div>
          </div>
          <form className="wh-form" onSubmit={handleImportSubmit}>
            <div className="wh-form-row">
              <label>
                <span>Loại nông sản</span>
                <select
                  value={importFruit}
                  onChange={e => {
                    const next = e.target.value
                    setImportFruit(next)
                  }}
                >
                  {FRUIT_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Số lượng (quả)</span>
                <input
                  type="number"
                  min="1"
                  value={importQty}
                  onChange={e => setImportQty(e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Hạn sử dụng (ngày)</span>
                <input
                  type="number"
                  min="0.5"
                  step="0.5"
                  value={importDays}
                  onChange={e => setImportDays(e.target.value)}
                  required
                />
              </label>
            </div>
            <div className="wh-form-row">
              <label>
                <span>Mã lô tiếp theo (tự động)</span>
                <input
                  type="text"
                  className="mono"
                  value={(() => {
                    let maxNum = 0
                    for (const lot of lots) {
                      for (const field of [lot.batch_id, lot.lot_id]) {
                        const m = String(field || '').trim().match(/^(?:LOT-)?MAN-(\d+)$/i)
                        if (m) maxNum = Math.max(maxNum, parseInt(m[1], 10))
                      }
                    }
                    return `LOT-MAN-${String(maxNum + 1).padStart(3, '0')}`
                  })()}
                  readOnly
                />
              </label>
              <label>
                <span>Ghi chú</span>
                <input
                  type="text"
                  placeholder="VD: Lô nhập từ vườn Đà Lạt..."
                  value={importNote}
                  onChange={e => setImportNote(e.target.value)}
                />
              </label>
            </div>
            <button type="submit" className="btn btn-secondary" disabled={busy}>
              Thêm lô vào kho
            </button>
          </form>
        </article>
      </section>

      {/* Lots Table */}
      <section className="panel wh-section">
        <div className="panel-header">
          <div className="panel-title">
            <h2>Danh sách lô hàng trong kho</h2>
            <p>Sắp xếp ưu tiên theo lô quá hạn / sắp hết hạn (FEFO)</p>
          </div>
          <div className="segmented">
            <button type="button" className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>
              Tất cả ({lots.length})
            </button>
            <button type="button" className={filter === 'alert' ? 'active' : ''} onClick={() => setFilter('alert')}>
              Cần kiểm tra ({summary.alert_lots_count})
            </button>
            <button type="button" className={filter === 'fresh' ? 'active' : ''} onClick={() => setFilter('fresh')}>
              Còn hạn
            </button>
            <button type="button" className={filter === 'closed' ? 'active' : ''} onClick={() => setFilter('closed')}>
              Đã xuất / Hủy
            </button>
          </div>
        </div>
        <div className="table-wrap">
          {filteredLots.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Mã lô</th>
                  <th>Sản phẩm / Khu</th>
                  <th>Tồn / Nhập</th>
                  <th>Hạn sử dụng</th>
                  <th>Trạng thái</th>
                  <th>Kiểm tra chất lượng</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {filteredLots.map(lot => {
                  const badge = expiryBadge(lot)
                  const isActive = lot.remaining_qty > 0 && lot.expiry_state !== 'disposed'
                  return (
                    <tr key={lot.lot_id} className={lot.needs_inspection ? `row-${lot.expiry_state}` : ''}>
                      <td>
                        <strong className="mono">{lot.lot_id}</strong>
                        <div className="sub-cell">{lot.source === 'conveyor' ? 'Từ băng chuyền' : 'Nhập thủ công'}</div>
                      </td>
                      <td>
                        <strong>{lot.fruit_label}</strong>
                        <div className="sub-cell">{lot.zone_id}</div>
                      </td>
                      <td className="tnum">
                        <strong>{lot.remaining_qty}</strong> / {lot.imported_qty} quả
                        <div className="sub-cell">{lot.weight_kg} kg</div>
                      </td>
                      <td>
                        <div className="mono">
                          {lot.expires_at ? new Date(lot.expires_at).toLocaleDateString('vi-VN') : '—'}
                        </div>
                        <div className="sub-cell">{lot.remaining_text}</div>
                      </td>
                      <td>
                        <span className={`result-pill ${badge.tone}`}>{badge.text}</span>
                      </td>
                      <td>
                        {lot.inspected ? (
                          <div>
                            <span className="inspected-tag">Đã kiểm tra</span>
                            <div className="sub-cell">
                              {new Date(lot.inspected_at).toLocaleTimeString('vi-VN')}
                            </div>
                          </div>
                        ) : lot.needs_inspection ? (
                          <span className="pending-inspect">Chờ kiểm tra</span>
                        ) : (
                          <span className="sub-cell">Chưa cần</span>
                        )}
                      </td>
                      <td>
                        {isActive ? (
                          <div className="row-actions">
                            {lot.needs_inspection && !lot.inspected && (
                              <button
                                type="button"
                                className="btn btn-primary btn-xs"
                                disabled={busy}
                                onClick={() => handleInspect(lot)}
                              >
                                Kiểm tra
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn btn-secondary btn-xs"
                              disabled={busy}
                              onClick={() => handleQuickDispatchLot(lot)}
                            >
                              Xuất hết
                            </button>
                            <button
                              type="button"
                              className="btn btn-danger btn-xs"
                              disabled={busy}
                              onClick={() => handleDispose(lot)}
                            >
                              Hủy
                            </button>
                          </div>
                        ) : (
                          <span className="sub-cell">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">Chưa có lô hàng nào trong mục này.</div>
          )}
        </div>
      </section>

      {/* Transaction History */}
      <section className="panel wh-section">
        <div className="panel-header">
          <div className="panel-title">
            <h2>Lịch sử giao dịch kho gần đây</h2>
            <p>Ghi nhận mọi thao tác nhập, xuất FEFO, kiểm tra và hủy lô</p>
          </div>
          <span className="panel-meta tnum">{transactions.length} giao dịch</span>
        </div>
        <div className="table-wrap">
          {transactions.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Loại</th>
                  <th>Mã lô</th>
                  <th>Sản phẩm</th>
                  <th>Số lượng</th>
                  <th>Ghi chú</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map(tx => {
                  const badge = txBadge(tx.type)
                  return (
                    <tr key={tx.id}>
                      <td className="mono">
                        {tx.created_at ? new Date(tx.created_at).toLocaleString('vi-VN') : '—'}
                      </td>
                      <td>
                        <span className={`result-pill ${badge.tone}`}>{badge.text}</span>
                      </td>
                      <td className="mono">{tx.lot_id}</td>
                      <td>{tx.fruit_label}</td>
                      <td className="tnum"><strong>{tx.qty}</strong> quả</td>
                      <td>{tx.note}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">Chưa có giao dịch kho nào được ghi nhận.</div>
          )}
        </div>
      </section>
      {quickDispatchLot && (
        <div
          className="modal-backdrop"
          onClick={() => setQuickDispatchLot(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Xác nhận xuất kho theo lô"
        >
          <div className="modal-card wh-modal-card" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Xuất lô {quickDispatchLot.lot_id}</h3>
              <button
                type="button"
                className="modal-close"
                onClick={() => setQuickDispatchLot(null)}
                aria-label="Đóng"
              >
                ✕
              </button>
            </div>
            <form className="wh-form" onSubmit={confirmQuickDispatch}>
              <p className="wh-modal-desc">
                Tồn kho lô <strong>{quickDispatchLot.lot_id}</strong> ({quickDispatchLot.fruit_label}):{' '}
                <strong>{quickDispatchLot.remaining_qty} / {quickDispatchLot.imported_qty} quả</strong>.
              </p>
              <label>
                <span>Số lượng xuất (tối đa {quickDispatchLot.remaining_qty} quả) <b className="req-mark">*</b></span>
                <input
                  type="number"
                  min="1"
                  max={quickDispatchLot.remaining_qty}
                  value={quickDispatchQty}
                  onChange={e => setQuickDispatchQty(e.target.value)}
                  required
                />
                {(parseInt(quickDispatchQty, 10) || 0) > quickDispatchLot.remaining_qty && (
                  <small className="field-error">
                    Số lượng xuất không được vượt quá tồn của lô ({quickDispatchLot.remaining_qty} quả).
                  </small>
                )}
              </label>
              <label>
                <span>Ghi chú / Đơn vị nhận <b className="req-mark">*</b></span>
                <input
                  type="text"
                  autoFocus
                  placeholder="Bắt buộc — VD: Giao siêu thị Co.opmart, Khách lẻ..."
                  value={quickDispatchNote}
                  onChange={e => setQuickDispatchNote(e.target.value)}
                  required
                />
              </label>
              <div className="wh-modal-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setQuickDispatchLot(null)}
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={
                    busy ||
                    !quickDispatchNote.trim() ||
                    (parseInt(quickDispatchQty, 10) || 0) <= 0 ||
                    (parseInt(quickDispatchQty, 10) || 0) > quickDispatchLot.remaining_qty
                  }
                >
                  Xác nhận xuất kho
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  )
}
