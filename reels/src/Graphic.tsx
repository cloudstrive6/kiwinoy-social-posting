import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";

const anton = loadAnton();

// KGcolor theme (from the KIWINOY logo): black base, red headline, blue accent.
export const KG = {
  dark: "#0B0B0E",
  red: "#E5322C",
  blue: "#2C5BD8",
  white: "#FFFFFF",
};

export type GraphicProps = {
  image: string | null; // file name in reels/public/
  headline: string;
  sublabel: string; // small label above the headline (e.g. NBA FINALS)
  footer: string; // small line bottom-right (e.g. @kiwinoygamer)
  accent: string; // headline color (defaults to KG red)
  logo: string | null;
  width: number;
  height: number;
};

export const defaultGraphicProps: GraphicProps = {
  image: null,
  headline: "SCROLL STOPPER",
  sublabel: "",
  footer: "@kiwinoygamer",
  accent: KG.red,
  logo: null,
  width: 1080,
  height: 1350,
};

export const Graphic: React.FC<GraphicProps> = ({
  image,
  headline,
  sublabel,
  footer,
  accent,
  logo,
}) => {
  const acc = accent || KG.red;
  return (
    <AbsoluteFill style={{ backgroundColor: KG.dark }}>
      {image ? (
        <Img
          src={staticFile(image)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      ) : null}

      {/* Guarantee a DARK zone behind the headline (top) and the logo/handle
          (bottom) so the red + white text stay high-contrast on ANY photo,
          bright or dark. The middle stays clear so the subject shows. */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(to bottom, rgba(11,11,14,0.94) 0%, rgba(11,11,14,0.84) 20%, rgba(11,11,14,0.42) 38%, rgba(11,11,14,0.12) 55%, rgba(11,11,14,0.52) 80%, rgba(11,11,14,0.95) 100%)",
        }}
      />

      {/* Small uppercase label above the headline. */}
      {sublabel ? (
        <div
          style={{
            position: "absolute",
            top: 70,
            left: 74,
            right: 74,
            fontFamily: anton.fontFamily,
            fontSize: 40,
            letterSpacing: 8,
            color: KG.white,
            textTransform: "uppercase",
            opacity: 0.9,
          }}
        >
          {sublabel}
        </div>
      ) : null}

      {/* The big headline. */}
      <div
        style={{
          position: "absolute",
          top: sublabel ? 130 : 84,
          left: 70,
          right: 70,
          fontFamily: anton.fontFamily,
          fontSize: 156,
          lineHeight: 0.9,
          color: acc,
          textTransform: "uppercase",
          textShadow:
            "0 2px 6px rgba(0,0,0,0.9), 0 8px 34px rgba(0,0,0,0.55)",
        }}
      >
        {headline}
      </div>

      {/* Logo + footer. */}
      {logo ? (
        <div
          style={{
            position: "absolute",
            bottom: 54,
            left: 64,
            width: 128,
            height: 128,
            borderRadius: "50%",
            overflow: "hidden",
            border: "3px solid rgba(255,255,255,0.92)",
            backgroundColor: "#0a0a0f",
          }}
        >
          <Img
            src={staticFile(logo)}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </div>
      ) : (
        <div
          style={{
            position: "absolute",
            bottom: 70,
            left: 74,
            fontFamily: anton.fontFamily,
            fontSize: 56,
            color: KG.white,
          }}
        >
          KG
        </div>
      )}
      {footer ? (
        <div
          style={{
            position: "absolute",
            bottom: 92,
            right: 74,
            fontFamily: anton.fontFamily,
            fontSize: 34,
            letterSpacing: 2,
            color: KG.white,
            opacity: 0.85,
          }}
        >
          {footer}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
