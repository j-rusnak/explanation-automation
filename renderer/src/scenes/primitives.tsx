import React from "react";
import type { SceneData } from "../schemas/project";
import { BeforeAfterOverlay, Comparison, LimitationCard } from "./comparisons";
import { AnnotatedChart, ChartReveal, Timeline } from "./data";
import {
  GridWarp,
  MechanismDiagram,
  ParameterSimulation,
  ProcessFlow,
  RasterScan,
  TimeSlice,
} from "./diagrams";
import { EvidenceHighlight, KineticText, SourceReceipt } from "./text-evidence";
import type { PrimitiveProps } from "./shared";

export {
  AnnotatedChart,
  BeforeAfterOverlay,
  ChartReveal,
  Comparison,
  EvidenceHighlight,
  GridWarp,
  KineticText,
  LimitationCard,
  MechanismDiagram,
  ParameterSimulation,
  ProcessFlow,
  RasterScan,
  SourceReceipt,
  TimeSlice,
  Timeline,
};
export type { PrimitiveProps } from "./shared";

const components: Record<SceneData["primitive"], React.FC<PrimitiveProps>> = {
  KineticText,
  SourceReceipt,
  MechanismDiagram,
  ChartReveal,
  ParameterSimulation,
  Comparison,
  LimitationCard,
  RasterScan,
  TimeSlice,
  GridWarp,
  BeforeAfterOverlay,
  AnnotatedChart,
  EvidenceHighlight,
  ProcessFlow,
  Timeline,
};

export const Primitive: React.FC<PrimitiveProps> = ({ scene, themeName }) => {
  const Component = components[scene.primitive];
  return <Component scene={scene} themeName={themeName} />;
};
