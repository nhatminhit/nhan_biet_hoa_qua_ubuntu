import { useEffect, useMemo, useState } from 'react'
import WarehouseView from './WarehouseView'

const emptyStats = {
  running: false,
  source: 'Chưa kết nối',
  total: 0,
  good: 0,
  rejected: 0,
  defect_rate: 0,
  fps: 0,
  latency_ms: 0,
  active_tracks: 0,
  uptime_seconds: 0,
  events: [],
  history: [],
  error: null,
  gui_online: false,
  updated_at: null,
  paused: false,
  batch: { id: 'DEMO-001', fruit: 'Trái cây' },
  fruit_breakdown: {},
  waste_kg: 0,
  estimated_loss_vnd: 0,
}

function api(path, options) {
  return fetch(path, options).then(async response => {
    const body = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(body.detail || 'Không thể kết nối máy chủ')
    return body
  })
}

function formatUptime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0))
  const h = String(Math.floor(s / 3600)).padStart(2, '0')
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0')
  const sec = String(s % 60).padStart(2, '0')
  return `${h}:${m}:${sec}`
}

function BrandMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <path d="M14 17.5l2.2 2.2L21 15" />
    </svg>
  )
}

function ActivityIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="22 12 18 12 15 20 9 4 6 12 2 12" />
    </svg>
  )
}

function HistoryIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15.5 14" />
    </svg>
  )
}

function WarehouseIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 9.5L12 4l9 5.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9.5z" />
      <path d="M8 21v-7h8v7" />
      <path d="M8 10h8" />
    </svg>
  )
}

function ExternalIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 3h7v7" />
      <path d="M10 14L21 3" />
      <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

function KpiCard({ label, value, detail, tone = 'neutral', badge }) {
  return (
    <article className={`kpi-card ${tone}`}>
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        {badge && <span className={`kpi-badge ${tone}`}>{badge}</span>}
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-detail">{detail}</div>
    </article>
  )
}

function ThroughputChart({ history, good, rejected, total, stats }) {
  const chart = useMemo(() => {
    const W = 640
    const H = 200
    const padL = 38
    const padR = 12
    const padT = 14
    const padB = 22
    const innerW = W - padL - padR
    const innerH = H - padT - padB

    if (!history.length) {
      return { W, H, padL, padR, padT, padB, innerH, max: 10, totalPoints: '', rejectedPoints: '', areaPoints: '' }
    }

    const rawMax = Math.max(1, ...history.map(p => Number(p.total || 0)))
    const max = rawMax <= 10 ? Math.max(4, Math.ceil(rawMax / 2) * 2) : Math.ceil(rawMax / 5) * 5

    const toCoords = key =>
      history.map((p, idx) => {
        const x = history.length === 1 ? padL + innerW : padL + (idx / (history.length - 1)) * innerW
        const val = Number(p[key] || 0)
        const y = padT + innerH - (val / max) * innerH
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })

    const totalCoords = toCoords('total')
    const rejectedCoords = toCoords('rejected')
    const firstX = history.length === 1 ? padL + innerW : padL
    const lastX = padL + innerW
    const baseY = padT + innerH

    return {
      W,
      H,
      padL,
      padR,
      padT,
      padB,
      innerH,
      max,
      totalPoints: totalCoords.join(' '),
      rejectedPoints: rejectedCoords.join(' '),
      areaPoints: `${firstX},${baseY} ${totalCoords.join(' ')} ${lastX},${baseY}`,
    }
  }, [history])

  const goodPct = total ? Math.round((good / total) * 1000) / 10 : 0
  const badPct = total ? Math.round((rejected / total) * 1000) / 10 : 0
  const yTicks = [0, 0.5, 1]

  return (
    <article className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <h2>Biểu đồ sản lượng theo thời gian</h2>
          <p>Lũy kế sản phẩm qua vạch đếm trong phiên hiện tại</p>
        </div>
        <div className="chart-legend">
          <span className="legend-item"><i className="legend-swatch" />Tổng kiểm tra</span>
          <span className="legend-item"><i className="legend-swatch bad" />Quả hỏng</span>
        </div>
      </div>
      <div className="panel-body">
        <div className="chart-wrap">
          <svg viewBox={`0 0 ${chart.W} ${chart.H}`} preserveAspectRatio="none" aria-label="Biểu đồ sản lượng">
            <defs>
              <linearGradient id="fgAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0f766e" stopOpacity="0.16" />
                <stop offset="100%" stopColor="#0f766e" stopOpacity="0.01" />
              </linearGradient>
            </defs>
            {yTicks.map(ratio => {
              const y = chart.padT + chart.innerH * (1 - ratio)
              const label = Math.round(chart.max * ratio)
              return (
                <g key={ratio}>
                  <line
                    x1={chart.padL}
                    x2={chart.W - chart.padR}
                    y1={y}
                    y2={y}
                    className="chart-gridline"
                  />
                  <text x={chart.padL - 8} y={y + 3.5} textAnchor="end" className="chart-axis-text">
                    {label}
                  </text>
                </g>
              )
            })}
            {chart.totalPoints && (
              <>
                <polygon points={chart.areaPoints} fill="url(#fgAreaGrad)" />
                <polyline points={chart.totalPoints} className="chart-line" />
                <polyline points={chart.rejectedPoints} className="chart-line-bad" />
              </>
            )}
          </svg>
          {!history.length && (
            <div className="chart-empty">Chưa có dữ liệu sản lượng trong phiên hiện tại.</div>
          )}
        </div>

        <div className="quality-bar-block">
          <div className="quality-bar-header">
            <span>Phân bố chất lượng lô hiện tại</span>
            <strong>Đạt {goodPct}% · Loại {badPct}%</strong>
          </div>
          <div className="quality-track" role="img" aria-label={`Đạt ${goodPct}%, loại ${badPct}%`}>
            <div className="quality-good" style={{ width: `${goodPct}%` }} />
            <div className="quality-bad" style={{ width: `${badPct}%` }} />
          </div>
        </div>

        <div className="runtime-strip">
          <span>Ứng dụng điều khiển: <code>app_gui.py</code></span>
          <span>Chế độ: <strong>Phân loại nhị phân (Lành / Hỏng)</strong></span>
          <span>Đồng bộ lúc: <strong className="mono">{stats.updated_at ? new Date(stats.updated_at).toLocaleTimeString('vi-VN') : '—'}</strong></span>
        </div>
      </div>
    </article>
  )
}

function EvidenceModal({ item, onClose }) {
  const [mode, setMode] = useState(item?.explanation_url ? 'explanation' : 'raw')

  useEffect(() => {
    setMode(item?.explanation_url ? 'explanation' : 'raw')
  }, [item])

  useEffect(() => {
    if (!item) return
    const onKey = e => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [item, onClose])

  if (!item) return null
  const src = mode === 'explanation' && item.explanation_url ? item.explanation_url : item.url

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="Chi tiết ảnh bằng chứng">
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Chi tiết sản phẩm bị loại</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Đóng">
            <CloseIcon />
          </button>
        </div>
        <div className="modal-media">
          <img src={src} alt="Ảnh bằng chứng phân loại" />
        </div>
        <div className="modal-footer">
          <div>
            <span className="mono">{item.name}</span>
            {' · '}
            <span>{new Date(item.created_at).toLocaleString('vi-VN')}</span>
          </div>
          {item.explanation_url && (
            <div className="segmented">
              <button
                type="button"
                className={mode === 'explanation' ? 'active' : ''}
                onClick={() => setMode('explanation')}
              >
                Vùng nhận diện lỗi
              </button>
              <button
                type="button"
                className={mode === 'raw' ? 'active' : ''}
                onClick={() => setMode('raw')}
              >
                Ảnh gốc
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EvidenceGrid({ items, onSelect, emptyText = 'Chưa có ảnh sản phẩm bị loại nào được lưu trong phiên này.' }) {
  return (
    <div className="evidence-grid">
      {items.length ? (
        items.map(item => (
          <figure
            className="evidence-card"
            key={item.name}
            onClick={() => onSelect(item)}
            tabIndex={0}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect(item)
              }
            }}
          >
            <div className="evidence-thumb">
              <img src={item.explanation_url || item.url} alt="Sản phẩm bị loại" loading="lazy" />
              <span className="evidence-tag">
                {item.explanation_url ? 'Phân tích vùng lỗi' : 'Ảnh gốc'}
              </span>
            </div>
            <figcaption>
              <div className="evidence-title">
                <b>Quả hỏng — Loại bỏ</b>
              </div>
              <span className="evidence-note">
                {item.explanation_url ? 'Vùng đánh dấu: dấu hiệu thâm/nâu' : 'Ghi nhận tại vạch kiểm tra'}
              </span>
              <time className="evidence-time">
                {new Date(item.created_at).toLocaleString('vi-VN')}
              </time>
            </figcaption>
          </figure>
        ))
      ) : (
        <div className="empty-box">{emptyText}</div>
      )}
    </div>
  )
}

function SessionHistory({ onSelectImage }) {
  const [sessions, setSessions] = useState([])
  const [selected, setSelected] = useState(null)
  const [logs, setLogs] = useState([])
  const [sessionRejections, setSessionRejections] = useState([])
  const [query, setQuery] = useState('')

  useEffect(() => {
    api('/api/sessions')
      .then(items => {
        setSessions(items)
        if (items.length) setSelected(items[0])
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selected) return
    const encoded = encodeURIComponent(selected.batch_id)
    api(`/api/sessions/${encoded}/logs`)
      .then(setLogs)
      .catch(() => setLogs([]))
    api(`/api/rejections?limit=200&batch_id=${encoded}`)
      .then(setSessionRejections)
      .catch(() => setSessionRejections([]))
  }, [selected])

  const filteredSessions = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sessions
    return sessions.filter(
      s =>
        String(s.batch_id || '').toLowerCase().includes(q) ||
        String(s.batch_fruit || '').toLowerCase().includes(q)
    )
  }, [sessions, query])

  return (
    <section>
      <div className="page-header">
        <div className="page-title-group">
          <h1>Lịch sử phiên kiểm tra</h1>
          <div className="meta-strip">
            <span>Truy xuất kết quả phân loại, tỷ lệ hư hỏng và báo cáo theo từng mã lô</span>
          </div>
        </div>
        <div className="header-telemetry">
          <span className="tele-pill">
            Tổng phiên đã lưu <strong>{sessions.length}</strong>
          </span>
        </div>
      </div>

      <div className="history-layout">
        <aside className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <h2>Danh sách lô hàng</h2>
            </div>
            <span className="panel-meta tnum">{filteredSessions.length} lô</span>
          </div>
          <div className="sidebar-search">
            <input
              type="search"
              placeholder="Tìm theo mã lô..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
          <div className="session-list-scroll">
            {filteredSessions.length ? (
              filteredSessions.map(session => (
                <button
                  type="button"
                  key={session.batch_id}
                  className={`session-item ${selected?.batch_id === session.batch_id ? 'selected' : ''}`}
                  onClick={() => setSelected(session)}
                >
                  <div className="session-item-top">
                    <strong>{session.batch_id}</strong>
                    <span className="session-item-count">{session.total} sp</span>
                  </div>
                  <div className="session-item-sub">
                    <span>{session.batch_fruit} · Hỏng {session.defect_rate}%</span>
                    <time className="mono">
                      {session.started_at
                        ? new Date(session.started_at).toLocaleDateString('vi-VN')
                        : '—'}
                    </time>
                  </div>
                </button>
              ))
            ) : (
              <div className="empty-state">Không tìm thấy phiên kiểm tra phù hợp.</div>
            )}
          </div>
        </aside>

        <div className="panel">
          {selected ? (
            <>
              <div className="detail-header">
                <div>
                  <h2>{selected.batch_id}</h2>
                  <p>
                    {selected.batch_fruit}
                    {' · '}
                    {selected.started_at
                      ? new Date(selected.started_at).toLocaleString('vi-VN')
                      : 'Không rõ thời gian'}
                  </p>
                </div>
                <div className="action-group">
                  <a
                    className="btn btn-primary"
                    target="_blank"
                    rel="noreferrer"
                    href={`/api/sessions/${encodeURIComponent(selected.batch_id)}/report.html`}
                  >
                    <ExternalIcon />
                    Xem báo cáo cuối phiên
                  </a>
                  <a
                    className="btn btn-secondary"
                    href={`/api/sessions/${encodeURIComponent(selected.batch_id)}/export.csv`}
                  >
                    <DownloadIcon />
                    Xuất CSV
                  </a>
                </div>
              </div>

              <div className="detail-metrics">
                <div className="detail-metric">
                  <span>Tổng kiểm tra</span>
                  <strong>{selected.total.toLocaleString('vi-VN')}</strong>
                </div>
                <div className="detail-metric">
                  <span>Đạt chuẩn</span>
                  <strong className="good">{selected.good.toLocaleString('vi-VN')}</strong>
                </div>
                <div className="detail-metric">
                  <span>Tỷ lệ hư hỏng</span>
                  <strong className="bad">{selected.defect_rate}%</strong>
                </div>
                <div className="detail-metric">
                  <span>Nguy cơ lãng phí</span>
                  <strong className="warn">{selected.waste_kg} kg</strong>
                </div>
                <div className="detail-metric">
                  <span>Thất thoát ước tính</span>
                  <strong>{Number(selected.estimated_loss_vnd).toLocaleString('vi-VN')} ₫</strong>
                </div>
              </div>

              <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
                <div className="section-header" style={{ marginBottom: 12 }}>
                  <h3>Ảnh quả hỏng bị loại · {selected.batch_id}</h3>
                  <span className="tnum">{sessionRejections.length} ảnh đã lưu · Nhấn để phóng to</span>
                </div>
                <div style={{ maxHeight: 440, overflowY: 'auto', paddingRight: 4 }}>
                  <EvidenceGrid
                    items={sessionRejections}
                    onSelect={onSelectImage}
                    emptyText={`Phiên ${selected.batch_id} chưa có ảnh sản phẩm bị loại.`}
                  />
                </div>
              </div>

              <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
                {logs.length ? (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Thời gian</th>
                        <th>Kết quả phân loại</th>
                        <th>Độ tin cậy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {logs.map((log, index) => {
                        const confPct = log.confidence ? Math.min(100, Math.round(log.confidence * 100)) : null
                        const tone = log.quality === 'rejected' ? 'bad' : log.quality === 'good' ? 'good' : 'neutral'
                        const label =
                          log.quality === 'rejected'
                            ? 'Quả hỏng — Loại bỏ'
                            : log.quality === 'good'
                            ? 'Quả lành — Đạt chuẩn'
                            : 'Không xác định'
                        return (
                          <tr key={`${log.created_at}-${index}`}>
                            <td className="mono">
                              {log.created_at
                                ? new Date(log.created_at).toLocaleTimeString('vi-VN')
                                : log.time || '—'}
                            </td>
                            <td>
                              <span className={`result-pill ${tone}`}>{label}</span>
                            </td>
                            <td>
                              {confPct !== null ? (
                                <span className="conf-cell">
                                  <span className="conf-bar"><i style={{ width: `${confPct}%` }} /></span>
                                  {confPct}%
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty-state">Phiên này chưa có nhật ký chi tiết theo từng sản phẩm.</div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-state">Chọn một lô hàng ở cột bên trái để xem chi tiết.</div>
          )}
        </div>
      </div>
    </section>
  )
}

export default function App() {
  const [stats, setStats] = useState(emptyStats)
  const [rejections, setRejections] = useState([])
  const [warehouse, setWarehouse] = useState(null)
  const [notice, setNotice] = useState('')
  const [view, setView] = useState('live')
  const [activeImage, setActiveImage] = useState(null)

  const currentBatchId = stats.batch?.id || ''

  const fetchRejections = batchId => {
    if (!batchId) {
      setRejections([])
      return Promise.resolve()
    }
    return api(`/api/rejections?limit=24&batch_id=${encodeURIComponent(batchId)}`)
      .then(setRejections)
      .catch(() => {})
  }

  const refresh = () =>
    api('/api/stats')
      .then(data => {
        setStats(data)
        setNotice('')
        fetchRejections(data?.batch?.id || '')
      })
      .catch(error => setNotice(error.message))

  const refreshWarehouse = () =>
    api('/api/warehouse')
      .then(setWarehouse)
      .catch(() => {})

  useEffect(() => {
    refresh()
    refreshWarehouse()
    const timer = setInterval(() => {
      refresh()
      refreshWarehouse()
    }, 1500)
    return () => clearInterval(timer)
  }, [])

  const uptime = formatUptime(stats.uptime_seconds)
  const standardRate = stats.total ? Math.round((stats.good / stats.total) * 1000) / 10 : 0
  const runStateClass = stats.running ? (stats.paused ? 'paused' : 'running') : ''
  const runStateLabel = stats.running ? (stats.paused ? 'Đang tạm dừng' : 'Đang vận hành') : 'Đang dừng'
  const alertLotsCount = warehouse?.summary?.alert_lots_count || 0
  const uninspectedCount = warehouse?.summary?.uninspected_alert_count || 0

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="topbar-left">
            <div className="brand">
              <div className="brand-mark">
                <BrandMark />
              </div>
              <div className="brand-text">
                <strong>FruitGuard</strong>
                <span>Giám sát chất lượng &amp; quản lý kho</span>
              </div>
            </div>

            <nav className="view-nav" aria-label="Điều hướng chính">
              <button
                type="button"
                className={view === 'live' ? 'active' : ''}
                onClick={() => setView('live')}
              >
                <ActivityIcon />
                Giám sát trực tiếp
              </button>
              <button
                type="button"
                className={view === 'warehouse' ? 'active' : ''}
                onClick={() => setView('warehouse')}
              >
                <WarehouseIcon />
                Quản lý kho
                {alertLotsCount > 0 && (
                  <span className={`nav-badge ${uninspectedCount > 0 ? 'urgent' : ''}`}>
                    {alertLotsCount}
                  </span>
                )}
              </button>
              <button
                type="button"
                className={view === 'history' ? 'active' : ''}
                onClick={() => setView('history')}
              >
                <HistoryIcon />
                Lịch sử phiên
              </button>
            </nav>
          </div>

          <div className="topbar-right">
            <div className={`status-chip ${stats.gui_online ? 'online' : ''}`}>
              <span className="dot" />
              {stats.gui_online ? 'GUI đang kết nối' : 'GUI ngoại tuyến'}
            </div>
            <span className="readonly-tag">Kho JSON · FEFO</span>
          </div>
        </div>
      </header>

      <main>
        {view === 'live' ? (
          <>
            {alertLotsCount > 0 && (
              <div className="global-expiry-banner" role="alert">
                <div>
                  <strong>Cảnh báo kho (trước hạn 2 ngày):</strong>{' '}
                  Hiện có <b>{alertLotsCount} lô hàng</b> sắp hết hạn hoặc đã quá hạn
                  {uninspectedCount > 0 ? ` (${uninspectedCount} lô chưa kiểm tra)` : ''}.
                </div>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setView('warehouse')}
                >
                  Kiểm tra kho ngay
                </button>
              </div>
            )}
            <div className="page-header">
              <div className="page-title-group">
                <h1>Giám sát dây chuyền phân loại</h1>
                <div className="meta-strip">
                  <span>Mã lô: <b className="mono">{stats.batch?.id || 'Chưa tạo lô'}</b></span>
                  <span className="meta-sep">·</span>
                  <span>Sản phẩm: <b>{stats.batch?.fruit || 'Trái cây'}</b></span>
                  <span className="meta-sep">·</span>
                  <span>Nguồn: <b>{stats.source}</b></span>
                </div>
              </div>

              <div className="header-telemetry">
                <span className={`run-badge ${runStateClass}`}>
                  <i />
                  {runStateLabel}
                </span>
                <span className="tele-pill">FPS <strong>{stats.fps}</strong></span>
                <span className="tele-pill">Độ trễ <strong>{stats.latency_ms} ms</strong></span>
                <span className="tele-pill">Theo dõi <strong>{stats.active_tracks}</strong></span>
              </div>
            </div>

            {(notice || stats.error) && (
              <div className="alert" role="alert">
                {notice || stats.error}
              </div>
            )}

            <section className="kpi-grid" aria-label="Chỉ số tổng quan">
              <KpiCard
                label="Tổng đã kiểm tra"
                value={stats.total.toLocaleString('vi-VN')}
                detail={`Thời gian chạy ${uptime}`}
              />
              <KpiCard
                label="Đạt chuẩn (Quả lành)"
                value={stats.good.toLocaleString('vi-VN')}
                badge={`${standardRate}%`}
                tone="good"
                detail="Đủ điều kiện đóng gói"
              />
              <KpiCard
                label="Loại bỏ (Quả hỏng)"
                value={stats.rejected.toLocaleString('vi-VN')}
                badge={`${stats.defect_rate}%`}
                tone="bad"
                detail="Đã ghi nhận ảnh bằng chứng"
              />
              <KpiCard
                label="Nguy cơ lãng phí"
                value={`${Number(stats.waste_kg).toLocaleString('vi-VN')} kg`}
                tone="warn"
                detail="Ước tính từ khối lượng TB"
              />
              <KpiCard
                label="Thất thoát ước tính"
                value={`${Number(stats.estimated_loss_vnd).toLocaleString('vi-VN')} ₫`}
                tone="bad"
                detail="Giá trị cần xử lý sớm"
              />
            </section>

            <section className="work-grid">
              <ThroughputChart
                history={stats.history}
                good={stats.good}
                rejected={stats.rejected}
                total={stats.total}
                stats={stats}
              />

              <article className="panel">
                <div className="panel-header">
                  <div className="panel-title">
                    <h2>Nhật ký sự kiện gần đây</h2>
                    <p>Cập nhật tự động mỗi giây từ bộ đếm</p>
                  </div>
                  <span className="panel-meta tnum">{stats.events.length} mục</span>
                </div>
                <div className="event-list">
                  {stats.events.length ? (
                    stats.events.map((event, index) => {
                      const isBad = String(event).toUpperCase().includes('HONG')
                      return (
                        <div className="event-row" key={`${event}-${index}`}>
                          <span className={`event-dot ${isBad ? 'bad' : ''}`} />
                          <span className="event-text">{event}</span>
                        </div>
                      )
                    })
                  ) : (
                    <div className="empty-state">Chưa có sản phẩm đi qua vạch đếm.</div>
                  )}
                </div>
              </article>
            </section>

            <section>
              <div className="section-header">
                <h2>
                  Ảnh bằng chứng sản phẩm bị loại
                  {currentBatchId ? ` · Phiên ${currentBatchId}` : ''}
                </h2>
                <span className="tnum">{rejections.length} ảnh trong phiên này · Nhấn vào ảnh để phóng to</span>
              </div>
              <EvidenceGrid
                items={rejections}
                onSelect={setActiveImage}
                emptyText={
                  currentBatchId
                    ? `Phiên ${currentBatchId} chưa có ảnh sản phẩm bị loại nào được lưu.`
                    : 'Chưa có ảnh sản phẩm bị loại nào được lưu.'
                }
              />
            </section>
          </>
        ) : view === 'warehouse' ? (
          <WarehouseView data={warehouse} onUpdate={setWarehouse} />
        ) : (
          <SessionHistory onSelectImage={setActiveImage} />
        )}
      </main>

      <footer className="page-footer">
        <div className="footer-inner">
          <span>FruitGuard · Hệ thống kiểm tra và phân loại chất lượng nông sản</span>
          <span>Chế độ chỉ đọc nhật ký · Vận hành cục bộ</span>
        </div>
      </footer>

      <EvidenceModal item={activeImage} onClose={() => setActiveImage(null)} />
    </div>
  )
}
