import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { Group, SegmentedControl, Text } from "@mantine/core";
import { get } from "../api";

type PromSeries = { metric: Record<string, string>; values: [number, string][] };

const RANGES = [
  { value: "300", label: "5m" },
  { value: "900", label: "15m" },
  { value: "3600", label: "1h" },
  { value: "21600", label: "6h" },
];

function scale(unit: string | undefined) {
  return (v: number) => {
    if (unit === "bps") {
      const p = ["", "k", "M", "G"];
      let i = 0;
      while (Math.abs(v) >= 1000 && i < p.length - 1) { v /= 1000; i++; }
      return `${Number(v.toFixed(1))} ${p[i]}bit/s`;
    }
    if (unit === "ratio") return `${Math.round(v * 100)}%`;
    return `${Number(v.toFixed(2))}`;
  };
}

/** Prometheus range query rendered with ECharts; re-queried every 5 s. */
export function PromChart(props: {
  title: string;
  query: string;
  name: (labels: Record<string, string>) => string;
  unit?: "bps" | "ratio";
  height?: number;
  palette?: Record<string, string>;
}) {
  const { title, query, name, unit, height = 220, palette } = props;
  const box = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const [range, setRange] = useState("900");
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const c = echarts.init(box.current!);
    inst.current = c;
    const obs = new ResizeObserver(() => c.resize());
    obs.observe(box.current!);
    return () => { obs.disconnect(); c.dispose(); };
  }, []);

  useEffect(() => {
    let live = true;
    const f = scale(unit);
    async function refresh() {
      try {
        const rows = await get<PromSeries[]>(`/api/metrics/range?seconds=${range}&query=${encodeURIComponent(query)}`);
        if (!live) return;
        setProblem(rows.length ? null : "No samples in this time range.");
        inst.current?.setOption(
          {
            backgroundColor: "transparent",
            animation: false,
            grid: { left: 70, right: 14, top: 30, bottom: 26 },
            legend: { top: 0, textStyle: { color: "#94a3b8", fontSize: 11 } },
            tooltip: {
              trigger: "axis",
              backgroundColor: "#0e141c",
              borderColor: "#1d2733",
              textStyle: { color: "#e2e8f0", fontSize: 12 },
              valueFormatter: (v: unknown) => f(Number(v)),
            },
            xAxis: { type: "time", axisLabel: { color: "#64748b", fontSize: 10 }, axisLine: { lineStyle: { color: "#1d2733" } } },
            yAxis: { type: "value", axisLabel: { color: "#64748b", fontSize: 10, formatter: f }, splitLine: { lineStyle: { color: "#141c26" } } },
            series: rows.map((r) => {
              const n = name(r.metric);
              return {
                name: n,
                type: "line",
                showSymbol: false,
                lineStyle: { width: 1.6 },
                areaStyle: { opacity: 0.07 },
                color: palette?.[n],
                data: r.values.map(([t, v]) => [t * 1000, Number(v)]),
              };
            }),
          },
          { notMerge: true },
        );
      } catch (e) {
        if (live) setProblem(String(e));
      }
    }
    refresh();
    const id = setInterval(refresh, 5000);
    return () => { live = false; clearInterval(id); };
  }, [query, range, unit, name, palette]);

  return (
    <div>
      <Group justify="space-between" mb={4}>
        <Text className="section-title">{title}</Text>
        <SegmentedControl size="xs" value={range} onChange={setRange} data={RANGES} />
      </Group>
      {problem && <Text size="xs" c="dimmed">{problem}</Text>}
      <div ref={box} style={{ height, width: "100%" }} />
    </div>
  );
}
