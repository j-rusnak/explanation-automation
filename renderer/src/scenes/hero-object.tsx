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

export type ReadoutDirection =
  | "top-to-bottom"
  | "bottom-to-top"
  | "left-to-right";

export const sensorRowReadoutStrength = (
  rowRatio: number,
  scanProgress: number,
  direction: ReadoutDirection,
): number => {
  const scan = clamp01(scanProgress);
  if (direction === "left-to-right") return scan;
  const leadingRatio =
    direction === "bottom-to-top" ? 1 - clamp01(rowRatio) : clamp01(rowRatio);
  const feather = 0.085;
  return clamp01((scan - leadingRatio + feather) / feather);
};

export const readoutDirectionLabel = (direction: ReadoutDirection): string =>
  direction === "bottom-to-top"
    ? "BOTTOM → TOP"
    : direction === "left-to-right"
      ? "LEFT → RIGHT"
      : "TOP → BOTTOM";

export type RollingShutterHeroProps = {
  tokens: ThemeTokens;
  idPrefix: string;
  progress: number;
  distortion: number;
  scanProgress?: number;
  direction?: ReadoutDirection;
  curvature?: number;
  immediateProof?: boolean;
  showReference?: boolean;
  captureMode?: "rolling" | "shared";
  readoutLabel?: string;
  width?: number;
  height?: number;
};

const safeId = (value: string): string => value.replace(/[^a-z0-9_-]/giu, "-");

/**
 * A scene-independent, deterministic sensor hero. It accepts only validated
 * theme and numeric data, making it safe to reuse in scenes and cover renders.
 */
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
  captureMode = "rolling",
  readoutLabel,
  width = 760,
  height = 610,
}) => {
  const rows = 18;
  const shellInset = Math.round(Math.min(width, height) * 0.045);
  const sensorX = shellInset + Math.round(width * 0.035);
  const sensorY = Math.max(58, Math.round(height * 0.135));
  const footerHeight = Math.max(48, Math.round(height * 0.105));
  const innerWidth = width - sensorX * 2;
  const innerHeight = height - sensorY - footerHeight;
  const rowHeight = innerHeight / rows;
  const proofProgress = rollingShutterProofProgress(progress, immediateProof);
  const scan = clamp01(scanProgress);
  const completion = captureMode === "shared" ? proofProgress : scan;
  const prefix = safeId(idPrefix);
  const poleX = sensorX + innerWidth * 0.46;
  const scanY =
    direction === "bottom-to-top"
      ? sensorY + innerHeight * (1 - scan)
      : sensorY + innerHeight * scan;
  const scanX = sensorX + innerWidth * scan;
  const labelSize = Math.max(22, Math.min(32, width * 0.06));
  const status =
    readoutLabel ??
    (captureMode === "shared" ? "SHARED EXPOSURE" : "ROW READOUT");

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
          height="170%"
        >
          <feDropShadow
            dx="0"
            dy="20"
            stdDeviation="20"
            floodColor="#000000"
            floodOpacity="0.38"
          />
        </filter>
        <linearGradient id={`${prefix}-shell`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={tokens.panelBorder} stopOpacity="0.48" />
          <stop offset="0.22" stopColor={tokens.panel} />
          <stop offset="1" stopColor={tokens.background} />
        </linearGradient>
        <linearGradient id={`${prefix}-glass`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={tokens.background} />
          <stop offset="1" stopColor={tokens.panel} stopOpacity="0.92" />
        </linearGradient>
        <clipPath id={`${prefix}-sensor`}>
          <rect
            x={sensorX}
            y={sensorY}
            width={innerWidth}
            height={innerHeight}
            rx={Math.max(14, shellInset * 0.65)}
          />
        </clipPath>
        {Array.from({ length: rows }, (_, row) => (
          <clipPath key={row} id={`${prefix}-row-${row}`}>
            <rect
              x={sensorX}
              y={sensorY + row * rowHeight}
              width={innerWidth}
              height={rowHeight + 1}
            />
          </clipPath>
        ))}
      </defs>

      <rect
        x={shellInset + 12}
        y={shellInset + 18}
        width={width - shellInset * 2}
        height={height - shellInset * 2}
        rx={Math.max(28, shellInset * 1.35)}
        fill={tokens.danger}
        opacity={0.34}
      />
      <g filter={`url(#${prefix}-shadow)`}>
        <rect
          x={shellInset}
          y={shellInset}
          width={width - shellInset * 2}
          height={height - shellInset * 2}
          rx={Math.max(28, shellInset * 1.35)}
          fill={`url(#${prefix}-shell)`}
          stroke={tokens.panelBorder}
          strokeWidth={3}
        />
        <path
          d={`M ${shellInset + 26} ${shellInset + 3} H ${width - shellInset - 38}`}
          stroke={tokens.text}
          strokeWidth={3}
          strokeLinecap="round"
          opacity={0.22}
        />
        <rect
          x={sensorX}
          y={sensorY}
          width={innerWidth}
          height={innerHeight}
          rx={Math.max(14, shellInset * 0.65)}
          fill={`url(#${prefix}-glass)`}
          stroke={tokens.accent}
          strokeWidth={4}
        />
      </g>

      <text
        x={sensorX}
        y={sensorY - 22}
        fill={tokens.text}
        fontFamily={tokens.font}
        fontSize={labelSize}
        fontWeight={850}
        letterSpacing={1.6}
      >
        SENSOR
      </text>
      <text
        x={sensorX + innerWidth}
        y={sensorY - 22}
        textAnchor="end"
        fill={captureMode === "shared" ? tokens.accent : tokens.warning}
        fontFamily={tokens.font}
        fontSize={labelSize}
        fontWeight={900}
        letterSpacing={1.3}
      >
        {status}
      </text>

      <g clipPath={`url(#${prefix}-sensor)`}>
        {showReference ? (
          <line
            x1={poleX}
            x2={poleX}
            y1={sensorY + 12}
            y2={sensorY + innerHeight - 12}
            stroke={tokens.text}
            strokeWidth={10}
            strokeDasharray="18 14"
            opacity={0.38}
          />
        ) : null}

        {Array.from({ length: rows }, (_, row) => {
          const ratio = row / Math.max(1, rows - 1);
          const readStrength =
            captureMode === "shared"
              ? proofProgress
              : sensorRowReadoutStrength(ratio, scan, direction);
          const assemblyProgress = immediateProof
            ? proofProgress
            : Math.min(proofProgress, readStrength);
          const offset = rollingShutterRowOffset(
            ratio,
            captureMode === "shared" ? 0 : distortion,
            assemblyProgress,
            innerWidth,
            curvature,
          );
          const rowY = sensorY + row * rowHeight;
          return (
            <g key={row} clipPath={`url(#${prefix}-row-${row})`}>
              <g transform={`translate(${offset} 0)`}>
                {Array.from({ length: 7 }, (_, column) => (
                  <line
                    key={column}
                    x1={sensorX + (innerWidth * column) / 6}
                    x2={sensorX + (innerWidth * column) / 6}
                    y1={rowY}
                    y2={rowY + rowHeight + 1}
                    stroke={tokens.citation}
                    strokeWidth={2}
                    opacity={0.18 + readStrength * 0.3}
                  />
                ))}
                <rect
                  x={poleX - 14}
                  y={sensorY + 10}
                  width={28}
                  height={innerHeight - 20}
                  rx={14}
                  fill={
                    captureMode === "shared" ? tokens.accent : tokens.danger
                  }
                  opacity={0.58 + readStrength * 0.42}
                />
              </g>
              <line
                x1={sensorX}
                x2={sensorX + innerWidth}
                y1={rowY}
                y2={rowY}
                stroke={readStrength > 0.5 ? tokens.accent : tokens.panelBorder}
                strokeWidth={2}
                opacity={0.24 + readStrength * 0.42}
              />
            </g>
          );
        })}

        {captureMode === "shared" ? (
          <rect
            x={sensorX + 2}
            y={sensorY + 2}
            width={innerWidth - 4}
            height={innerHeight - 4}
            rx={Math.max(12, shellInset * 0.58)}
            fill={tokens.accent}
            opacity={0.04 + proofProgress * 0.12}
          />
        ) : direction === "left-to-right" ? (
          <line
            x1={scanX}
            x2={scanX}
            y1={sensorY}
            y2={sensorY + innerHeight}
            stroke={tokens.warning}
            strokeWidth={7}
            opacity={0.96}
            style={{ filter: `drop-shadow(0 0 13px ${tokens.warning})` }}
          />
        ) : (
          <line
            x1={sensorX}
            x2={sensorX + innerWidth}
            y1={scanY}
            y2={scanY}
            stroke={tokens.warning}
            strokeWidth={7}
            opacity={0.96}
            style={{ filter: `drop-shadow(0 0 13px ${tokens.warning})` }}
          />
        )}
      </g>

      <rect
        x={sensorX}
        y={sensorY + innerHeight + 18}
        width={innerWidth}
        height={9}
        rx={4.5}
        fill={tokens.panelBorder}
        opacity={0.62}
      />
      <rect
        x={sensorX}
        y={sensorY + innerHeight + 18}
        width={innerWidth * completion}
        height={9}
        rx={4.5}
        fill={captureMode === "shared" ? tokens.accent : tokens.warning}
      />
      <text
        x={sensorX}
        y={sensorY + innerHeight + 48}
        fill={tokens.muted}
        fontFamily={tokens.font}
        fontSize={labelSize}
        fontWeight={750}
        letterSpacing={1.1}
      >
        {captureMode === "shared"
          ? "ALL ROWS TOGETHER"
          : readoutDirectionLabel(direction)}
      </text>
      <text
        x={sensorX + innerWidth}
        y={sensorY + innerHeight + 48}
        textAnchor="end"
        fill={tokens.text}
        fontFamily={tokens.font}
        fontSize={labelSize}
        fontWeight={850}
      >
        {Math.round(completion * 100)}%
      </text>
    </svg>
  );
};
