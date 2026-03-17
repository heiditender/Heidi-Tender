import type { EChartsOption } from "echarts";
import type { FieldFrequencyStatRow, JobDurationStatRow, StepDurationStatRow } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/view-models";

const AXIS_TEXT_COLOR = "#a9c0d0";
const LABEL_TEXT_COLOR = "#d8eaf6";
const SPLIT_LINE_COLOR = "rgba(148, 178, 197, 0.14)";
const GRID_LINE_COLOR = "rgba(148, 178, 197, 0.22)";
const TOOLTIP_BG = "rgba(6, 18, 26, 0.95)";
const TOOLTIP_BORDER = "rgba(118, 187, 223, 0.45)";

const HEATMAP_COLS = 8;

function compactText(input: string, maxLength: number): string {
  if (input.length <= maxLength) return input;
  return `${input.slice(0, maxLength - 3)}...`;
}

function compactJobId(input: string): string {
  if (input.length <= 16) return input;
  return `${input.slice(0, 8)}...${input.slice(-6)}`;
}

function toDurationMsValue(input: number | null): number {
  if (input == null || Number.isNaN(input)) return 0;
  return Math.max(0, input);
}

function commonTooltip() {
  return {
    trigger: "item" as const,
    backgroundColor: TOOLTIP_BG,
    borderColor: TOOLTIP_BORDER,
    borderWidth: 1,
    textStyle: {
      color: LABEL_TEXT_COLOR,
      fontSize: 12,
    },
  };
}

export function buildJobDurationOption(rows: JobDurationStatRow[]): EChartsOption {
  const categories = rows.map((row) => compactJobId(row.job_id));
  const values = rows.map((row) => toDurationMsValue(row.duration_ms));

  return {
    animationDuration: 320,
    color: ["#38bdf8"],
    grid: { left: 156, right: 38, top: 26, bottom: 24 },
    tooltip: {
      ...commonTooltip(),
      formatter: (raw: any) => {
        const index = Number(raw?.dataIndex ?? 0);
        const row = rows[index];
        if (!row) return "";
        return [
          `<strong>${row.job_id}</strong>`,
          `总耗时: ${formatDuration(row.duration_ms)}`,
          `状态: ${row.status}`,
          `更新时间: ${formatDateTime(row.updated_at)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "value",
      axisLabel: {
        color: AXIS_TEXT_COLOR,
        formatter: (value: number) => formatDuration(value),
      },
      splitLine: {
        lineStyle: { color: SPLIT_LINE_COLOR },
      },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    yAxis: {
      type: "category",
      data: categories,
      inverse: true,
      axisLabel: {
        color: AXIS_TEXT_COLOR,
        width: 138,
        overflow: "truncate",
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    dataZoom: [
      {
        type: "inside",
        yAxisIndex: 0,
        zoomOnMouseWheel: true,
      },
      {
        type: "slider",
        yAxisIndex: 0,
        width: 12,
        right: 10,
        backgroundColor: "rgba(29, 54, 68, 0.5)",
        borderColor: "rgba(117, 163, 189, 0.28)",
        fillerColor: "rgba(56, 189, 248, 0.2)",
      },
    ],
    series: [
      {
        type: "bar",
        data: values,
        barMaxWidth: 14,
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
        },
      },
    ],
  };
}

export function buildExtractedProductsOption(rows: JobDurationStatRow[]): EChartsOption {
  const categories = rows.map((row) => compactJobId(row.job_id));
  const values = rows.map((row) => {
    if (row.extracted_products == null || Number.isNaN(row.extracted_products)) return 0;
    return Math.max(0, row.extracted_products);
  });

  return {
    animationDuration: 320,
    color: ["#22c55e"],
    grid: { left: 156, right: 38, top: 26, bottom: 24 },
    tooltip: {
      ...commonTooltip(),
      formatter: (raw: any) => {
        const index = Number(raw?.dataIndex ?? 0);
        const row = rows[index];
        if (!row) return "";
        return [
          `<strong>${row.job_id}</strong>`,
          `抽取产品数: ${row.extracted_products ?? "-"}`,
          `状态: ${row.status}`,
          `更新时间: ${formatDateTime(row.updated_at)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "value",
      axisLabel: { color: AXIS_TEXT_COLOR },
      splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    yAxis: {
      type: "category",
      data: categories,
      inverse: true,
      axisLabel: {
        color: AXIS_TEXT_COLOR,
        width: 138,
        overflow: "truncate",
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    dataZoom: [
      {
        type: "inside",
        yAxisIndex: 0,
      },
      {
        type: "slider",
        yAxisIndex: 0,
        width: 12,
        right: 10,
        backgroundColor: "rgba(29, 54, 68, 0.5)",
        borderColor: "rgba(117, 163, 189, 0.28)",
        fillerColor: "rgba(34, 197, 94, 0.2)",
      },
    ],
    series: [
      {
        type: "bar",
        data: values,
        barMaxWidth: 14,
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
        },
      },
    ],
  };
}

export function buildStepDurationOption(rows: StepDurationStatRow[]): EChartsOption {
  const categories = rows.map((row) => compactText(row.step_name, 24));
  const avgSeries = rows.map((row) => toDurationMsValue(row.avg_duration_ms));
  const p50Series = rows.map((row) => toDurationMsValue(row.p50_duration_ms));
  const p90Series = rows.map((row) => toDurationMsValue(row.p90_duration_ms));

  return {
    animationDuration: 300,
    color: ["#38bdf8", "#22c55e", "#f59e0b"],
    grid: { left: 44, right: 24, top: 40, bottom: 68 },
    legend: {
      top: 6,
      textStyle: { color: AXIS_TEXT_COLOR },
    },
    tooltip: {
      ...commonTooltip(),
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (items: any) => {
        const rowsList = Array.isArray(items) ? items : [items];
        const first = rowsList[0];
        const index = Number(first?.dataIndex ?? 0);
        const row = rows[index];
        if (!row) return "";
        return [
          `<strong>${row.step_name}</strong>`,
          `sample_count: ${row.sample_count}`,
          `avg: ${formatDuration(row.avg_duration_ms == null ? null : Math.round(row.avg_duration_ms))}`,
          `p50: ${formatDuration(row.p50_duration_ms)}`,
          `p90: ${formatDuration(row.p90_duration_ms)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: {
        color: AXIS_TEXT_COLOR,
        rotate: 22,
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: AXIS_TEXT_COLOR,
        formatter: (value: number) => formatDuration(value),
      },
      splitLine: { lineStyle: { color: SPLIT_LINE_COLOR } },
      axisLine: { lineStyle: { color: GRID_LINE_COLOR } },
    },
    series: [
      {
        name: "avg",
        type: "bar",
        barMaxWidth: 24,
        data: avgSeries,
        itemStyle: { borderRadius: [5, 5, 0, 0] },
      },
      {
        name: "p50",
        type: "bar",
        barMaxWidth: 24,
        data: p50Series,
        itemStyle: { borderRadius: [5, 5, 0, 0] },
      },
      {
        name: "p90",
        type: "bar",
        barMaxWidth: 24,
        data: p90Series,
        itemStyle: { borderRadius: [5, 5, 0, 0] },
      },
    ],
  };
}

export function buildFieldHeatmapOption(rows: FieldFrequencyStatRow[]): EChartsOption {
  const colCount = Math.min(HEATMAP_COLS, Math.max(1, rows.length));
  const rowCount = Math.max(1, Math.ceil(rows.length / colCount));
  const xAxisLabels = Array.from({ length: colCount }, (_, idx) => `C${idx + 1}`);
  const yAxisLabels = Array.from({ length: rowCount }, (_, idx) => `R${idx + 1}`);
  const maxCount = Math.max(1, ...rows.map((row) => row.count));

  const data = rows.map((row, idx) => {
    const x = idx % colCount;
    const y = Math.floor(idx / colCount);
    return {
      value: [x, y, row.count],
      field: row.field,
      rank: idx + 1,
    };
  });

  return {
    animationDuration: 280,
    grid: {
      left: 12,
      right: 12,
      top: 12,
      bottom: 48,
      containLabel: false,
    },
    tooltip: {
      ...commonTooltip(),
      formatter: (raw: any) => {
        const item = raw?.data;
        if (!item) return "";
        return [`<strong>#${item.rank}</strong>`, `${item.field}`, `出现次数: ${item.value?.[2] ?? 0}`].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: xAxisLabels,
      show: false,
    },
    yAxis: {
      type: "category",
      data: yAxisLabels,
      show: false,
    },
    visualMap: {
      min: 0,
      max: maxCount,
      orient: "horizontal",
      left: "center",
      bottom: 2,
      text: ["高频", "低频"],
      textStyle: { color: AXIS_TEXT_COLOR },
      inRange: {
        color: ["#0b2e42", "#134760", "#1f6f8b", "#2f95b0", "#47b7d6"],
      },
    },
    series: [
      {
        type: "heatmap",
        data,
        label: {
          show: true,
          formatter: (raw: any) => {
            const item = raw?.data;
            if (!item) return "";
            return `${item.value?.[2] ?? 0}`;
          },
          color: "#e6f6ff",
          fontSize: 11,
          fontWeight: 600,
        },
        itemStyle: {
          borderColor: "rgba(155, 209, 235, 0.24)",
          borderWidth: 1,
          borderRadius: 4,
        },
      },
    ],
  };
}
