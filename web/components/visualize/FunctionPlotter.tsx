"use client";

import { useMemo } from "react";

interface FunctionPlotterProps {
  /** Function expression, e.g. "x^2 - 3x + 2", "2x + 1" */
  formula: string;
  /** X range, e.g. "-5:5" — default "-5:5" */
  xRange?: string;
  width?: number;
  height?: number;
}

/**
 * Evaluate a simple math expression at a given x value.
 * Supports: +, -, *, /, ^, sin, cos, tan, sqrt, abs, pi, e
 */
function evaluate(expr: string, x: number): number {
  const sanitized = expr
    .replace(/\^/g, "**")
    .replace(/sin\(/g, "Math.sin(")
    .replace(/cos\(/g, "Math.cos(")
    .replace(/tan\(/g, "Math.tan(")
    .replace(/sqrt\(/g, "Math.sqrt(")
    .replace(/abs\(/g, "Math.abs(")
    .replace(/pi/g, "Math.PI")
    .replace(/e(?![xp])/g, "Math.E");
  try {
    const fn = new Function("x", `return ${sanitized};`);
    const result = fn(x);
    return typeof result === "number" && isFinite(result) ? result : NaN;
  } catch {
    return NaN;
  }
}

/**
 * Simple SVG function plotter for K12 math.
 *
 * Renders a coordinate system + function curve in pure SVG,
 * no external dependencies. Supports linear, quadratic,
 * inverse, and trigonometric functions.
 */
export default function FunctionPlotter({
  formula,
  xRange = "-5:5",
  width = 320,
  height = 280,
}: FunctionPlotterProps) {
  const { points, xMin, xMax, yMin, yMax } = useMemo(() => {
    const parts = xRange.split(":");
    const xMinNum = parseFloat(parts[0]) || -5;
    const xMaxNum = parseFloat(parts[1]) || 5;
    const step = (xMaxNum - xMinNum) / 200;

    const pts: Array<[number, number]> = [];
    let yMinNum = Infinity;
    let yMaxNum = -Infinity;

    for (let x = xMinNum; x <= xMaxNum; x += step) {
      const y = evaluate(formula, x);
      if (!isNaN(y)) {
        pts.push([x, y]);
        yMinNum = Math.min(yMinNum, y);
        yMaxNum = Math.max(yMaxNum, y);
      }
    }

    // Add some padding to Y range
    const yPad = Math.max((yMaxNum - yMinNum) * 0.1 || 1, 1);
    return {
      points: pts,
      xMin: xMinNum,
      xMax: xMaxNum,
      yMin: yMinNum - yPad,
      yMax: yMaxNum + yPad,
    };
  }, [formula, xRange]);

  // SVG coordinate transform
  const pad = { top: 20, right: 20, bottom: 30, left: 40 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const xScale = (x: number) =>
    pad.left + ((x - xMin) / (xMax - xMin)) * plotW;
  const yScale = (y: number) =>
    pad.top + plotH - ((y - yMin) / (yMax - yMin)) * plotH;

  // Grid lines
  const xStep = 10 ** Math.floor(Math.log10(xMax - xMin)) / 2;
  const yStep = 10 ** Math.floor(Math.log10(yMax - yMin)) / 2;

  const gridLines = useMemo(() => {
    const xLines: number[] = [];
    const yLines: number[] = [];
    const startX = Math.ceil(xMin / xStep) * xStep;
    const startY = Math.ceil(yMin / yStep) * yStep;
    for (let x = startX; x <= xMax; x += xStep) xLines.push(x);
    for (let y = startY; y <= yMax; y += yStep) yLines.push(y);
    return { xLines, yLines };
  }, [xMin, xMax, yMin, yMax, xStep, yStep]);

  // Build path data
  const pathD = useMemo(() => {
    if (points.length < 2) return "";
    return points
      .map(([x, y], i) =>
        i === 0 ? `M${xScale(x)},${yScale(y)}` : `L${xScale(x)},${yScale(y)}`,
      )
      .join(" ");
  }, [points]);

  return (
    <div className="my-3 inline-block rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-2 shadow-sm">
      <div className="mb-1 px-2 text-[11px] font-mono text-[var(--muted-foreground)]">
        y = {formula}
      </div>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block"
      >
        {/* Grid */}
        {gridLines.xLines.map((x) => (
          <line
            key={`gx-${x}`}
            x1={xScale(x)}
            y1={pad.top}
            x2={xScale(x)}
            y2={height - pad.bottom}
            stroke="var(--border)"
            strokeWidth={0.5}
            opacity={0.4}
          />
        ))}
        {gridLines.yLines.map((y) => (
          <line
            key={`gy-${y}`}
            x1={pad.left}
            y1={yScale(y)}
            x2={width - pad.right}
            y2={yScale(y)}
            stroke="var(--border)"
            strokeWidth={0.5}
            opacity={0.4}
          />
        ))}

        {/* Axes */}
        {xMin < 0 && xMax > 0 && (
          <line
            x1={xScale(0)}
            y1={pad.top}
            x2={xScale(0)}
            y2={height - pad.bottom}
            stroke="var(--foreground)"
            strokeWidth={1}
            opacity={0.5}
          />
        )}
        {yMin < 0 && yMax > 0 && (
          <line
            x1={pad.left}
            y1={yScale(0)}
            x2={width - pad.right}
            y2={yScale(0)}
            stroke="var(--foreground)"
            strokeWidth={1}
            opacity={0.5}
          />
        )}

        {/* Axis labels */}
        {gridLines.xLines
          .filter((x) => Math.abs(x) > 0.01 && x >= xMin && x <= xMax)
          .map((x) => (
            <text
              key={`lx-${x}`}
              x={xScale(x)}
              y={height - 8}
              textAnchor="middle"
              className="fill-[var(--muted-foreground)] text-[9px]"
            >
              {Math.abs(x) < 0.01 ? "0" : Number.isInteger(x) ? x : x.toFixed(1)}
            </text>
          ))}
        {gridLines.yLines
          .filter((y) => Math.abs(y) > 0.01 && y >= yMin && y <= yMax)
          .map((y) => (
            <text
              key={`ly-${y}`}
              x={pad.left - 6}
              y={yScale(y) + 3}
              textAnchor="end"
              className="fill-[var(--muted-foreground)] text-[9px]"
            >
              {Number.isInteger(y) ? y : y.toFixed(1)}
            </text>
          ))}

        {/* Function curve */}
        {pathD && (
          <path
            d={pathD}
            fill="none"
            stroke="var(--primary)"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
      </svg>
    </div>
  );
}
