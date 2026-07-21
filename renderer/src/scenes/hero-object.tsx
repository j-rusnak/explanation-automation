import React from "react";
import type { ThemeTokens } from "../themes/tokens";

const clamp01 = (value: number): number => Math.max(0, Math.min(1, value));

export const rollingShutterProofProgress = (
  progress: number,
  immediate: boolean,
): number =>
  immediate ? Math.max(0.72, clamp01(progress)) : clamp01(progress);

export const rollingShutterRowOffset = (
  rowRatio: number,
  distortion: number,
  progress: number,
  width: number,
  curvature = 0,
): number => {
  const ratio = clamp01(rowRatio);
  const bend = Math.sin(ratio * Math.PI) * curvature * width * 0.08;
  return (
    distortion * width * 0.22 * ratio * clamp01(progress) +
    bend * clamp01(progress)
  );
};

type RollingShutterHeroProps = {
  tokens: ThemeTokens;
  idPrefix: string;
  progress: number;
  distortion: number;
  scanProgress?: number;
  direction?: "top-to-bottom" | "bottom-to-top" | "left-to-right";
  curvature?: number;
  immediateProof?: boolean;
  showReference?: boolean;
  width?: number;
  height?: number;
};

const safeId = (value: string): string => value.replace(/[^a-z0-9_-]/giu, "-");

export const RollingShutterHero: React.FC<RollingShutterHeroProps> = ({
  tokens,
  idPrefix,
  progress,
  distortion,
  scanProgress = progress,
  direction = "top-to-bottom",
  curvature = 0,
  immediateProof = false,
  showReference = false,
  width = 760,
  height = 610,
}) => {
  const rows = 18;
  const inset = Math.round(Math.min(width, height) * 0.075);
  const innerWidth = width - inset * 2;
  const innerHeight = height - inset * 2;
  const rowHeight = innerHeight / rows;
  const proofProgress = rollingShutterProofProgress(progress, immediateProof);
  const scan = clamp01(scanProgress);
  const prefix = safeId(idPrefix);
  const poleX = inset + innerWidth * 0.46;
  const scanY =
    direction === "bottom-to-top"
      ? inset + innerHeight * (1 - scan)
      : inset + innerHeight * scan;
  const scanX = inset + innerWidth * scan;

  return (
    <svg
      aria-hidden="true"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block", overflow: "visible" }}
    >
      <defs>
        <filter
          id={`${prefix}-shadow`}
          x="-30%"
          y="-30%"
          width="160%"
          height="160%"
        >
          <feDropShadow
            dx="0"
            dy="18"
            stdDeviation="18"
            floodColor="#000000"
            floodOpacity="0.34"
          />
        </filter>
        {Array.from({ length: rows }, (_, row) => (
          <clipPath key={row} id={`${prefix}-row-${row}`}>
            <rect
              x={inset}
              y={inset + row * rowHeight}
              width={innerWidth}
              height={rowHeight + 1}
            />
          </clipPath>
        ))}
      </defs>

      <g filter={`url(#${prefix}-shadow)`}>
        <rect
          x={6}
          y={6}
          width={width - 12}
          height={height - 12}
          rx={46}
          fill={tokens.panel}
          stroke={tokens.accent}
          strokeWidth={7}
        />
        <rect
          x={inset}
          y={inset}
          width={innerWidth}
          height={innerHeight}
          rx={24}
          fill={tokens.background}
          stroke={`${tokens.accent}66`}
          strokeWidth={3}
        />
      </g>

      {showReference ? (
        <line
          x1={poleX}
          x2={poleX}
          y1={inset + 18}
          y2={inset + innerHeight - 18}
          stroke={tokens.accent}
          strokeWidth={12}
          strokeDasharray="22 18"
          opacity={0.52}
        />
      ) : null}

      {Array.from({ length: rows }, (_, row) => {
        const ratio = row / Math.max(1, rows - 1);
        const offset = rollingShutterRowOffset(
          ratio,
          distortion,
          proofProgress,
          innerWidth,
          curvature,
        );
        const rowY = inset + row * rowHeight;
        return (
          <g key={row} clipPath={`url(#${prefix}-row-${row})`}>
            <g transform={`translate(${offset} 0)`}>
              {Array.from({ length: 7 }, (_, column) => (
                <line
                  key={column}
                  x1={inset + (innerWidth * column) / 6}
                  x2={inset + (innerWidth * column) / 6}
                  y1={rowY}
                  y2={rowY + rowHeight + 1}
                  stroke={tokens.accent}
                  strokeWidth={2}
                  opacity={0.24}
                />
              ))}
              <rect
                x={poleX - 15}
                y={inset + 12}
                width={30}
                height={innerHeight - 24}
                rx={15}
                fill={tokens.danger}
              />
            </g>
            <line
              x1={inset}
              x2={inset + innerWidth}
              y1={rowY}
              y2={rowY}
              stroke={tokens.accent}
              strokeWidth={2}
              opacity={0.34}
            />
          </g>
        );
      })}

      {direction === "left-to-right" ? (
        <line
          x1={scanX}
          x2={scanX}
          y1={inset}
          y2={inset + innerHeight}
          stroke={tokens.danger}
          strokeWidth={8}
          opacity={0.92}
          style={{ filter: `drop-shadow(0 0 14px ${tokens.danger})` }}
        />
      ) : (
        <line
          x1={inset}
          x2={inset + innerWidth}
          y1={scanY}
          y2={scanY}
          stroke={tokens.danger}
          strokeWidth={8}
          opacity={0.92}
          style={{ filter: `drop-shadow(0 0 14px ${tokens.danger})` }}
        />
      )}

      <circle cx={width / 2} cy={27} r={8} fill={tokens.danger} />
    </svg>
  );
};
