"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { BRAND, COPYRIGHT_NOTICE } from "@/lib/brand";

// ── Eclipse globe (backlit sphere, ORCA-style) ───────────────────────────────

function Globe() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;

    const resize = () => {
      const dpr = devicePixelRatio;
      canvas.width = canvas.offsetWidth * dpr;
      canvas.height = canvas.offsetHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const W = () => canvas.offsetWidth;
    // next/font hashes family names, so read the DM Mono stack from its CSS variable once.
    const monoFamily =
      getComputedStyle(document.documentElement).getPropertyValue("--font-dm-mono").trim() ||
      "monospace";
    const H = () => canvas.offsetHeight;

    // Light direction: backlit from upper-right, behind the globe (negative z)
    // → thin bright crescent along the upper-right limb (eclipse look).
    const L = (() => {
      const v = [0.32, 0.42, -0.85];
      const m = Math.hypot(v[0], v[1], v[2]);
      return [v[0] / m, v[1] / m, v[2] / m];
    })();

    // Set initial angle so Los Angeles (lng -118.24) faces front at startup.
    // theta = (lng + 180 + angle) * π/180; want sin(theta) ≈ 1 → theta ≈ π/2 → angle ≈ 90 - 61.76 = offset below.
    let angle = 28.24; // shifts Los Angeles to ~90° theta so uz is maximised at t=0

    const cities: [number, number, string][] = [
      [34.05, -118.24, "LOS ANGELES"],
      [47.61, -122.33, "SEATTLE"],
      [39.74, -104.99, "DENVER"],
      [30.27, -97.74, "AUSTIN"],
    ];

    // Tip the north pole toward the viewer so the US cities sit near mid-globe, as on the screen.
    const TILT = 0.6;
    const cosT = Math.cos(TILT);
    const sinT = Math.sin(TILT);
    const tilt = (y: number, z: number) => [y * cosT - z * sinT, y * sinT + z * cosT] as const;

    function project(lat: number, lng: number, cx: number, cy: number, r: number) {
      const phi = (90 - lat) * (Math.PI / 180);
      const theta = (lng + 180 + angle) * (Math.PI / 180);
      // Negated so east draws to the right of west (otherwise the globe is mirrored).
      const ux = -Math.sin(phi) * Math.cos(theta);
      const [uy, uz] = tilt(Math.cos(phi), Math.sin(phi) * Math.sin(theta));
      return { ux, uy, uz, sx: cx + ux * r, sy: cy - uy * r };
    }

    function drawArc(
      lat1: number,
      lng1: number,
      lat2: number,
      lng2: number,
      cx: number,
      cy: number,
      r: number,
      opacity: number,
    ) {
      const steps = 60;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i <= steps; i++) {
        const t2 = i / steps;
        // Spherical linear interpolation
        const phi1 = (90 - lat1) * (Math.PI / 180);
        const theta1 = (lng1 + 180 + angle) * (Math.PI / 180);
        const phi2 = (90 - lat2) * (Math.PI / 180);
        const theta2 = (lng2 + 180 + angle) * (Math.PI / 180);
        const ax = -Math.sin(phi1) * Math.cos(theta1);
        const ay = Math.cos(phi1);
        const az = Math.sin(phi1) * Math.sin(theta1);
        const bx = -Math.sin(phi2) * Math.cos(theta2);
        const by = Math.cos(phi2);
        const bz = Math.sin(phi2) * Math.sin(theta2);
        // Linear interp then normalize (approximate great circle)
        const ix = ax + (bx - ax) * t2;
        const iy = ay + (by - ay) * t2;
        const iz = az + (bz - az) * t2;
        const im = Math.hypot(ix, iy, iz);
        const nx = ix / im;
        const [ny, nz] = tilt(iy / im, iz / im);
        if (nz < 0) {
          started = false;
          continue;
        } // behind the globe
        const px = cx + nx * r;
        const py = cy - ny * r;
        if (!started) {
          ctx.moveTo(px, py);
          started = true;
        } else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = `rgba(255,255,255,${opacity})`;
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }

    function draw() {
      ctx.clearRect(0, 0, W(), H());

      const wide = W() > 900;
      const cx = wide ? W() * 0.775 : W() * 0.5;
      const cy = wide ? H() * 0.5 : H() * 0.34;
      const r = wide ? Math.min(H() * 0.42, W() * 0.3) : Math.min(W(), H()) * 0.36;

      angle += 0.03; // slower, smoother rotation

      // ── Sphere body: solid, with a hairline rim ──
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = "#14171a";
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.12)";
      ctx.lineWidth = 1;
      ctx.stroke();

      // Clip all subsequent drawing to the sphere.
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.clip();

      // ── Surface dot grid ──
      for (let lat = -85; lat <= 85; lat += 6) {
        for (let lng = -180; lng <= 180; lng += 6) {
          const { ux, uy, uz, sx, sy } = project(lat, lng, cx, cy, r);
          if (uz < -0.42) continue;
          const illum = Math.max(0, ux * L[0] + uy * L[1] + uz * L[2]);
          const k = Math.pow(illum, 1.5);
          const front = Math.min(1, (uz + 0.42) / 1.42);
          const opacity = 0.06 + front * 0.28;
          const size = 0.6 + front * 0.7 + k * 1.1;
          ctx.beginPath();
          ctx.arc(sx, sy, size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${Math.min(1, opacity)})`;
          ctx.fill();
        }
      }

      // ── Great-circle arcs from Los Angeles to other cities ──
      const originCity = cities[0];
      cities.slice(1).forEach(([lat, lng]) => {
        const p = project(lat, lng, cx, cy, r);
        if (p.uz > -0.1) {
          drawArc(originCity[0], originCity[1], lat, lng, cx, cy, r, 0.18);
        }
      });

      ctx.restore(); // end sphere clip

      // ── City pins (front-facing only) ──
      cities.forEach(([lat, lng, label], i) => {
        const { uz, sx, sy } = project(lat, lng, cx, cy, r);
        if (uz < 0.05) return;
        const isPrimary = i === 0;
        const fade = Math.min(1, (uz - 0.05) / 0.25);

        // Square markers: Los Angeles gets a 6px square inside a 22px outline.
        const size = isPrimary ? 6 : 4;
        ctx.fillStyle = `rgba(255,255,255,${fade})`;
        ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
        if (isPrimary) {
          ctx.strokeStyle = `rgba(255,255,255,${fade * 0.6})`;
          ctx.lineWidth = 1;
          ctx.strokeRect(sx - 11, sy - 11, 22, 22);
        }

        // Label
        if (isPrimary || uz > 0.25) {
          ctx.font = `${isPrimary ? 500 : 400} 9px ${monoFamily}`;
          ctx.fillStyle = `rgba(255,255,255,${fade * 0.7})`;
          ctx.letterSpacing = "0.05em";
          ctx.fillText(label, sx + (isPrimary ? 14 : 8), sy - (isPrimary ? 10 : 6));
        }
      });

      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="h-full w-full block" />;
}

// Floating hazard alert cards anchored over the globe.
function AlertCard({
  title,
  place,
  className,
  delay,
}: {
  title: string;
  place: string;
  className: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay, ease: "easeOut" }}
      className={`absolute z-[5] w-60 ${className}`}
    >
      <div className="flex flex-col gap-[10px] bg-[rgb(29_31_34/0.88)] px-4 py-[14px]">
        <span className="caps text-[11px] text-soft">{title}</span>
        <span className="text-[20px] leading-[24px] text-fg">{place}</span>
        <div className="h-[2px] w-full overflow-hidden bg-[#2e3236]">
          <motion.div
            initial={{ width: "0%" }}
            animate={{ width: "78%" }}
            transition={{ duration: 1.2, delay: delay + 0.3 }}
            className="h-full bg-white"
          />
        </div>
      </div>
    </motion.div>
  );
}

// ── Shared primitives ────────────────────────────────────────────────────────

/** A caps label. With a marker it becomes the content sections' full-width ruled row. */
function SectionLabel({
  children,
  center,
  marker,
}: {
  children: React.ReactNode;
  center?: boolean;
  marker?: string;
}) {
  if (marker) {
    return (
      <div className="caps mb-20 flex justify-between border-t border-rule-light pt-[10px] text-[12px] text-dim">
        <span>{children}</span>
        <span>{marker}</span>
      </div>
    );
  }
  return (
    <div className={`caps mb-5 text-[12px] text-soft ${center ? "text-center" : ""}`}>
      {children}
    </div>
  );
}

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-[44px] leading-[48px] tracking-[-0.035em] text-ink tabular-nums md:text-[60px] md:leading-[60px]">
        {value}
      </div>
      <div className="mt-3 text-[15px] leading-[22px] text-faint">{label}</div>
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="flex gap-6 border-t border-rule-light py-[18px]">
      <div className="caps w-8 shrink-0 pt-1.5 text-[12px] text-dim">{n}</div>
      <div>
        <div className="mb-1 text-[22px] leading-[28px] tracking-[-0.01em] text-ink">{title}</div>
        <div className="text-[15px] leading-[22px] text-faint">{body}</div>
      </div>
    </div>
  );
}

const H2 =
  "text-4xl font-normal leading-[1.1] tracking-[-0.025em] md:text-[52px] md:leading-[58px]";
const BODY = "text-[17px] leading-[27px] text-faint";

// ── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ container: containerRef });
  const globeOpacity = useTransform(scrollYProgress, [0, 0.15], [1, 0]);
  const globeScale = useTransform(scrollYProgress, [0, 0.15], [1, 0.96]);

  return (
    <div
      ref={containerRef}
      className="h-screen overflow-y-scroll bg-page text-fg"
      style={{ scrollSnapType: "y proximity" }}
    >
      {/* HERO */}
      <section className="relative flex min-h-screen flex-col" style={{ scrollSnapAlign: "start" }}>
        <motion.div
          style={{ opacity: globeOpacity, scale: globeScale }}
          className="absolute inset-0 pointer-events-none"
        >
          <Globe />
          <AlertCard
            title="STRUCTURE FIRE"
            place="Westwood"
            className="right-[25%] top-[26%]"
            delay={0.9}
          />
          <AlertCard
            title="RED FLAG WARNING"
            place="Los Angeles"
            className="right-[2%] top-[71%]"
            delay={1.3}
          />
        </motion.div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-page to-transparent" />

        <div className="relative z-10 flex items-center justify-between px-8 pt-7">
          <span className="text-[19px] font-medium text-fg">{BRAND.name}</span>
          <span className="caps text-[12px] text-quiet">Pre-incident intelligence</span>
        </div>

        <div className="relative z-10 mx-auto flex w-full max-w-[1200px] flex-1 flex-col justify-center px-8 xl:px-0">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <SectionLabel>BUILT FOR FIRST RESPONDERS</SectionLabel>
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.1 }}
            className="max-w-[720px] text-5xl font-normal leading-[1.05] tracking-[-0.03em] md:text-[72px] md:leading-[76px]"
          >
            Know the building <span className="text-dim md:block">before the truck arrives.</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.25 }}
            className="mt-7 max-w-[560px] text-[18px] leading-[28px] text-soft"
          >
            {BRAND.name} turns a phone scan of a building into a fire pre-plan: how fire spreads
            room by room, which exits stay open, how long everyone takes to get out, and a size-up a
            battalion chief can act on.
          </motion.p>
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.4 }}
            className="mt-10 flex items-center gap-6"
          >
            <Link
              href="/dashboard"
              className="inline-flex h-11 items-center gap-3 bg-white px-[22px] text-[15px] text-ink transition-colors hover:bg-rule-light"
            >
              Open Dashboard
              <span aria-hidden>→</span>
            </Link>
            {/* The live response (CREAO agents, texts, calls): served by the API via /live. */}
            <a
              href="/live/view"
              className="inline-flex h-11 items-center gap-3 border border-control px-[22px] text-[15px] text-fg transition-colors hover:border-white"
            >
              Live response
              <span aria-hidden>↗</span>
            </a>
            <button
              onClick={() =>
                containerRef.current?.scrollBy({ top: window.innerHeight, behavior: "smooth" })
              }
              className="caps text-[12px] text-quiet transition-colors hover:text-fg"
            >
              LEARN MORE ↓
            </button>
          </motion.div>
        </div>

        <div className="relative z-10 flex justify-center pb-8">
          <div className="caps text-[11px] text-faint">SCROLL</div>
        </div>
      </section>

      {/* The problem and How it works share one white band, so no seam shows between them. */}
      <div className="bg-white text-ink">
        {/* PROBLEM */}
        <section className="px-8 py-[120px] md:px-16" style={{ scrollSnapAlign: "start" }}>
          <div className="mx-auto w-full max-w-[1200px]">
            <SectionLabel marker="/0.1">THE PROBLEM</SectionLabel>
            <div className="grid items-start gap-16 md:grid-cols-2">
              <div>
                <h2 className={`mb-7 ${H2}`}>Firefighters size up on the curb.</h2>
                {/* Sources: CAL FIRE incident pages for the Palisades and Eaton fires (6,845 + 9,419
                  structures destroyed); Governor's proclamation, Jan 2026 (31 lives lost); LAFD
                  "Our Mission" page (470,274 incidents in 2021); NFPA US Fire Department Profile
                  2020 (29,452 departments); LA County 2023 building footprints layer (3,310,548). */}
                <p className={`mb-6 ${BODY}`}>
                  In January 2025 the Palisades and Eaton fires destroyed{" "}
                  <span className="text-ink">more than 16,000 structures</span> across Los Angeles
                  County and took 31 lives. On every call, crews still walk into buildings they have
                  never been inside, with no plan for how the fire will move or which exits will
                  hold.
                </p>
                <p className={BODY}>
                  The size-up happens on the curb, in the first minutes, from what crews can see
                  from outside. {BRAND.name} does the work before the call: how this building burns,
                  which exits it loses and when, and who is still inside.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-x-10 gap-y-12">
                <StatCard
                  value="16,000+"
                  label="structures destroyed in the January 2025 LA fires"
                />
                <StatCard value="470K+" label="incidents LAFD answered in 2021" />
                <StatCard
                  value="63"
                  label="spaces in the venue model, from the scan and floor plan"
                />
                <StatCard value="14" label="exterior exits, each checked against the fire clock" />
              </div>
            </div>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section className="px-8 pb-[120px] pt-10 md:px-16" style={{ scrollSnapAlign: "start" }}>
          <div className="mx-auto w-full max-w-[1200px]">
            <SectionLabel marker="/0.2">HOW IT WORKS</SectionLabel>
            <div className="grid items-start gap-16 md:grid-cols-2">
              <div>
                <Step
                  n="01"
                  title="Scan the building"
                  body="Capture rooms with a phone LiDAR scan and stitch them into one model. The floor plan fills in the rest of the building, floor by floor."
                />
                <Step
                  n="02"
                  title="The engine runs the fire"
                  body="Pick any room as the fire's start. Fire and smoke spread through the building model room by room, and the engine times when each room becomes untenable and each exit is lost."
                />
                <Step
                  n="03"
                  title="Routes and who is at risk"
                  body="Every occupied room gets a route out that books door and stair capacity, compared with the routes people would pick themselves: who is at risk, how long everyone takes to get out, which ways down each floor has."
                />
                <Step
                  n="04"
                  title="Live response"
                  body="During an incident, CREAO agents run the response: people inside get texts and calls with directions and answers, and a dispatcher console shows it all live."
                />
              </div>
              <div>
                <h2 className={`mb-7 ${H2}`}>
                  Scan once. <span className="text-dim md:block">Pre-plan every call.</span>
                </h2>
                <p className={BODY}>
                  One building model serves both sides: the pre-plan responders read before the
                  call, and the live response that guides people out while it happens.
                </p>
                <Link
                  href="/dashboard"
                  className="mt-8 inline-block text-[17px] text-ink underline underline-offset-4"
                >
                  ↳ Open the dashboard
                </Link>
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* MARKET + USE CASE (-mt-px hides a sub-pixel seam against the white band at fractional scaling) */}
      <section
        className="relative -mt-px bg-paper-2 px-8 py-[120px] text-ink md:px-16"
        style={{ scrollSnapAlign: "start" }}
      >
        <div className="mx-auto w-full max-w-[1200px]">
          <SectionLabel marker="/0.3">MARKET + USE CASE</SectionLabel>
          <div className="mb-14 grid items-start gap-x-10 gap-y-6 md:grid-cols-3">
            <h2 className={`md:col-span-2 ${H2}`}>Every building in every city.</h2>
            <p className="text-[17px] leading-[27px] text-faint">
              Los Angeles is the wedge. The architecture scales to any city, any building type, any
              risk profile.
            </p>
          </div>
          <div className="mb-14 grid gap-x-10 gap-y-12 md:grid-cols-3">
            <StatCard value="29,000+" label="fire departments in the United States" />
            <StatCard value="3.3M" label="buildings mapped in Los Angeles County alone" />
          </div>
          <div className="grid gap-x-10 gap-y-8 md:grid-cols-3">
            <div className="border-t border-[#d9dbde] pt-3">
              <div className="caps mb-3 text-[12px] text-ink">FIRE &amp; RESCUE</div>
              <p className="text-[15px] leading-[22px] text-faint">
                Battalion chiefs get a size-up before the truck leaves the station: where the fire
                goes, which exits are lost and when, ways down per floor, and rooms to check.
              </p>
            </div>
            <div className="border-t border-[#d9dbde] pt-3">
              <div className="caps mb-3 text-[12px] text-ink">EMERGENCY MANAGEMENT</div>
              <p className="text-[15px] leading-[22px] text-faint">
                Pre-plan schools, venues and high-occupancy buildings before fire season. See how a
                fire would move through a specific building and how long it takes to clear.
              </p>
            </div>
            <div className="border-t border-[#d9dbde] pt-3">
              <div className="caps mb-3 text-[12px] text-ink">BEYOND FIRE</div>
              <p className="text-[15px] leading-[22px] text-faint">
                Insurance underwriting, CRE due diligence, urban search &amp; rescue. Fire response
                is the wedge.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section
        className="flex min-h-[60vh] items-center justify-center px-8 text-center"
        style={{ scrollSnapAlign: "start" }}
      >
        <div>
          <SectionLabel center>[ TRY IT ]</SectionLabel>
          <h2 className="mx-auto mb-8 max-w-3xl text-5xl font-normal leading-[1.05] tracking-[-0.03em] md:text-[64px] md:leading-[68px]">
            See it run on a real building.
          </h2>
          <Link
            href="/dashboard"
            className="inline-flex h-12 items-center gap-3 bg-white px-[26px] text-[15px] text-ink transition-colors hover:bg-rule-light"
          >
            Open Dashboard
            <span aria-hidden>→</span>
          </Link>
        </div>
      </section>

      <footer className="caps border-t border-rule px-8 py-8 text-center text-[11px] text-faint">
        {COPYRIGHT_NOTICE}
      </footer>
    </div>
  );
}
