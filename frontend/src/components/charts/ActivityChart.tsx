import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { BarChart3, Table2 } from 'lucide-react'
import { cx } from '../ui'

// 14-day activity as three small multiples (one column chart per series).
// The series differ by orders of magnitude (hundreds discovered vs a handful
// submitted), so each row gets its own y-scale instead of a misleading shared
// or dual axis. One hover position drives a single tooltip listing every series.

export interface Series {
  key: string
  label: string
  color: string // CSS var reference, e.g. var(--series-1)
  values: number[]
}

const PLOT_H = 64
const TOP_PAD = 16 // room for the peak label
const AXIS_H = 22

function niceCeil(max: number): number {
  if (max <= 0) return 1
  const mag = Math.pow(10, Math.floor(Math.log10(max)))
  const n = max / mag
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10
  return Math.max(1, nice * mag)
}

function dayLabel(iso: string, withWeekday = false): string {
  // Days are UTC calendar dates from the API; format in UTC so they don't shift.
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', weekday: withWeekday ? 'short' : undefined, timeZone: 'UTC' })
}

function barPath(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, h, w / 2)
  return `M${x},${y + h}L${x},${y + rr}Q${x},${y} ${x + rr},${y}L${x + w - rr},${y}Q${x + w},${y} ${x + w},${y + rr}L${x + w},${y + h}Z`
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth)
    const ro = new ResizeObserver((entries) => setW(entries[0].contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

export function ActivityChart({ days, series }: { days: string[]; series: Series[] }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [hover, setHover] = useState<number | null>(null)
  const [hoverRow, setHoverRow] = useState(0)
  const rowRefs = useRef<(HTMLDivElement | null)[]>([])
  const [wrapRef, width] = useWidth<HTMLDivElement>()
  const n = days.length
  const band = n ? width / n : 0
  const barW = Math.max(3, Math.min(24, band * 0.62))
  const stride = band > 0 ? Math.max(1, Math.ceil(52 / band)) : 1

  useEffect(() => {
    if (view === 'table') setHover(null)
  }, [view])

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!n) return
    if (e.key === 'ArrowRight') {
      e.preventDefault()
      setHover((h) => (h == null ? n - 1 : Math.min(n - 1, h + 1)))
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      setHover((h) => (h == null ? n - 1 : Math.max(0, h - 1)))
    } else if (e.key === 'Escape') setHover(null)
  }

  const colCenter = hover != null ? hover * band + band / 2 : 0
  const flip = colCenter > width - 190
  const tooltipLeft = flip ? colCenter - band / 2 - 8 : colCenter + band / 2 + 8
  const tooltipTop = Math.max(0, (rowRefs.current[hoverRow]?.offsetTop ?? 0) + 4)

  return (
    <figure className="m-0 min-w-0">
      <div className="mb-3 flex items-center justify-between gap-3">
        <figcaption className="text-xs text-slate-500 dark:text-slate-400">
          Daily counts (UTC days). Each row has its own scale.
        </figcaption>
        <div className="inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-700" role="group" aria-label="Chart view">
          <button
            type="button"
            onClick={() => setView('chart')}
            aria-pressed={view === 'chart'}
            className={cx(
              'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium',
              view === 'chart' ? 'bg-slate-100 text-slate-900 dark:bg-slate-700 dark:text-white' : 'text-slate-500 dark:text-slate-400',
            )}
          >
            <BarChart3 className="h-3.5 w-3.5" aria-hidden /> Chart
          </button>
          <button
            type="button"
            onClick={() => setView('table')}
            aria-pressed={view === 'table'}
            className={cx(
              'inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium',
              view === 'table' ? 'bg-slate-100 text-slate-900 dark:bg-slate-700 dark:text-white' : 'text-slate-500 dark:text-slate-400',
            )}
          >
            <Table2 className="h-3.5 w-3.5" aria-hidden /> Table
          </button>
        </div>
      </div>

      {view === 'table' ? (
        <div className="relative overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="table-head">
                <th className="px-3 py-2">Day</th>
                {series.map((s) => (
                  <th key={s.key} className="px-3 py-2 text-right">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {days.map((d, i) => (
                <tr key={d}>
                  <td className="px-3 py-1.5 text-slate-600 dark:text-slate-300">{dayLabel(d, true)}</td>
                  {series.map((s) => (
                    <td key={s.key} className="px-3 py-1.5 text-right tabular text-slate-900 dark:text-slate-100">
                      {s.values[i] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="px-3 py-1.5">14-day total</td>
                {series.map((s) => (
                  <td key={s.key} className="px-3 py-1.5 text-right tabular">
                    {s.values.reduce((a, b) => a + b, 0)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <div
          ref={wrapRef}
          className="relative w-full min-w-0 overflow-x-clip outline-none"
          tabIndex={0}
          role="img"
          aria-label={`14-day activity. ${series.map((s) => `${s.label}: ${s.values.reduce((a, b) => a + b, 0)} total`).join('. ')}. Use arrow keys to read daily values, or switch to the table view.`}
          onKeyDown={onKey}
          onFocus={() => setHover((h) => (h == null ? n - 1 : h))}
          onBlur={() => setHover(null)}
          onPointerLeave={() => setHover(null)}
        >
          {width > 0 &&
            series.map((s, si) => {
              const max = Math.max(0, ...s.values)
              const top = niceCeil(max)
              const peak = s.values.indexOf(max)
              const total = s.values.reduce((a, b) => a + b, 0)
              const y = (v: number) => TOP_PAD + PLOT_H - (v / top) * PLOT_H
              const last = si === series.length - 1
              const h = TOP_PAD + PLOT_H + (last ? AXIS_H : 6)
              return (
                <div key={s.key} className={si ? 'mt-1' : ''} ref={(el) => { rowRefs.current[si] = el }}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="inline-flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-200">
                      <span className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} aria-hidden />
                      {s.label}
                    </span>
                    <span className="text-slate-500 dark:text-slate-400">
                      14-day total <span className="font-semibold text-slate-800 dark:text-slate-100">{total.toLocaleString()}</span>
                    </span>
                  </div>
                  <svg width={width} height={h} className="block overflow-visible" aria-hidden>
                    {/* hover band */}
                    {hover != null && <rect x={hover * band} y={TOP_PAD - 4} width={band} height={PLOT_H + 4} className="fill-slate-100 dark:fill-slate-800/70" />}
                    {/* gridline at the nice max + its label */}
                    <line x1={0} x2={width} y1={y(top)} y2={y(top)} stroke="var(--chart-grid)" strokeWidth={1} shapeRendering="crispEdges" />
                    <text x={0} y={y(top) - 3} fontSize={10} fill="var(--chart-ink-muted)" className="tabular">
                      {top.toLocaleString()}
                    </text>
                    {/* baseline */}
                    <line x1={0} x2={width} y1={y(0) + 0.5} y2={y(0) + 0.5} stroke="var(--chart-axis)" strokeWidth={1} shapeRendering="crispEdges" />
                    {s.values.map((v, i) => {
                      if (v <= 0) return null
                      const bx = i * band + (band - barW) / 2
                      const by = y(v)
                      return (
                        <path
                          key={i}
                          d={barPath(bx, by, barW, y(0) - by, 4)}
                          fill={s.color}
                          opacity={hover == null || hover === i ? 1 : 0.55}
                        />
                      )
                    })}
                    {/* selective direct label: the peak only */}
                    {max > 0 && (
                      <text
                        x={Math.min(Math.max(peak * band + band / 2, 10), width - 10)}
                        y={y(max) - 4}
                        fontSize={10.5}
                        fontWeight={600}
                        textAnchor="middle"
                        className="fill-slate-700 tabular dark:fill-slate-200"
                      >
                        {max.toLocaleString()}
                      </text>
                    )}
                    {last &&
                      days.map((d, i) =>
                        (n - 1 - i) % stride === 0 ? (
                          <text
                            key={d}
                            x={Math.min(Math.max(i * band + band / 2, 16), width - 16)}
                            y={TOP_PAD + PLOT_H + 15}
                            fontSize={10}
                            textAnchor="middle"
                            fill="var(--chart-ink-muted)"
                          >
                            {dayLabel(d)}
                          </text>
                        ) : null,
                      )}
                    {/* hit targets: full column, bigger than the mark */}
                    {days.map((d, i) => (
                      <rect
                        key={d}
                        x={i * band}
                        y={0}
                        width={band}
                        height={h}
                        fill="transparent"
                        onPointerEnter={() => { setHover(i); setHoverRow(si) }}
                        onPointerDown={() => { setHover(i); setHoverRow(si) }}
                      />
                    ))}
                  </svg>
                </div>
              )
            })}

          {hover != null && width > 0 && (
            <div
              className="pointer-events-none absolute z-10 w-40 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800"
              style={{ left: tooltipLeft, top: tooltipTop, transform: flip ? 'translateX(-100%)' : undefined }}
              role="status"
            >
              <p className="mb-1 font-medium text-slate-500 dark:text-slate-400">{dayLabel(days[hover], true)}</p>
              {series.map((s) => (
                <div key={s.key} className="flex items-center gap-2 py-0.5">
                  <span className="inline-block h-0.5 w-3 rounded-full" style={{ background: s.color }} aria-hidden />
                  <span className="font-semibold tabular text-slate-900 dark:text-white">{(s.values[hover] ?? 0).toLocaleString()}</span>
                  <span className="truncate text-slate-500 dark:text-slate-400">{s.label}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  )
}
