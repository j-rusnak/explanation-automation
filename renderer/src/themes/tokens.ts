export type ThemeName =
  | "kinetic-pop"
  | "blueprint"
  | "signal-lab"
  | "technical-editorial";

export type ThemeTokens = {
  background: string;
  backgroundCss: string;
  panel: string;
  panelBorder: string;
  text: string;
  muted: string;
  accent: string;
  warning: string;
  danger: string;
  citation: string;
  font: string;
  headingFont: string;
  radius: number;
  motif: "pop" | "grid" | "signal" | "paper";
};

export const themes: Record<ThemeName, ThemeTokens> = {
  "kinetic-pop": {
    background: "#0B0D17",
    backgroundCss:
      "radial-gradient(circle at 86% 8%, #7657FFaa 0, transparent 34%), radial-gradient(circle at 10% 82%, #FF4F6D77 0, transparent 28%), linear-gradient(145deg, #0B0D17 0%, #171A2E 58%, #0B0D17 100%)",
    panel: "#171A2E",
    panelBorder: "#7657FF",
    text: "#FFF8E7",
    muted: "#D4CEE3",
    accent: "#24E5FF",
    warning: "#FFD84A",
    danger: "#FF4F6D",
    citation: "#B8AAFF",
    font: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    headingFont: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    radius: 18,
    motif: "pop",
  },
  blueprint: {
    background: "#071124",
    backgroundCss:
      "radial-gradient(circle at 84% 8%, #183866 0, #071124 46%), linear-gradient(135deg, #071124, #0c1931)",
    panel: "#13213d",
    panelBorder: "#2d4670",
    text: "#f7f9ff",
    muted: "#b7c4e2",
    accent: "#5eead4",
    warning: "#ffd166",
    danger: "#ff6b6b",
    citation: "#a8b7ff",
    font: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    headingFont: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    radius: 28,
    motif: "grid",
  },
  "signal-lab": {
    background: "#07130f",
    backgroundCss:
      "radial-gradient(circle at 18% 15%, #174332 0, #07130f 42%), linear-gradient(145deg, #07130f, #0a2119)",
    panel: "#102c22",
    panelBorder: "#285844",
    text: "#f4fff9",
    muted: "#afd5c2",
    accent: "#6df7ad",
    warning: "#ffce5c",
    danger: "#ff786f",
    citation: "#8ed8ff",
    font: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    headingFont: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    radius: 16,
    motif: "signal",
  },
  "technical-editorial": {
    background: "#f3efe5",
    backgroundCss:
      "linear-gradient(125deg, #f8f5ed 0, #ebe4d5 74%, #d9cfbd 100%)",
    panel: "#fffdf7",
    panelBorder: "#b9ad99",
    text: "#172033",
    muted: "#5b6370",
    accent: "#006d77",
    warning: "#9c4f10",
    danger: "#a42a2a",
    citation: "#31558a",
    font: '"Atkinson Hyperlegible", Arial, Helvetica, sans-serif',
    headingFont: 'Georgia, "Times New Roman", serif',
    radius: 8,
    motif: "paper",
  },
};

// A compatibility alias for older imports and tests.
export const theme = themes.blueprint;
export const getTheme = (name: ThemeName): ThemeTokens => themes[name];
