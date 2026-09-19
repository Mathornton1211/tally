import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef, useState } from 'react'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer])

export type ChartTheme = {
  s1: string; s2: string; compare: string; grid: string; axis: string; surface: string
  ink: string; ink2: string; ink3: string; line: string; font: string
}

function readTheme(): ChartTheme {
  const cs = getComputedStyle(document.documentElement)
  const v = (n: string) => cs.getPropertyValue(n).trim()
  return {
    s1: v('--series-1'), s2: v('--series-2'), compare: v('--series-compare'), grid: v('--chart-grid'),
    axis: v('--chart-axis'), surface: v('--chart-surface'), ink: v('--ink'), ink2: v('--ink-2'),
    ink3: v('--ink-3'), line: v('--line-strong'),
    font: '"Geist Variable", system-ui, sans-serif',
  }
}

/** Re-reads CSS tokens whenever the look changes -- the OS flipping, or somebody
 *  picking a mode, an accent or more contrast in Settings. */
export function useChartTheme() {
  const [theme, setTheme] = useState<ChartTheme>(readTheme)
  useEffect(() => {
    // A frame late: the attribute has to land on <html> before the computed
    // values are worth reading.
    const on = () => requestAnimationFrame(() => setTheme(readTheme()))
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', on)
    window.addEventListener('tally:theme', on)
    return () => {
      mq.removeEventListener('change', on)
      window.removeEventListener('tally:theme', on)
    }
  }, [])
  return theme
}

export function tooltipBase(t: ChartTheme) {
  return {
    backgroundColor: t.surface,
    borderColor: t.line,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: t.ink, fontFamily: t.font, fontSize: 12 },
    extraCssText: 'border-radius:12px;box-shadow:0 8px 24px -8px rgba(0,0,0,.18);',
  }
}

export function Chart({ option, height, onClick, ariaLabel }: {
  option: echarts.EChartsCoreOption; height: number; onClick?: (p: { dataIndex: number; seriesIndex?: number }) => void; ariaLabel: string
}) {
  const el = useRef<HTMLDivElement>(null)
  const inst = useRef<echarts.ECharts | null>(null)
  const clickRef = useRef(onClick)
  clickRef.current = onClick

  useEffect(() => {
    if (!el.current) return
    const c = echarts.init(el.current, undefined, { renderer: 'canvas' })
    inst.current = c
    c.on('click', (p) => clickRef.current?.(p as { dataIndex: number; seriesIndex?: number }))
    const ro = new ResizeObserver(() => c.resize())
    ro.observe(el.current)
    return () => { ro.disconnect(); c.dispose(); inst.current = null }
  }, [])

  useEffect(() => {
    inst.current?.setOption(option, { notMerge: true })
  }, [option])

  return <div ref={el} role="img" aria-label={ariaLabel} style={{ height, width: '100%' }} />
}
