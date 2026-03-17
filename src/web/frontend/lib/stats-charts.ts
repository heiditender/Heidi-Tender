import type { EChartsOption } from "echarts";
import type { FieldFrequencyStatRow, JobDurationStatRow, StepDurationStatRow } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/view-models";

export type ChartTheme = "light" | "dark";

interface ChartThemeTokens {
  axisTextColor: string;
  labelTextColor: string;
  splitLineColor: string;
  gridLineColor: string;
  tooltipBg: string;
  tooltipBorder: string;
  sliderBg: string;
  sliderBorder: string;
  heatmapTextColor: string;
  heatmapBorderColor: string;
  heatmapPalette: string[];
}

const CHART_THEME_TOKENS: Record<ChartTheme, ChartThemeTokens> = {
  dark: {
    axisTextColor: "#a9c0d0",
    labelTextColor: "#d8eaf6",
    splitLineColor: "rgba(148, 178, 197, 0.14)",
    gridLineColor: "rgba(148, 178, 197, 0.22)",
    tooltipBg: "rgba(6, 18, 26, 0.95)",
    tooltipBorder: "rgba(118, 187, 223, 0.45)",
    sliderBg: "rgba(29, 54, 68, 0.5)",
    sliderBorder: "rgba(117, 163, 189, 0.28)",
    heatmapTextColor: "#e6f6ff",
    heatmapBorderColor: "rgba(155, 209, 235, 0.24)",
    heatmapPalette: ["#0b2e42", "#134760", "#1f6f8b", "#2f95b0", "#47b7d6"],
  },
  light: {
    axisTextColor: "#4c6472",
    labelTextColor: "#163243",
    splitLineColor: "rgba(82, 113, 132, 0.16)",
    gridLineColor: "rgba(82, 113, 132, 0.24)",
    tooltipBg: "rgba(250, 252, 253, 0.98)",
    tooltipBorder: "rgba(109, 149, 172, 0.34)",
    sliderBg: "rgba(216, 230, 238, 0.78)",
    sliderBorder: "rgba(110, 142, 161, 0.24)",
    heatmapTextColor: "#103245",
    heatmapBorderColor: "rgba(84, 128, 151, 0.18)",
    heatmapPalette: ["#d5e9f3", "#b0d8e6", "#7fbfd3", "#4796b1", "#165d76"],
  },
};

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

function getChartTokens(theme: ChartTheme): ChartThemeTokens {
  return CHART_THEME_TOKENS[theme];
}

function commonTooltip(theme: ChartTheme) {
  const tokens = getChartTokens(theme);
  return {
    trigger: "item" as const,
    backgroundColor: tokens.tooltipBg,
    borderColor: tokens.tooltipBorder,
    borderWidth: 1,
    textStyle: {
      color: tokens.labelTextColor,
      fontSize: 12,
    },
  };
}

export function buildJobDurationOption(rows: JobDurationStatRow[], theme: ChartTheme = "dark"): EChartsOption {
  const tokens = getChartTokens(theme);
  const categories = rows.map((row) => compactJobId(row.job_id));
  const values = rows.map((row) => toDurationMsValue(row.duration_ms));

  return {
    animationDuration: 320,
    color: ["#38bdf8"],
    grid: { left: 156, right: 38, top: 26, bottom: 24 },
    tooltip: {
      ...commonTooltip(theme),
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
        color: tokens.axisTextColor,
        formatter: (value: number) => formatDuration(value),
      },
      splitLine: {
        lineStyle: { color: tokens.splitLineColor },
      },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
    },
    yAxis: {
      type: "category",
      data: categories,
      inverse: true,
      axisLabel: {
        color: tokens.axisTextColor,
        width: 138,
        overflow: "truncate",
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
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
        backgroundColor: tokens.sliderBg,
        borderColor: tokens.sliderBorder,
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

export function buildExtractedProductsOption(rows: JobDurationStatRow[], theme: ChartTheme = "dark"): EChartsOption {
  const tokens = getChartTokens(theme);
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
      ...commonTooltip(theme),
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
      axisLabel: { color: tokens.axisTextColor },
      splitLine: { lineStyle: { color: tokens.splitLineColor } },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
    },
    yAxis: {
      type: "category",
      data: categories,
      inverse: true,
      axisLabel: {
        color: tokens.axisTextColor,
        width: 138,
        overflow: "truncate",
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
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
        backgroundColor: tokens.sliderBg,
        borderColor: tokens.sliderBorder,
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

export function buildStepDurationOption(rows: StepDurationStatRow[], theme: ChartTheme = "dark"): EChartsOption {
  const tokens = getChartTokens(theme);
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
      textStyle: { color: tokens.axisTextColor },
    },
    tooltip: {
      ...commonTooltip(theme),
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
        color: tokens.axisTextColor,
        rotate: 22,
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: tokens.axisTextColor,
        formatter: (value: number) => formatDuration(value),
      },
      splitLine: { lineStyle: { color: tokens.splitLineColor } },
      axisLine: { lineStyle: { color: tokens.gridLineColor } },
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

export function buildFieldHeatmapOption(rows: FieldFrequencyStatRow[], theme: ChartTheme = "dark"): EChartsOption {
  const tokens = getChartTokens(theme);
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
      ...commonTooltip(theme),
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
      textStyle: { color: tokens.axisTextColor },
      inRange: {
        color: tokens.heatmapPalette,
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
          color: tokens.heatmapTextColor,
          fontSize: 11,
          fontWeight: 600,
        },
        itemStyle: {
          borderColor: tokens.heatmapBorderColor,
          borderWidth: 1,
          borderRadius: 4,
        },
      },
    ],
  };
}
