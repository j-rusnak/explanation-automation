export type RenderMode = "preview" | "final" | "cover";

export interface RenderCommandOptions {
  mode: RenderMode;
  output: string;
  props: string;
  scale: number;
}

export declare const buildRemotionArgs: (
  options: RenderCommandOptions,
) => string[];
