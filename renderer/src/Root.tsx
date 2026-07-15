import React from "react";
import { Composition, getInputProps } from "remotion";
import { Explainer } from "./compositions/Explainer";
import { projectSchema, type ProjectData } from "./schemas/project";

export const Root: React.FC = () => {
  const data = projectSchema.parse(getInputProps()) as ProjectData;
  const duration = data.scenes.reduce(
    (total, scene) => Math.max(total, scene.start_time + scene.duration),
    0,
  );
  return (
    <Composition
      id="TechShort"
      component={Explainer}
      width={data.width}
      height={data.height}
      fps={data.fps}
      durationInFrames={Math.ceil(duration * data.fps)}
      defaultProps={data}
    />
  );
};
