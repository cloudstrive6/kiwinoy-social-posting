import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadBaloo } from "@remotion/google-fonts/Baloo2";

// Sports = condensed athletic caps; Gacha = rounded bold game vibe.
const anton = loadAnton();
const baloo = loadBaloo();

export type Beat = { kind: string; text: string };
export type Clip = { src: string; durationInFrames: number };

export type ReelProps = {
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
  category: string;
  images: string[]; // file names that live in reels/public/
  clips: Clip[]; // gameplay footage clips (preferred over images when present)
  beats: Beat[];
  music: string | null; // file name in reels/public/ or null
  narration: string | null; // AI voiceover file name in reels/public/ or null
  brand: string; // fallback text badge
  logo: string | null; // channel logo file name in reels/public/ or null
};

export const defaultReelProps: ReelProps = {
  fps: 30,
  durationInFrames: 420,
  width: 1080,
  height: 1920,
  category: "gacha",
  images: [],
  clips: [],
  beats: [
    { kind: "hook", text: "Big update just dropped" },
    { kind: "fact", text: "Here is why it matters" },
    { kind: "cta", text: "Follow for more" },
  ],
  music: null,
  narration: null,
  brand: "KG",
  logo: null,
};

const styleFor = (category: string) => {
  const isSports = category === "sports";
  return {
    isSports,
    fontFamily: isSports ? anton.fontFamily : baloo.fontFamily,
    accent: isSports ? "#39ff14" : "#8a5cff", // sports lime / gacha purple
    transform: isSports ? "uppercase" : ("none" as const),
  };
};

// Gameplay footage: each clip plays back-to-back, scaled to fit (contain) over a
// blurred, zoomed copy of itself so landscape gameplay looks clean in 9:16.
const Clips: React.FC<{ clips: { src: string; durationInFrames: number }[] }> = ({
  clips,
}) => {
  let acc = 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {clips.map((c, i) => {
        const from = acc;
        acc += c.durationInFrames;
        return (
          <Sequence key={i} from={from} durationInFrames={c.durationInFrames}>
            <AbsoluteFill>
              <OffthreadVideo
                src={staticFile(c.src)}
                muted
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  filter: "blur(28px) brightness(0.5)",
                  transform: "scale(1.15)",
                }}
              />
              <AbsoluteFill
                style={{ justifyContent: "center", alignItems: "center" }}
              >
                <OffthreadVideo
                  src={staticFile(c.src)}
                  muted
                  style={{
                    width: "100%",
                    height: "auto",
                    maxHeight: "100%",
                    objectFit: "contain",
                  }}
                />
              </AbsoluteFill>
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const Background: React.FC<{ images: string[] }> = ({ images }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  if (images.length === 0) {
    return <AbsoluteFill style={{ backgroundColor: "#0b0b14" }} />;
  }
  const seg = durationInFrames / images.length;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {images.map((img, i) => {
        const start = i * seg;
        const end = start + seg;
        const opacity = interpolate(
          frame,
          [start - 14, start, end - 14, end],
          [0, 1, 1, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
        );
        const scale = interpolate(frame, [start, end], [1.12, 1.3], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const tx = interpolate(frame, [start, end], [-2, 2], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <AbsoluteFill key={i} style={{ opacity }}>
            <Img
              src={staticFile(img)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: `scale(${scale}) translateX(${tx}%)`,
              }}
            />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};

const Scrim: React.FC = () => (
  <AbsoluteFill
    style={{
      background:
        "linear-gradient(to top, rgba(0,0,0,0.88) 0%, rgba(0,0,0,0.35) 34%, rgba(0,0,0,0) 58%), linear-gradient(to bottom, rgba(0,0,0,0.45) 0%, rgba(0,0,0,0) 22%)",
    }}
  />
);

// On-screen channel logo, small, in the top-left corner. Just the logo image
// (no text). Renders nothing if no logo is configured.
const Brand: React.FC<{ logo: string | null }> = ({ logo }) => {
  if (!logo) return null;
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-start",
        alignItems: "flex-start",
        paddingTop: 50,
        paddingLeft: 48,
      }}
    >
      <div
        style={{
          width: 104,
          height: 104,
          borderRadius: 24,
          background: "#0a0a0f",
          border: "3px solid rgba(255,255,255,0.9)",
          boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        <Img
          src={staticFile(logo)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: "scale(1.35)",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

const CaptionCard: React.FC<{
  beat: Beat;
  category: string;
  segFrames: number;
}> = ({ beat, category, segFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { isSports, fontFamily, accent, transform } = styleFor(category);

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 14 });
  const translateY = interpolate(enter, [0, 1], [55, 0]);
  const opacity = interpolate(
    frame,
    [0, 7, segFrames - 10, segFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const isHook = beat.kind === "hook";
  const isCta = beat.kind === "cta";

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: 300,
        paddingLeft: 64,
        paddingRight: 64,
      }}
    >
      <div
        style={{
          opacity,
          transform: `translateY(${translateY}px)`,
          textAlign: "center",
          maxWidth: "92%",
        }}
      >
        {isCta ? (
          <div
            style={{
              fontFamily,
              fontSize: 64,
              color: "#fff",
              background: accent,
              padding: "20px 44px",
              borderRadius: 20,
              textTransform: transform,
              boxShadow: "0 12px 44px rgba(0,0,0,0.55)",
            }}
          >
            {beat.text}
          </div>
        ) : (
          <div
            style={{
              fontFamily,
              color: "#fff",
              fontSize: isHook ? 108 : 86,
              lineHeight: 1.04,
              textTransform: transform,
              textShadow: "0 6px 30px rgba(0,0,0,0.75)",
              borderBottom: `10px solid ${accent}`,
              display: "inline-block",
              paddingBottom: 6,
            }}
          >
            {beat.text}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

const Captions: React.FC<{ beats: Beat[]; category: string }> = ({
  beats,
  category,
}) => {
  const { durationInFrames } = useVideoConfig();
  const seg = durationInFrames / Math.max(beats.length, 1);
  return (
    <>
      {beats.map((b, i) => (
        <Sequence
          key={i}
          from={Math.round(i * seg)}
          durationInFrames={Math.round(seg)}
        >
          <CaptionCard beat={b} category={category} segFrames={Math.round(seg)} />
        </Sequence>
      ))}
    </>
  );
};

const Progress: React.FC<{ accent: string }> = ({ accent }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const w = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end" }}>
      <div style={{ height: 10, width: `${w}%`, background: accent, opacity: 0.95 }} />
    </AbsoluteFill>
  );
};

export const Reel: React.FC<ReelProps> = ({
  images,
  clips,
  beats,
  music,
  narration,
  logo,
  category,
}) => {
  const { accent } = styleFor(category);
  // Duck the music well under the voiceover when narration is present.
  const musicVolume = narration ? 0.16 : 0.6;
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {clips && clips.length > 0 ? (
        <Clips clips={clips} />
      ) : (
        <Background images={images} />
      )}
      <Scrim />
      <Brand logo={logo} />
      <Captions beats={beats} category={category} />
      <Progress accent={accent} />
      {music ? <Audio src={staticFile(music)} volume={musicVolume} /> : null}
      {narration ? <Audio src={staticFile(narration)} volume={1} /> : null}
    </AbsoluteFill>
  );
};
