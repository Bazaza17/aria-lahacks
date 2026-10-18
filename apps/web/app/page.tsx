"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { BRAND, BRAND_WORDMARK, COPYRIGHT_NOTICE } from "@/lib/brand";

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

    function project(lat: number, lng: number, cx: number, cy: number, r: number) {
      const phi = (90 - lat) * (Math.PI / 180);
      const theta = (lng + 180 + angle) * (Math.PI / 180);
      // Negated so east draws to the right of west (otherwise the globe is mirrored).
      const ux = -Math.sin(phi) * Math.cos(theta);
      const uy = Math.cos(phi);
      const uz = Math.sin(phi) * Math.sin(theta);
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
        const nx = ix / im,
          ny = iy / im,
          nz = iz / im;
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
      ctx.strokeStyle = `rgba(255,107,0,${opacity})`;
      ctx.lineWidth = 0.7;
      ctx.stroke();
    }

    function draw(t: number) {
      ctx.clearRect(0, 0, W(), H());

      const wide = W() > 900;
      const cx = wide ? W() * 0.82 : W() * 0.5;
      const cy = wide ? H() * 0.5 : H() * 0.34;
      const r = wide ? Math.min(H() * 0.62, W() * 0.46) : Math.min(W(), H()) * 0.36;

      angle += 0.03; // slower, smoother rotation

      // ── Atmosphere glow (behind sphere) ──
      const glowX = cx + 0.62 * r;
      const glowY = cy - 0.78 * r;
      const pulse = (Math.sin(t * 0.0012) + 1) / 2;
      const g1 = ctx.createRadialGradient(glowX, glowY, r * 0.1, glowX, glowY, r * 1.5);
      g1.addColorStop(0, `rgba(255,120,20,${0.5 + pulse * 0.12})`);
      g1.addColorStop(0.4, "rgba(255,90,0,0.16)");
      g1.addColorStop(1, "rgba(255,90,0,0)");
      ctx.fillStyle = g1;
      ctx.fillRect(0, 0, W(), H());

      // Thin full rim halo.
      const ring = ctx.createRadialGradient(cx, cy, r * 0.92, cx, cy, r * 1.18);
      ring.addColorStop(0, "rgba(255,107,0,0)");
      ring.addColorStop(0.5, "rgba(255,107,0,0.10)");
      ring.addColorStop(1, "rgba(255,107,0,0)");
      ctx.fillStyle = ring;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 1.18, 0, Math.PI * 2);
      ctx.fill();

      // ── Sphere body ──
      const bodyX = cx + L[0] * r * 0.5;
      const bodyY = cy - L[1] * r * 0.5;
      const body = ctx.createRadialGradient(bodyX, bodyY, r * 0.1, cx, cy, r);
      body.addColorStop(0, "rgba(26,22,20,1)");
      body.addColorStop(0.6, "rgba(12,11,12,1)");
      body.addColorStop(1, "rgba(6,6,8,1)");
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = body;
      ctx.fill();

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
          const rC = Math.round(60 + (255 - 60) * k);
          const gC = Math.round(55 + (110 - 55) * k);
          const bC = Math.round(58 - 58 * k);
          const opacity = 0.08 + front * 0.22 + k * 0.5;
          const size = 0.6 + front * 0.7 + k * 1.1;
          ctx.beginPath();
          ctx.arc(sx, sy, size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${rC},${gC},${bC},${Math.min(1, opacity)})`;
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

        // Pulse ring
        const pp = (Math.sin(t * 0.003 + i * 1.3) + 1) / 2;
        const pulseR = (isPrimary ? 9 : 5) + pp * (isPrimary ? 12 : 6);
        ctx.beginPath();
        ctx.arc(sx, sy, pulseR, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,107,0,${fade * (0.35 - pp * 0.28)})`;
        ctx.lineWidth = isPrimary ? 1.5 : 1;
        ctx.stroke();

        // Second static ring
        ctx.beginPath();
        ctx.arc(sx, sy, isPrimary ? 7 : 4, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(255,107,0,${fade * 0.5})`;
        ctx.lineWidth = 0.8;
        ctx.stroke();

        // Crosshair lines
        const ch = isPrimary ? 10 : 6;
        const gap = isPrimary ? 4 : 2.5;
        ctx.strokeStyle = `rgba(255,107,0,${fade * 0.6})`;
        ctx.lineWidth = 0.8;
        [
          [1, 0],
          [-1, 0],
          [0, 1],
          [0, -1],
        ].forEach(([dx, dy]) => {
          ctx.beginPath();
          ctx.moveTo(sx + dx * gap, sy + dy * gap);
          ctx.lineTo(sx + dx * (gap + ch), sy + dy * (gap + ch));
          ctx.stroke();
        });

        // Solid centre dot
        ctx.beginPath();
        ctx.arc(sx, sy, isPrimary ? 3 : 1.8, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,107,0,${fade})`;
        ctx.fill();

        // Label
        if (isPrimary || uz > 0.25) {
          ctx.font = `${isPrimary ? 600 : 400} ${isPrimary ? 9 : 8}px monospace`;
          ctx.fillStyle = `rgba(255,107,0,${fade * (isPrimary ? 0.9 : 0.55)})`;
          ctx.letterSpacing = "0.15em";
          ctx.fillText(label, sx + (isPrimary ? 14 : 10), sy - (isPrimary ? 10 : 7));
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

// Floating hazard alert cards anchored over the globe (ORCA-style).
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
      initial={{ opacity: 0, y: 12, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.6, delay, ease: "easeOut" }}
      className={`absolute z-[5] w-52 ${className}`}
    >
      <div className="rounded-md border border-[#ff6b00]/25 bg-black/70 p-3 backdrop-blur-sm shadow-[0_8px_30px_-10px_rgba(255,107,0,0.4)]">
        <div className="mb-2 flex items-center gap-2">
          <motion.span
            animate={{ opacity: [1, 0.3, 1] }}
            transition={{ repeat: Infinity, duration: 1.8 }}
            className="h-1.5 w-1.5 rounded-full bg-[#ff6b00]"
          />
          <span className="font-mono text-[10px] tracking-[0.2em] text-[#ff6b00]">{title}</span>
        </div>
        <div className="font-mono text-sm font-medium tracking-[0.15em] text-white/90">{place}</div>
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
          <motion.div
            initial={{ width: "0%" }}
            animate={{ width: "78%" }}
            transition={{ duration: 1.2, delay: delay + 0.3 }}
            className="h-full bg-[#ff6b00]/70"
          />
        </div>
      </div>
    </motion.div>
  );
}

// ── Shared primitives ────────────────────────────────────────────────────────

function SectionLabel({ children, center }: { children: React.ReactNode; center?: boolean }) {
  return (
    <div
      className={`mb-5 flex items-center gap-3 font-mono text-xs tracking-[0.3em] text-[#ff6b00] ${center ? "justify-center" : ""}`}
    >
      <span className="h-px w-6 bg-[#ff6b00]" />
      {children}
      {center && <span className="h-px w-6 bg-[#ff6b00]" />}
    </div>
  );
}

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-sm border border-white/[0.07] bg-white/[0.02] p-6">
      <div className="mb-1 font-mono text-3xl font-semibold text-[#ff6b00]">{value}</div>
      <div className="text-sm leading-relaxed text-white/50">{label}</div>
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="flex gap-5">
      <div className="w-5 shrink-0 pt-0.5 font-mono text-xs text-[#ff6b00]/40">{n}</div>
      <div>
        <div className="mb-1 text-sm font-medium text-white">{title}</div>
        <div className="text-sm leading-relaxed text-white/50">{body}</div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ container: containerRef });
  const globeOpacity = useTransform(scrollYProgress, [0, 0.15], [1, 0]);
  const globeScale = useTransform(scrollYProgress, [0, 0.15], [1, 0.96]);

  return (
    <div
      ref={containerRef}
      className="h-screen overflow-y-scroll bg-black text-white"
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
            place="WESTWOOD"
            className="right-[20%] top-[26%]"
            delay={0.9}
          />
          <AlertCard
            title="RED FLAG WARNING"
            place="LOS ANGELES"
            className="right-[5%] top-[48%]"
            delay={1.3}
          />
        </motion.div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-black to-transparent" />

        <div className="relative z-10 flex items-center justify-between px-8 pt-7">
          <span className="font-mono text-xs tracking-[0.3em] text-white/40">{BRAND_WORDMARK}</span>
          <span className="font-mono text-xs tracking-[0.2em] text-white/25">
            PRE-INCIDENT INTELLIGENCE
          </span>
        </div>

        <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-8 md:px-16">
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
            className="max-w-4xl text-balance text-5xl font-medium leading-[1.05] tracking-tight md:text-7xl"
          >
            Know the building <span className="text-white/40">before the truck arrives.</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.25 }}
            className="mt-7 max-w-xl text-lg leading-relaxed text-white/55"
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
              className="group inline-flex items-center gap-3 rounded-sm bg-[#ff6b00] px-6 py-3 text-sm font-medium tracking-wide text-black transition-colors hover:bg-[#ff7f1f]"
            >
              Open Dashboard
              <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
                →
              </span>
            </Link>
            <button
              onClick={() =>
                containerRef.current?.scrollBy({ top: window.innerHeight, behavior: "smooth" })
              }
              className="font-mono text-xs tracking-[0.2em] text-white/30 transition-colors hover:text-white/60"
            >
              LEARN MORE ↓
            </button>
          </motion.div>
        </div>

        <div className="relative z-10 flex justify-center pb-8">
          <motion.div
            animate={{ y: [0, 6, 0] }}
            transition={{ repeat: Infinity, duration: 2.2, ease: "easeInOut" }}
            className="font-mono text-[10px] tracking-[0.3em] text-white/20"
          >
            SCROLL
          </motion.div>
        </div>
      </section>

      {/* PROBLEM */}
      <section
        className="flex min-h-screen items-center px-8 py-24 md:px-16"
        style={{ scrollSnapAlign: "start" }}
      >
        <div className="mx-auto grid w-full max-w-5xl items-center gap-16 md:grid-cols-2">
          <div>
            <SectionLabel>THE PROBLEM</SectionLabel>
            <h2 className="mb-7 text-4xl font-medium leading-[1.1] tracking-tight md:text-5xl">
              Firefighters size up on the curb.
            </h2>
            {/* Sources: CAL FIRE incident pages for the Palisades and Eaton fires (6,845 + 9,419
                structures destroyed); Governor's proclamation, Jan 2026 (31 lives lost); LAFD
                "Our Mission" page (470,274 incidents in 2021); NFPA US Fire Department Profile
                2020 (29,452 departments); LA County 2023 building footprints layer (3,310,548). */}
            <p className="mb-6 leading-relaxed text-white/50">
              In January 2025 the Palisades and Eaton fires destroyed{" "}
              <span className="text-white/80">more than 16,000 structures</span> across Los Angeles
              County and took 31 lives. On every call, crews still walk into buildings they have
              never been inside, with no plan for how the fire will move or which exits will hold.
            </p>
            <p className="leading-relaxed text-white/50">
              Crews get <span className="text-white/80">60 seconds</span> to size up an unfamiliar
              structure while lives are on the line. That’s the problem {BRAND.name} solves — before
              the tone drops.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <StatCard value="16,000+" label="structures destroyed in the January 2025 LA fires" />
            <StatCard value="470K+" label="incidents LAFD answered in 2021" />
            <StatCard value="60s" label="average on-scene size-up window" />
            <StatCard value="30s" label={`${BRAND.name}'s size-up, ready before dispatch`} />
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section
        className="flex min-h-screen items-center px-8 py-24 md:px-16"
        style={{ scrollSnapAlign: "start" }}
      >
        <div className="mx-auto grid w-full max-w-5xl items-center gap-16 md:grid-cols-2">
          <div className="space-y-8">
            <Step
              n="01"
              title="Scan the building"
              body="Capture a LiDAR scan with a phone. Polycam exports a 3D mesh in minutes."
            />
            <div className="h-px bg-white/[0.06]" />
            <Step
              n="02"
              title="Agent synthesizes the intel"
              body="The scan and floor plan become a building model. Fire and smoke spread through it room by room while agents route every room to every exit and write a structured report."
            />
            <div className="h-px bg-white/[0.06]" />
            <Step
              n="03"
              title="Chief gets the size-up"
              body="Headline risk, immediate actions, and the 3D scan showing how the fire moves, which exits stay open and how long the building takes to clear."
            />
            <div className="h-px bg-white/[0.06]" />
            <Step
              n="04"
              title="Cache it. Always ready."
              body="Reports are stored and replayed instantly. No live API call at dispatch, so it works in the field."
            />
          </div>
          <div>
            <SectionLabel>HOW IT WORKS</SectionLabel>
            <h2 className="mb-7 text-4xl font-medium leading-[1.1] tracking-tight md:text-5xl">
              Scan once. <span className="text-white/40">Pre-plan every call.</span>
            </h2>
            <p className="leading-relaxed text-white/50">
              The same pattern used for AI-driven drone inspection — agent over visual + geospatial
              data — applied to building risk for the people who run toward the fire.
            </p>
            <Link
              href="/dashboard"
              className="group mt-8 inline-flex items-center gap-2 font-mono text-sm tracking-[0.15em] text-[#ff6b00] transition-colors hover:text-[#ff7f1f]"
            >
              OPEN THE DASHBOARD →
            </Link>
          </div>
        </div>
      </section>

      {/* MARKET + USE CASE */}
      <section
        className="flex min-h-screen items-center px-8 py-24 md:px-16"
        style={{ scrollSnapAlign: "start" }}
      >
        <div className="mx-auto w-full max-w-5xl">
          <SectionLabel>MARKET + USE CASE</SectionLabel>
          <h2 className="mb-4 max-w-2xl text-4xl font-medium leading-[1.1] tracking-tight md:text-5xl">
            Every building in every city.
          </h2>
          <p className="mb-14 max-w-xl leading-relaxed text-white/50">
            Los Angeles is the wedge. The architecture scales to any city, any building type, any
            risk profile.
          </p>
          <div className="mb-14 grid gap-6 md:grid-cols-3">
            <StatCard value="29,000+" label="fire departments in the United States" />
            <StatCard value="130M+" label="buildings in the US addressable by this system" />
            <StatCard value="3.3M" label="buildings mapped in Los Angeles County alone" />
          </div>
          <div className="grid gap-8 border-t border-white/[0.06] pt-12 md:grid-cols-3">
            <div>
              <div className="mb-3 font-mono text-xs tracking-[0.25em] text-[#ff6b00]">
                FIRE &amp; RESCUE
              </div>
              <p className="text-sm leading-relaxed text-white/50">
                Battalion chiefs get a structured size-up before the truck leaves the station.
                Immediate actions are pre-generated and dispatchable from the app.
              </p>
            </div>
            <div>
              <div className="mb-3 font-mono text-xs tracking-[0.25em] text-[#ff6b00]">
                EMERGENCY MANAGEMENT
              </div>
              <p className="text-sm leading-relaxed text-white/50">
                Pre-plan schools, venues and high-occupancy buildings before fire season. See how a
                fire would move through a specific building and how long it takes to clear.
              </p>
            </div>
            <div>
              <div className="mb-3 font-mono text-xs tracking-[0.25em] text-[#ff6b00]">
                BEYOND FIRE
              </div>
              <p className="text-sm leading-relaxed text-white/50">
                Insurance underwriting, CRE due diligence, urban search &amp; rescue. {BRAND.name}{" "}
                is a structured-intel agent platform — fire response is the wedge.
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
          <SectionLabel center>TRY IT</SectionLabel>
          <h2 className="mx-auto mb-8 max-w-2xl text-5xl font-medium leading-[1.05] tracking-tight md:text-6xl">
            See it run on a real building.
          </h2>
          <Link
            href="/dashboard"
            className="group inline-flex items-center gap-3 rounded-sm bg-[#ff6b00] px-8 py-4 text-sm font-medium tracking-wide text-black transition-colors hover:bg-[#ff7f1f]"
          >
            Open Dashboard
            <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
              →
            </span>
          </Link>
        </div>
      </section>

      <footer className="border-t border-white/[0.06] px-8 py-8 text-center font-mono text-[11px] tracking-[0.15em] text-white/30">
        {COPYRIGHT_NOTICE}
      </footer>
    </div>
  );
}
