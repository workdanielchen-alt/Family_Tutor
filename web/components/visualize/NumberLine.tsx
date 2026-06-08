"use client";

import { useMemo } from "react";

interface NumberLineProps {
  /** Raw spec text after the ```numberline fence */
  spec: string;
  width?: number;
  height?: number;
}

interface NumberLineConfig {
  range: [number, number];
  points: number[];
  openPoints: number[];
  highlights: Array<[number, number]>;
  labels: Record<number, string>;
}

function parseSpec(spec: string): NumberLineConfig {
  const config: NumberLineConfig = {
    range: [-5, 5],
    points: [],
    openPoints: [],
    highlights: [],
    labels: {},
  };

  for (const line of spec.split("\n")) {
    const clean = line.replace(/#.*$/, "").trim();
    if (!clean) continue;

    // range: -3:5
    if (clean.startsWith("range:")) {
      const m = clean.match(/range:\s*([\d.-]+)\s*:\s*([\d.-]+)/);
      if (m) config.range = [parseFloat(m[1]), parseFloat(m[2])];
    }
    // points: -2,0,3
    else if (clean.startsWith("points:")) {
      config.points = clean
        .replace(/^points:\s*/, "")
        .split(/[,，\s]+/)
        .map((s) => parseFloat(s.trim()))
        .filter((n) => isFinite(n));
    }
    // open: 1,4
    else if (clean.startsWith("open:")) {
      config.openPoints = clean
        .replace(/^open:\s*/, "")
        .split(/[,，\s]+/)
        .map((s) => parseFloat(s.trim()))
        .filter((n) => isFinite(n));
    }
    // highlight: 0.5:2.5
    else if (clean.startsWith("highlight:")) {
      const m = clean.match(/highlight:\s*([\d.-]+)\s*:\s*([\d.-]+)/);
      if (m) config.highlights.push([parseFloat(m[1]), parseFloat(m[2])]);
    }
  }

  return config;
}

const MARKER_R = 5;

export default function NumberLine({
  spec,
  width = 360,
  height = 60,
}: NumberLineProps) {
  const cfg = useMemo(() => parseSpec(spec), [spec]);
  const [xMin, xMax] = cfg.range;
  const xSpan = xMax - xMin || 1;
  const pad = { left: 28, right: 28, top: 10, bottom: 20 };
  const plotW = width - pad.left - pad.right;
  const axisY = pad.top + 8;

  const toX = (v: number) => pad.left + ((v - xMin) / xSpan) * plotW;

  // Determine tick step (1, 2, 0.5, 5, 10…)
  const tickStep = useMemo(() => {
    const raw = xSpan / 8;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const norm = raw / mag;
    return (norm <= 1.5 ? mag : norm <= 3.5 ? 2 * mag : 5 * mag) || 1;
  }, [xSpan]);

  const ticks = useMemo(() => {
    const tks: number[] = [];
    const start = Math.ceil(xMin / tickStep) * tickStep;
    for (let v = start; v <= xMax; v += tickStep) {
      tks.push(Math.round(v * 1e10) / 1e10);
    }
    return tks;
  }, [xMin, xMax, tickStep]);

  const isZeroVisible = xMin < 0 && xMax > 0;

  return (
    <div className="my-2 inline-block rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-1 shadow-sm">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block"
      >
        {/* Highlight bars */}
        {cfg.highlights.map(([lo, hi], i) => (
          <rect
            key={`hl-${i}`}
            x={toX(Math.max(lo, xMin))}
            y={axisY - 4}
            width={toX(Math.min(hi, xMax)) - toX(Math.max(lo, xMin))}
            height={8}
            rx={3}
            fill="var(--primary)"
            opacity={0.2}
          />
        ))}

        {/* Axis line */}
        <line
          x1={pad.left}
          y1={axisY}
          x2={width - pad.right}
          y2={axisY}
          stroke="var(--foreground)"
          strokeWidth={1.2}
          opacity={0.5}
        />

        {/* Arrow right */}
        <polygon
          points={`${width - pad.right},${axisY} ${width - pad.right - 6},${axisY - 3} ${width - pad.right - 6},${axisY + 3}`}
          fill="var(--foreground)"
          opacity={0.5}
        />

        {/* Tick marks + labels */}
        {ticks.map((v) => (
          <g key={`tick-${v}`}>
            <line
              x1={toX(v)}
              y1={axisY - 3}
              x2={toX(v)}
              y2={axisY + 3}
              stroke="var(--foreground)"
              strokeWidth={1}
              opacity={0.4}
            />
            <text
              x={toX(v)}
              y={axisY + 16}
              textAnchor="middle"
              className="fill-[var(--muted-foreground)] text-[10px]"
            >
              {v === 0 ? "0" : Number.isInteger(v) ? v.toString() : v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* Zero marker (above ticks) */}
        {isZeroVisible && (
          <line
            x1={toX(0)}
            y1={axisY - 4}
            x2={toX(0)}
            y2={axisY + 4}
            stroke="var(--foreground)"
            strokeWidth={1.2}
          />
        )}

        {/* Solid points */}
        {cfg.points.map((v, i) => {
          if (v < xMin || v > xMax) return null;
          const cx = toX(v);
          const cy = axisY;
          const label = cfg.labels[v] ?? v.toString();
          return (
            <g key={`pt-${i}`}>
              <circle cx={cx} cy={cy} r={MARKER_R} fill="var(--primary)" />
              {/* Inline label below */}
              {label !== v.toString() && (
                <text
                  x={cx}
                  y={cy + 22}
                  textAnchor="middle"
                  className="fill-[var(--foreground)] text-[9px]"
                >
                  {label}
                </text>
              )}
            </g>
          );
        })}

        {/* Open (hollow) points */}
        {cfg.openPoints.map((v, i) => {
          if (v < xMin || v > xMax) return null;
          return (
            <circle
              key={`op-${i}`}
              cx={toX(v)}
              cy={axisY}
              r={MARKER_R}
              fill="var(--card)"
              stroke="var(--foreground)"
              strokeWidth={1.5}
            />
          );
        })}
      </svg>
    </div>
  );
}
