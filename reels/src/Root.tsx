import React from "react";
import { Composition } from "remotion";
import { Reel, defaultReelProps, ReelProps } from "./Reel";
import { Graphic, defaultGraphicProps, GraphicProps } from "./Graphic";

export const RemotionRoot: React.FC = () => {
  return (
    <>
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
      {/* Static designed graphic (one PNG) for FB/IG/Threads image posts. */}
      <Composition
        id="Graphic"
        component={Graphic}
        durationInFrames={1}
        fps={1}
        width={defaultGraphicProps.width}
        height={defaultGraphicProps.height}
        defaultProps={defaultGraphicProps}
        calculateMetadata={({ props }: { props: GraphicProps }) => ({
          width: props.width,
          height: props.height,
        })}
      />
    </>
  );
};
