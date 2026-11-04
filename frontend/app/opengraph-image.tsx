import { ImageResponse } from "next/og";
import { LOGO, LOGO_COLORS } from "@/lib/logo";

export const alt = "Lexio: ask the contract, get the page it came from";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 80,
          background: "#f3f5f4",
          color: "#12201c",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <svg width="72" height="72" viewBox="0 0 32 32">
            {LOGO.map(({ role, ...r }, i) => (
              <rect key={i} {...r} fill={LOGO_COLORS[role]} opacity={role === "line" ? 0.6 : 1} />
            ))}
          </svg>
          <div style={{ fontSize: 56, fontWeight: 700, letterSpacing: -1 }}>Lexio</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ fontSize: 96, fontWeight: 700, lineHeight: 1.02, letterSpacing: -3, maxWidth: 980 }}>
            Ask the contract. Get the page it came from.
          </div>
          <div style={{ display: "flex" }}>
            <div style={{ fontSize: 34, background: "#ffc94d", padding: "6px 16px", borderRadius: 6 }}>
              Answers that cite the exact passage
            </div>
          </div>
        </div>
      </div>
    ),
    size,
  );
}
