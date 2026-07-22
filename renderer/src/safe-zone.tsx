import React, { createContext, useContext } from "react";
import { useVideoConfig } from "remotion";
import { DEFAULT_SAFE_ZONE, type SafeZoneInsets } from "./schemas/project";

const SafeZoneContext = createContext<SafeZoneInsets>(DEFAULT_SAFE_ZONE);

export const SafeZoneProvider: React.FC<{
  insets: SafeZoneInsets;
  children: React.ReactNode;
}> = ({ insets, children }) => (
  <SafeZoneContext.Provider value={insets}>{children}</SafeZoneContext.Provider>
);

export type SafeZonePixels = {
  top: number;
  right: number;
  bottom: number;
  left: number;
};

export const safeZonePixels = (
  insets: SafeZoneInsets,
  width: number,
  height: number,
): SafeZonePixels => ({
  top: Math.ceil(insets.top * height),
  right: Math.ceil(insets.right * width),
  bottom: Math.ceil(insets.bottom * height),
  left: Math.ceil(insets.left * width),
});

export const useSafeZone = (): SafeZonePixels => {
  const insets = useContext(SafeZoneContext);
  const { width, height } = useVideoConfig();
  return safeZonePixels(insets, width, height);
};
