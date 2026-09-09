import React from "react";
import { loadFont as loadDMMono } from "@remotion/google-fonts/DMMono";
import { loadFont as loadSpaceGrotesk } from "@remotion/google-fonts/SpaceGrotesk";
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

const { fontFamily: mono } = loadDMMono("normal", {
  weights: ["400", "500"],
  subsets: ["latin"],
});
const { fontFamily: display } = loadSpaceGrotesk("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

const C = {
  bg: "#050807",
  panel: "rgba(10,16,13,.92)",
  panel2: "#0e1813",
  mint: "#86ffb4",
  bright: "#86ffb4",
  green: "#42dc88",
  cyan: "#22d3ee",
  gold: "#e2b65d",
  ink: "#e8efe8",
  muted: "#829289",
  dim: "#365b48",
  line: "#1d3328",
  line2: "#173023",
  red: "#ff7b73",
};

// ──────────────────────────────────────────────────────────────
// shared primitives
// ──────────────────────────────────────────────────────────────
const fade = (frame: number, duration = 18) => ({
  opacity: interpolate(frame, [0, duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }),
});
const rise = (frame: number, duration = 22, distance = 30) => ({
  transform: `translateY(${interpolate(frame, [0, duration], [distance, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  })}px)`,
});

const Logo: React.FC<{ size?: number }> = ({ size = 48 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 200 200"
    aria-label="Praetor logo"
    role="img"
    style={{ flex: "0 0 auto", filter: `drop-shadow(0 0 ${size / 3}px rgba(134,255,180,.18))` }}
  >
    <defs>
      <linearGradient id="praetor-video-logo" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#7cffb2" />
        <stop offset="1" stopColor="#22d3ee" />
      </linearGradient>
    </defs>
    <g transform="rotate(-18 100 100)">
      <path
        d="M60 132 A56 56 0 1 1 150 78"
        fill="none"
        stroke="url(#praetor-video-logo)"
        strokeWidth="12"
        strokeLinecap="round"
      />
      <circle cx="150" cy="78" r="13" fill="#7cffb2" />
      <circle cx="100" cy="100" r="24" fill="none" stroke="#7cffb2" strokeWidth="6" />
      <circle cx="100" cy="100" r="10" fill="#7cffb2" />
    </g>
  </svg>
);

const Grid: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      opacity: 0.25,
      backgroundImage: `linear-gradient(rgba(134,255,180,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(134,255,180,.04) 1px, transparent 1px), radial-gradient(900px 500px at 16% 0%, rgba(134,255,180,.12), transparent 65%)`,
      backgroundSize: "72px 72px, 72px 72px, 100% 100%",
      maskImage: "linear-gradient(to bottom, black, transparent 92%)",
    }}
  />
);

const Header: React.FC<{ section?: string }> = ({ section }) => (
  <div
    style={{
      position: "absolute",
      top: 54,
      left: 74,
      right: 74,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      fontFamily: mono,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <Logo />
      <div>
        <div
          style={{
            color: C.ink,
            fontFamily: display,
            fontWeight: 700,
          fontSize: 23,
          letterSpacing: ".16em",
          }}
        >
          PRAETOR
        </div>
        <div
          style={{
            color: C.muted,
            fontSize: 11,
            letterSpacing: 3,
            textTransform: "uppercase",
          }}
        >
          memory-backed coordination
        </div>
      </div>
    </div>
    <div style={{ color: C.muted, fontSize: 12, letterSpacing: 2 }}>
      {section ?? "PRODUCT DEMO"}{" "}
      <span style={{ color: C.mint }}>// VERIFIED COORDINATION</span>
    </div>
  </div>
);

const Panel: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ children, style }) => (
  <div
    style={{
      position: "relative",
      background: C.panel,
      border: `1px solid ${C.line}`,
      borderRadius: 0,
      padding: 29,
      ...style,
    }}
  >
    {children}
  </div>
);

const Label: React.FC<{ children: React.ReactNode; color?: string }> = ({
  children,
  color,
}) => (
  <div
    style={{
      color: color ?? C.muted,
      fontFamily: mono,
      fontSize: 12,
      letterSpacing: 3,
      textTransform: "uppercase",
    }}
  >
    {children}
  </div>
);

const Dot: React.FC<{ color?: string }> = ({ color = C.mint }) => (
  <span
    style={{
      width: 10,
      height: 10,
      borderRadius: "50%",
      background: color,
      display: "inline-block",
      boxShadow: `0 0 14px ${color}`,
    }}
  />
);

const Chip: React.FC<{ label: string; on?: boolean; sub?: string }> = ({
  label,
  on = true,
  sub,
}) => (
  <span
    style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: "6px 12px",
      borderRadius: 999,
      border: `1px solid ${on ? "rgba(61,245,160,.45)" : "rgba(255,107,107,.4)"}`,
      color: on ? C.mint : C.red,
      fontFamily: mono,
      fontSize: 12,
      letterSpacing: 1.3,
      textTransform: "uppercase",
      background: C.panel2,
    }}
  >
    <span
      style={{
        width: 6,
        height: 6,
        borderRadius: 999,
        background: "currentColor",
      }}
    />
    <b style={{ color: C.ink }}>{label}</b>
    {sub && <span style={{ color: C.muted }}>· {sub}</span>}
  </span>
);

// ──────────────────────────────────────────────────────────────
// 1) INTRO  (3s = 90 frames @ 30fps)
// ──────────────────────────────────────────────────────────────
const Intro: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ frame: f, fps, config: { damping: 14, mass: 0.6 } });
  return (
    <AbsoluteFill
      style={{
        ...fade(f, 10),
        background: C.bg,
        color: C.ink,
        fontFamily: display,
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      <Grid />
      <div style={{ transform: `scale(${scale})`, zIndex: 1 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 30 }}>
          <Logo size={104} />
        </div>
        <div style={{ fontSize: 104, fontWeight: 500, letterSpacing: "-.055em" }}>
          PRAETOR<span style={{ color: C.mint }}>.</span>
        </div>
        <div
          style={{
            marginTop: 14,
            color: C.muted,
            fontFamily: mono,
            fontSize: 18,
            letterSpacing: 6,
            textTransform: "uppercase",
          }}
        >
           Memory and settlement for autonomous systems
        </div>
        <div
          style={{
            margin: "34px auto 0",
            width: 340,
            height: 1,
            background: `linear-gradient(90deg, transparent, ${C.mint}, transparent)`,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 2) PROBLEM  (15s = 450 frames)  — 3 beats:
//    Beat A (0-100)  the wrong question
//    Beat B (100-200) the failure everyone forgets
//    Beat C (200-300) the next router doesn't know
// ──────────────────────────────────────────────────────────────
const Problem: React.FC = () => {
  const f = useCurrentFrame();
  const beatA = f < 105 ? 1 : interpolate(f, [105, 125], [1, 0], { extrapolateRight: "clamp" });
  const beatB =
    f < 100 ? 0 : f < 205 ? interpolate(f, [100, 120], [0, 1], { extrapolateRight: "clamp" })
                          : interpolate(f, [205, 225], [1, 0], { extrapolateRight: "clamp" });
  const beatC = f < 200 ? 0 : interpolate(f, [200, 220], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink }}>
      <Grid />
      <Header section="01 // THE PROBLEM" />

      {/* Beat A — static descriptions */}
      <div
        style={{
          position: "absolute",
          left: 130,
          right: 130,
          top: 210,
          opacity: beatA,
          transform: `translateY(${(1 - beatA) * -20}px)`,
        }}
      >
        <Label>Beat 01 · Static orchestration</Label>
        <h1
          style={{
            fontFamily: display,
            fontSize: 68,
            lineHeight: 1.08,
            margin: "22px 0 34px",
            letterSpacing: -2,
            maxWidth: 1180,
          }}
        >
           Agents can do the work.
           <br />
           <span style={{ color: C.muted }}>They just don't remember who did it well.</span>
        </h1>
        <div style={{ display: "flex", gap: 24, alignItems: "stretch" }}>
          <Panel style={{ flex: 1 }}>
             <Label color={C.gold}>What the agent claims</Label>
            <div style={{ marginTop: 22, fontFamily: mono, fontSize: 20, lineHeight: 1.9 }}>
              <div>
                <span style={{ color: C.muted }}>capabilities</span>:{" "}
                <span style={{ color: C.bright }}>["risk", "audit"]</span>
              </div>
              <div>
                <span style={{ color: C.muted }}>self_score</span>:{" "}
                <span style={{ color: C.bright }}>0.94</span>
              </div>
              <div>
                <span style={{ color: C.muted }}>bio</span>:{" "}
                <span style={{ color: C.bright }}>
                  "expert in liquidity-lock analysis"
                </span>
              </div>
            </div>
          </Panel>
          <Panel style={{ flex: 1 }}>
            <Label color={C.mint}>What the router does</Label>
            <div style={{ marginTop: 22, fontFamily: mono, fontSize: 20, lineHeight: 1.9 }}>
              <div>
                <span style={{ color: C.muted }}>router.select</span>({" "}
                <span style={{ color: C.gold }}>claim</span> )
              </div>
              <div style={{ color: C.mint }}>→ atlas-risk-07</div>
              <div style={{ color: C.muted, fontSize: 15, marginTop: 12 }}>
                 No persistent record of performance.
              </div>
            </div>
          </Panel>
        </div>
      </div>

      {/* Beat B — the failure everyone forgets */}
      <div
        style={{
          position: "absolute",
          left: 130,
          right: 130,
          top: 210,
          opacity: beatB,
          transform: `translateY(${(1 - beatB) * 30}px)`,
        }}
      >
        <Label>Beat 02 · The failure everyone forgets</Label>
        <h1
          style={{
            fontFamily: display,
            fontSize: 68,
            lineHeight: 1.08,
            margin: "22px 0 34px",
            letterSpacing: -2,
            maxWidth: 1200,
          }}
        >
           A job can succeed once.
           <span style={{ color: C.red }}> The failure still matters.</span>
        </h1>
        <Panel style={{ width: 1200 }}>
          <Label color={C.red}>incident.log · 2026-08-14</Label>
          <div style={{ marginTop: 20, fontFamily: mono, fontSize: 19, lineHeight: 2.0 }}>
            <div>
              <span style={{ color: C.muted }}>job_id</span>:{" "}
              <span style={{ color: C.bright }}>base-lend-audit-4471</span>
            </div>
            <div>
              <span style={{ color: C.muted }}>worker</span>:{" "}
              <span style={{ color: C.bright }}>atlas-risk-07</span>{" "}
              <span style={{ color: C.muted }}>(self_score 0.94)</span>
            </div>
            <div>
              <span style={{ color: C.muted }}>outcome</span>:{" "}
              <span style={{ color: C.red }}>
                 missed liquidity-lock evidence — protocol drained later
              </span>
            </div>
            <div style={{ marginTop: 8 }}>
              <span style={{ color: C.muted }}>router.state after crash</span>:{" "}
              <span style={{ color: C.red }}>∅ (in-memory, gone)</span>
            </div>
          </div>
        </Panel>
      </div>

      {/* Beat C — the same job routes to the same failure */}
      <div
        style={{
          position: "absolute",
          left: 130,
          right: 130,
          top: 210,
          opacity: beatC,
          transform: `translateY(${(1 - beatC) * 30}px)`,
        }}
      >
        <Label>Beat 03 · The next router doesn't know</Label>
        <h1
          style={{
            fontFamily: display,
            fontSize: 68,
            lineHeight: 1.08,
            margin: "22px 0 30px",
            letterSpacing: -2,
            maxWidth: 1180,
          }}
        >
           Without memory, the next decision starts from zero.
        </h1>
        <div style={{ display: "flex", gap: 22, alignItems: "stretch" }}>
          <Panel style={{ flex: 1 }}>
            <Label>Fresh session · 2026-08-15 08:04</Label>
            <div style={{ marginTop: 18, fontFamily: mono, fontSize: 19, lineHeight: 1.95 }}>
              <div>
                <span style={{ color: C.muted }}>router.load(</span>
                <span style={{ color: C.gold }}>reputation</span>
                <span style={{ color: C.muted }}>)</span>
              </div>
              <div style={{ color: C.red }}>
                → NotFoundError: no persisted state
              </div>
              <div style={{ color: C.muted, marginTop: 12 }}>
                 Same claim reads. No history to inform the route.
              </div>
            </div>
          </Panel>
          <Panel style={{ flex: 1, borderColor: C.mint }}>
            <Label color={C.mint}>What Praetor does instead</Label>
            <div style={{ marginTop: 18, fontFamily: mono, fontSize: 19, lineHeight: 1.95 }}>
              <div>
                <span style={{ color: C.muted }}>memory.load_worker(</span>
                <span style={{ color: C.bright }}>"atlas-risk-07"</span>
                <span style={{ color: C.muted }}>)</span>
              </div>
              <div style={{ color: C.mint }}>
                → failures: 1 · requires_review: true
              </div>
              <div style={{ color: C.muted, marginTop: 12 }}>
                 Route changes before the job is dispatched.
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 3) PRAETOR  (7s = 210 frames)
// ──────────────────────────────────────────────────────────────
const PraetorThesis: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink, justifyContent: "center", alignItems: "center", textAlign: "center" }}>
      <Grid />
      <div style={{ zIndex: 1, ...fade(f), ...rise(f, 24, 20) }}>
        <Label color={C.gold}>02 // PRAETOR</Label>
        <h2 style={{ fontFamily: display, fontSize: 74, lineHeight: 1.08, margin: "24px 0 30px" }}>
          Trust is not a claim.<br /><span style={{ color: C.mint }}>It is a record.</span>
        </h2>
        <div style={{ color: C.muted, fontFamily: mono, fontSize: 20, lineHeight: 1.7, maxWidth: 1060 }}>
          Memory and settlement for autonomous systems.<br />
          Route work. Verify results. Let every outcome shape the next decision.
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 4) FLOW  (10s = 300 frames)  — the six-step product loop
// ──────────────────────────────────────────────────────────────
const Flow: React.FC = () => {
  const f = useCurrentFrame();
  const nodes: Array<[string, string, string, string]> = [
    ["01", "REQUEST", "POST /api/jobs", "Task and category enter Praetor."],
    ["02", "ROUTE", "memory.load_worker()", "Sibyl recalls performance, not just claims."],
    ["03", "EXECUTE", "worker.execute(job)", "The selected specialist returns evidence."],
    ["04", "VERIFY", "verifier.verify(result)", "Unverified work cannot be settled."],
    ["05", "RECORD", "record_event + receipt", "The outcome updates the worker record."],
    ["06", "INFORM", "next decision", "The next route starts with history."],
  ];
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink }}>
      <Grid />
       <Header section="03 // THE PRAETOR LOOP" />
      <div style={{ position: "absolute", top: 220, left: 120, right: 120 }}>
         <Label>One job. One durable loop.</Label>
        <h2 style={{ fontFamily: display, fontSize: 52, margin: "20px 0 60px" }}>
           Every outcome informs the next decision
          <span style={{ color: C.mint }}>.</span>
        </h2>
        <div style={{ display: "flex", alignItems: "stretch", gap: 18 }}>
          {nodes.map(([n, title, code, text], i) => {
            const x = interpolate(f, [i * 12, i * 12 + 22], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <React.Fragment key={n}>
                <Panel
                  style={{
                     flex: 1,
                     minWidth: 0,
                    opacity: x,
                    transform: `translateY(${(1 - x) * 35}px)`,
                  }}
                >
                  <div style={{ color: C.mint, fontFamily: mono, fontSize: 14, letterSpacing: 2 }}>
                    {n}
                  </div>
                  <div
                    style={{
                      fontFamily: display,
                      fontWeight: 700,
                       fontSize: 22,
                      margin: "28px 0 8px",
                    }}
                  >
                    {title}
                  </div>
                  <div
                    style={{
                      fontFamily: mono,
                      color: C.bright,
                     fontSize: 13,
                      marginBottom: 14,
                    }}
                  >
                    {code}
                  </div>
                   <div style={{ fontFamily: mono, color: C.muted, fontSize: 13, lineHeight: 1.5 }}>
                    {text}
                  </div>
                </Panel>
                 {i < 5 && (
                  <div style={{ alignSelf: "center", color: C.mint, fontSize: 30, opacity: x }}>
                    →
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
        <div
          style={{
            marginTop: 26,
            padding: "15px 20px",
            border: `1px solid ${C.line2}`,
            background: "rgba(14,24,19,.72)",
            display: "flex",
            alignItems: "center",
            gap: 18,
            fontFamily: mono,
            fontSize: 14,
          }}
        >
          <span style={{ color: C.gold }}>CLIENT</span>
          <span style={{ color: C.muted }}>request</span>
          <span style={{ color: C.mint }}>→</span>
          <span style={{ color: C.bright }}>PRAETOR</span>
          <span style={{ color: C.muted }}>routes, verifies, records</span>
          <span style={{ color: C.mint }}>→</span>
          <span style={{ color: C.bright }}>WORKER</span>
          <span style={{ color: C.muted }}>returns evidence</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 5) MEMORY  (9s = 270 frames)  — WARM entities + COLD events + multi-worker
// ──────────────────────────────────────────────────────────────
const Memory: React.FC = () => {
  const f = useCurrentFrame();
  const fill = interpolate(f, [8, 90], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const workers: Array<[string, string, string, string]> = [
    ["atlas-risk-07", "missed liquidity-lock evidence", "REQUIRES REVIEW", C.gold],
    ["sentinel-03", "no prior failures · 12 completions", "TRUSTED", C.mint],
    ["nova-audit", "cold-start · no history", "COLD-START", C.muted],
  ];
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink }}>
      <Grid />
      <Header section="04 // SIBYL MEMORY" />
      <div
        style={{
          position: "absolute",
          top: 210,
          left: 130,
          right: 130,
          display: "flex",
          gap: 60,
          alignItems: "flex-start",
        }}
      >
        <div style={{ flex: 1, ...fade(f) }}>
          <Label>Load-bearing memory</Label>
          <h2
            style={{
              fontFamily: display,
              fontSize: 60,
              lineHeight: 1.06,
              margin: "20px 0",
            }}
          >
            Memory is not a log
            <span style={{ color: C.mint }}>.</span>
            <br />
            <span style={{ color: C.mint }}>It is the control plane.</span>
          </h2>
          <p
            style={{
              color: C.muted,
              fontFamily: mono,
              fontSize: 17,
              lineHeight: 1.7,
              maxWidth: 560,
            }}
          >
            Sibyl backs five tiers. Every routing decision reads from
            three of them; every job completion writes to four.
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 26, flexWrap: "wrap" }}>
            <Chip label="WARM" sub="worker entities" />
            <Chip label="COLD" sub="job events" />
            <Chip label="HOT" sub="live counters" />
            <Chip label="REFERENCE" sub="immutable receipts" />
            <Chip label="SEARCH" sub="semantic index" />
          </div>
          <div
            style={{
              color: C.muted,
              fontFamily: mono,
              fontSize: 13,
              marginTop: 20,
              maxWidth: 560,
              lineHeight: 1.6,
            }}
          >
            Kill the process. Restart. On the first request, Sibyl has already
            rehydrated every worker's reputation — no warm-up, no re-seed.
          </div>
        </div>
        <Panel style={{ width: 720, padding: 32, ...fade(f, 20), ...rise(f) }}>
          <Label>Sibyl Memory · WARM tier · live recall</Label>
          <div style={{ marginTop: 22, fontFamily: mono }}>
            {workers.map(([name, note, status, color]) => (
              <div
                key={name}
                style={{
                  padding: "18px 0",
                  borderBottom: `1px solid ${C.line2}`,
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto",
                  gap: 14,
                  alignItems: "center",
                }}
              >
                <Dot color={color} />
                <div>
                  <div style={{ color: C.bright, fontSize: 17 }}>{name}</div>
                  <div style={{ color: C.muted, fontSize: 13, marginTop: 4 }}>
                    {note}
                  </div>
                </div>
                <div style={{ color, fontSize: 11, letterSpacing: 1.5 }}>
                  {status}
                </div>
              </div>
            ))}
            <div
              style={{
                marginTop: 22,
                height: 8,
                background: "#10251a",
                borderRadius: 5,
              }}
            >
              <div
                style={{
                  width: `${fill}%`,
                  height: "100%",
                  background: C.mint,
                  borderRadius: 5,
                  boxShadow: `0 0 12px ${C.mint}`,
                }}
              />
            </div>
            <div style={{ color: C.muted, fontSize: 13, marginTop: 10 }}>
              WARM rehydrate complete · WorkerProfile ×3 · reliability derived
            </div>
          </div>
        </Panel>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 6) DASHBOARD  (18s = 540 frames)  — the product demo is the hero
// ──────────────────────────────────────────────────────────────
const Dashboard: React.FC = () => {
  const f = useCurrentFrame();
  const workers: Array<[string, string, string, string]> = [
    ["sentinel-03", "92%", "trusted", C.mint],
    ["atlas-risk-07", "64%", "review", C.gold],
    ["nova-audit", "88%", "trusted", C.mint],
  ];
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink }}>
      <Grid />
      <Header section="05 // LIVE DEMO" />
      <div style={{ position: "absolute", top: 180, left: 110, right: 110, ...fade(f) }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            marginBottom: 22,
          }}
        >
          <div>
            <Label>REQUEST // ROUTE // REPUTATION</Label>
            <h2 style={{ fontFamily: display, fontSize: 46, margin: "12px 0 0" }}>
              Submit one job. Watch the record change.
            </h2>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Chip label="Memory" sub="sibyl" />
            <Chip label="Base" sub="chain 84532" />
             <Chip label="Virtuals" sub="on" />
          </div>
        </div>

        {/* Live environment strip, matching the deployed operator console. */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            padding: "16px 22px",
            border: `1px solid ${C.line}`,
            borderRadius: 12,
            marginBottom: 20,
            background: C.panel,
          }}
        >
          <div style={{ fontFamily: display, fontWeight: 700, fontSize: 34, color: C.ink, lineHeight: 1 }}>
            Sepolia <span style={{ color: C.muted, fontSize: 20 }}>· 84532</span>
          </div>
          <div style={{ fontFamily: mono, fontSize: 14, color: C.muted, lineHeight: 1.6 }}>
            <b style={{ color: C.mint }}>CONNECTED</b> · signer ready<br />
            Base Sepolia · settlement reference recorded
          </div>
          <div style={{ marginLeft: "auto", color: C.mint, fontFamily: mono, fontSize: 14 }}>
            <Dot /> CONTROL PLANE ONLINE
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.05fr .95fr", gap: 18 }}>
          <Panel>
            <Label>POST /api/jobs · from any client</Label>
            <pre
              style={{
                marginTop: 22,
                padding: 20,
                background: C.panel2,
                border: `1px solid ${C.line}`,
                borderRadius: 10,
                fontFamily: mono,
                fontSize: 14,
                lineHeight: 1.75,
                color: C.bright,
                whiteSpace: "pre",
                overflow: "hidden",
              }}
            >
{`$ curl -X POST $HOST/api/jobs \\
    -H 'Content-Type: application/json' \\
    -d '{
      "task": "Review a Base lending protocol",
      "category": "risk",
      "value_usdc": 0
    }'`}
            </pre>
            <div
              style={{
                marginTop: 18,
                fontFamily: mono,
                color: C.muted,
                fontSize: 13,
                lineHeight: 1.65,
              }}
            >
              Praetor routes by remembered performance, then records the result.
            </div>
          </Panel>
          <Panel>
            <Label>Worker reputation · recalled</Label>
            {workers.map(([name, score, status, color], i) => (
              <div
                key={name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  padding: "22px 0",
                  borderBottom: i < workers.length - 1 ? `1px solid ${C.line}` : 0,
                  fontFamily: mono,
                }}
              >
                <Dot color={color} />
                <div style={{ flex: 1, fontSize: 16 }}>{name}</div>
                <div style={{ color }}>{score}</div>
                <div style={{ color: C.muted, fontSize: 11, letterSpacing: 1 }}>
                  {status.toUpperCase()}
                </div>
              </div>
            ))}
            <div style={{ marginTop: 18, color: C.muted, fontFamily: mono, fontSize: 12 }}>
              highest-reputation eligible worker selected · ties broken by recency
            </div>
          </Panel>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 7) SETTLEMENT  (7s = 210 frames)  — verification and settlement
// ──────────────────────────────────────────────────────────────
const Settlement: React.FC = () => {
  const f = useCurrentFrame();
  const p = interpolate(f, [16, 55], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink }}>
      <Grid />
      <Header section="06 // WHY IT MATTERS" />
      <div
        style={{
          position: "absolute",
          top: 220,
          left: 130,
          right: 130,
          textAlign: "center",
          ...fade(f),
        }}
      >
        <Label>Trust, then transfer</Label>
        <h2 style={{ fontFamily: display, fontSize: 66, margin: "22px 0 48px" }}>
          Prove the work<span style={{ color: C.mint }}>.</span> Then pay.
        </h2>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "stretch",
            gap: 22,
          }}
        >
          <Panel style={{ width: 400, textAlign: "left" }}>
            <Dot />
            <div style={{ fontFamily: display, fontSize: 26, marginTop: 18 }}>
              Deliverable received
            </div>
            <div style={{ color: C.muted, fontFamily: mono, marginTop: 12, fontSize: 14 }}>
              risk_report.json · verifier.verify() → PASS
            </div>
          </Panel>
          <div style={{ alignSelf: "center", color: C.mint, fontSize: 36 }}>→</div>
          <Panel
            style={{
              width: 400,
              textAlign: "left",
              borderColor: C.mint,
              transform: `scale(${0.94 + p * 0.06})`,
            }}
          >
            <Dot color={C.gold} />
            <div style={{ fontFamily: display, fontSize: 26, marginTop: 18 }}>
              Verified · settlement ready
            </div>
            <div style={{ color: C.gold, fontFamily: mono, marginTop: 12, fontSize: 14 }}>
              Base Sepolia · settlement ready
            </div>
          </Panel>
        </div>

        {/* concrete references */}
        <Panel
          style={{
            marginTop: 40,
            width: 1220,
            marginInline: "auto",
            textAlign: "left",
            opacity: p,
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", rowGap: 12, columnGap: 24, fontFamily: mono, fontSize: 15 }}>
            <div style={{ color: C.muted }}>ACP job</div>
            <div style={{ color: C.muted }}>delegation optional · configure VIRTUALS_* to activate</div>
            <div style={{ color: C.muted }}>Base validation</div>
            <div style={{ color: C.bright }}>Base Sepolia · payload + gas validated on real chain</div>
            <div style={{ color: C.muted }}>Verifier</div>
            <div style={{ color: C.bright }}>BasicVerifier · schema + payload signature · PASS</div>
            <div style={{ color: C.muted }}>Receipt</div>
            <div style={{ color: C.bright }}>REFERENCE tier · immutable, keyed by job_id, retrievable via GET /api/receipts/&lt;id&gt;</div>
          </div>
        </Panel>
        <div
          style={{
            color: C.muted,
            fontFamily: mono,
            marginTop: 26,
            fontSize: 14,
            letterSpacing: 1,
          }}
        >
          Verification is the gate. Every payment writes a chain, a reference, and a receipt any client can audit.
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// 8) OUTRO  (5s = 150 frames)
// ──────────────────────────────────────────────────────────────
const Outro: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        color: C.ink,
        justifyContent: "center",
        alignItems: "center",
        textAlign: "center",
      }}
    >
      <Grid />
      <div style={{ ...fade(f), zIndex: 1 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 24 }}>
          <Logo size={92} />
        </div>
        <h2 style={{ fontFamily: display, fontSize: 68, margin: 0 }}>
           Autonomous systems need more than capability.
           <br />
           <span style={{ color: C.mint }}>They need memory.</span>
        </h2>
        <div
          style={{
            marginTop: 26,
            color: C.muted,
            fontFamily: mono,
            fontSize: 16,
            lineHeight: 1.65,
            maxWidth: 900,
            marginInline: "auto",
          }}
        >
          Trust is not a claim. It is a record.
        </div>
        <div
          style={{
            color: C.muted,
            fontFamily: mono,
            marginTop: 30,
            fontSize: 15,
            letterSpacing: 3,
          }}
        >
          PRAETORV1.UP.RAILWAY.APP
        </div>
        <div
          style={{
            marginTop: 40,
            color: C.gold,
            fontFamily: mono,
            fontSize: 12,
            letterSpacing: 2,
          }}
        >
           PRAETOR · SIBYL · VERIFIED OUTCOMES
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ──────────────────────────────────────────────────────────────
// Composition (30 fps)
//   Intro       90   ( 3.0s)
//   Problem    450   (15.0s)
//   Thesis     210   ( 7.0s)
//   Flow       300   (10.0s)
//   Memory     270   ( 9.0s)
//   Dashboard  540   (18.0s)
//   Settlement 210   ( 7.0s)
//   Outro     150   ( 5.0s)
//   TOTAL     2220   (74.0s)
// ──────────────────────────────────────────────────────────────
export const PraetorDemo: React.FC = () => (
  <AbsoluteFill style={{ background: C.bg }}>
    <Sequence from={0}    durationInFrames={90}>  <Intro /></Sequence>
    <Sequence from={90}   durationInFrames={450}> <Problem /></Sequence>
    <Sequence from={540}  durationInFrames={210}> <PraetorThesis /></Sequence>
    <Sequence from={750}  durationInFrames={300}> <Flow /></Sequence>
    <Sequence from={1050} durationInFrames={270}> <Memory /></Sequence>
    <Sequence from={1320} durationInFrames={540}> <Dashboard /></Sequence>
    <Sequence from={1860} durationInFrames={210}> <Settlement /></Sequence>
    <Sequence from={2070} durationInFrames={150}> <Outro /></Sequence>
  </AbsoluteFill>
);
