import React from "react";
import { Composition } from "remotion";
import { Reel, defaultReelProps, ReelProps } from "./Reel";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Reel"
      component={Reel}
      durationInFrames={defaultReelProps.durationInFrames}
      fps={defaultReelProps.fps}
      width={defaultReelProps.width}
      height={defaultReelProps.height}
      defaultProps={defaultReelProps}
      // Real duration / dimensions come from the props file at render time.
      calculateMetadata={({ props }: { props: ReelProps }) => ({
        durationInFrames: props.durationInFrames,
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
