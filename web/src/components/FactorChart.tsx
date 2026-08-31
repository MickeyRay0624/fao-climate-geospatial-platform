import { useEffect, useRef } from "react";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { init, use, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { AreaResult, Catalog } from "../types";

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

type Props = {
  area: AreaResult | null;
  catalog: Catalog;
};

function FactorChart({ area, catalog }: Props) {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    if (!nodeRef.current) return;
    if (!chartRef.current) chartRef.current = init(nodeRef.current);
    const chart = chartRef.current;

    if (!area) {
      chart.clear();
      return;
    }

    const rows = Object.entries(area.components)
      .map(([code, component]) => ({
        code,
        label: catalog.indicators[code]?.short_label ?? code,
        contribution: component.contribution,
        colour: catalog.indicators[code]?.colour ?? "#6b7c78",
      }))
      .sort((left, right) => left.contribution - right.contribution);

    chart.setOption({
      animationDuration: 300,
      grid: { left: 94, right: 18, top: 8, bottom: 18 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (value: unknown) => `${Number(value).toFixed(1)} points`,
      },
      xAxis: {
        type: "value",
        axisLabel: { color: "#72807c", fontSize: 10 },
        splitLine: { lineStyle: { color: "#e5ebe8" } },
      },
      yAxis: {
        type: "category",
        data: rows.map((row) => row.label),
        axisLabel: { color: "#455a56", fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: "bar",
          data: rows.map((row) => ({
            value: row.contribution,
            itemStyle: { color: row.colour, borderRadius: [0, 4, 4, 0] },
          })),
          barMaxWidth: 12,
        },
      ],
    });

    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [area, catalog.indicators]);

  useEffect(
    () => () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    },
    [],
  );

  return <div ref={nodeRef} className="factor-chart" aria-label="Score contribution chart" />;
}

export default FactorChart;

