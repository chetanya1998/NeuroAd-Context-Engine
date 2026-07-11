"use client";

import { useEffect, useRef } from "react";
import {
  animate,
  createDrawable,
  createMotionPath,
  createTimeline,
  stagger
} from "animejs";

const gridCells = Array.from({ length: 143 }, (_, index) => index);
const signalDots = Array.from({ length: 28 }, (_, index) => index);
const timelineBars = [28, 42, 66, 82, 48, 74, 58];

export default function HeroContextAnimation() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.dataset.motion = "reduced";
      return;
    }

    root.dataset.motion = "animated";
    const grid = root.querySelectorAll(".hero-context-grid__cell");
    const capsule = root.querySelector(".hero-context-source");
    const capsuleBits = root.querySelectorAll(".hero-context-source__bit");
    const packets = root.querySelectorAll(".hero-context-packet");
    const modules = root.querySelectorAll(".hero-context-module");
    const paths = root.querySelectorAll(".hero-context-path");
    const output = root.querySelector(".hero-context-output");
    const bars = root.querySelectorAll(".hero-context-output__bar-fill");
    const score = root.querySelector(".hero-context-output__score");
    const movingDot = root.querySelector(".hero-context-carrier");
    const carrierPath = root.querySelector<SVGPathElement>("#hero-context-carrier-path");
    const ambientCells = root.querySelectorAll(".hero-context-grid__cell:nth-child(3n)");

    if (!capsule || !output || !score || !movingDot || !carrierPath) return;

    const drawablePaths = Array.from(paths).map((path) => createDrawable(path));
    const motionPath = createMotionPath(carrierPath);

    const loop = createTimeline({
      loop: true,
      defaults: {
        ease: "inOutSine"
      }
    })
      .add(grid, {
        opacity: [0.03, 0.28],
        scale: [0.35, 1],
        rotate: [0, 90],
        borderRadius: ["18%", "50%"],
        duration: 1200,
        delay: stagger(16, { from: "center", grid: [13, 11] })
      }, 0)
      .add(grid, {
        opacity: 0.1,
        scale: 0.62,
        duration: 700,
        delay: stagger(8, { from: "center", grid: [13, 11] })
      }, 1180)
      .add(capsule, {
        opacity: [0, 0.42],
        scale: [0.7, 1],
        y: [18, 0],
        duration: 900,
        ease: "outExpo"
      }, 1200)
      .add(capsuleBits, {
        opacity: [0, 0.82],
        scale: [0.35, 1],
        x: stagger([-44, 44], { from: "center" }),
        y: stagger([18, -18], { from: "center" }),
        duration: 850,
        delay: stagger(32, { from: "center" })
      }, 1550)
      .add(capsule, {
        opacity: [0.42, 0.18],
        scale: [1, 0.92],
        duration: 650
      }, 2700)
      .add(capsuleBits, {
        opacity: [0.8, 0],
        scale: [1, 0.18],
        x: stagger([-140, 140], { from: "center" }),
        y: stagger([-92, 92], { from: "center" }),
        rotate: stagger([-90, 90], { from: "center" }),
        duration: 760,
        delay: stagger(18, { from: "center" }),
        ease: "inExpo"
      }, 2820)
      .add(packets, {
        opacity: [0, 1],
        scale: [0.54, 1],
        y: [16, 0],
        duration: 760,
        delay: stagger(120, { from: "center" }),
        ease: "outBack"
      }, 3060)
      .add(packets, {
        x: stagger([-14, 14], { from: "center" }),
        y: stagger([8, -8], { from: "center" }),
        duration: 900,
        delay: stagger(70, { from: "center" }),
        alternate: true
      }, 3680)
      .add(modules, {
        opacity: [0, 1],
        scale: [0.72, 1],
        duration: 760,
        delay: stagger(80, { from: "center" }),
        ease: "outCubic"
      }, 4500)
      .add(drawablePaths, {
        draw: ["0 0", "0 1"],
        duration: 1120,
        delay: stagger(90, { from: "center" }),
        ease: "inOutCubic"
      }, 4720)
      .add(movingDot, {
        opacity: [0, 1, 0],
        ...motionPath,
        duration: 1850,
        ease: "inOutCubic"
      }, 4820)
      .add(packets, {
        opacity: [1, 0.38],
        scale: [1, 0.86],
        duration: 540,
        delay: stagger(48, { from: "center" })
      }, 6260)
      .add(modules, {
        borderColor: "rgba(34, 197, 94, 0.42)",
        boxShadow: "0 0 28px rgba(34, 197, 94, 0.18)",
        duration: 780,
        delay: stagger(58, { from: "center" })
      }, 6460)
      .add(output, {
        opacity: [0, 0.46],
        scale: [0.78, 1],
        y: [28, 0],
        duration: 840,
        ease: "outExpo"
      }, 6860)
      .add(bars, {
        scaleX: [0, 1],
        duration: 900,
        delay: stagger(95)
      }, 7240)
      .add(score, {
        scale: [0.82, 1.18, 1],
        color: ["#d4d4d8", "#ffffff", "#86efac"],
        duration: 680,
        ease: "outBack"
      }, 8420)
      .add(output, {
        boxShadow: [
          "0 0 0 rgba(34, 197, 94, 0)",
          "0 0 30px rgba(34, 197, 94, 0.16)",
          "0 0 12px rgba(255, 255, 255, 0.05)"
        ],
        duration: 1200
      }, 8460)
      .add(modules, {
        scale: [1, 1.06, 1],
        duration: 900,
        delay: stagger(58, { from: "center" })
      }, 8640)
      .add([packets, modules, output], {
        opacity: 0,
        scale: 0.72,
        y: stagger([-18, 18], { from: "center" }),
        duration: 820,
        delay: stagger(38, { from: "center" }),
        ease: "inCubic"
      }, 9800)
      .add(drawablePaths, {
        draw: ["0 1", "1 1"],
        duration: 760,
        delay: stagger(40, { from: "center" }),
        ease: "inOutCubic"
      }, 9900)
      .add(capsule, {
        opacity: 0,
        scale: 0.68,
        duration: 520
      }, 10020)
      .add(grid, {
        opacity: [0.1, 0.24, 0.04],
        scale: [0.62, 0.96, 0.4],
        rotate: [90, 0],
        borderRadius: ["50%", "18%"],
        duration: 1500,
        delay: stagger(10, { from: "center", grid: [13, 11] })
      }, 10100);

    const ambient = animate(ambientCells, {
      opacity: [0.05, 0.18],
      duration: 1800,
      alternate: true,
      loop: true,
      delay: stagger(18, { from: "center" }),
      ease: "inOutSine"
    });

    return () => {
      loop.revert();
      ambient.revert();
    };
  }, []);

  return (
    <div ref={rootRef} className="hero-context-animation" aria-hidden="true">
      <div className="hero-context-grid">
        {gridCells.map((cell) => (
          <span key={cell} className="hero-context-grid__cell" />
        ))}
      </div>

      <svg className="hero-context-svg" viewBox="0 0 1000 620" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="hero-context-path-gradient" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="rgba(255,255,255,0)" />
            <stop offset="45%" stopColor="rgba(255,255,255,0.64)" />
            <stop offset="72%" stopColor="rgba(34,197,94,0.68)" />
            <stop offset="100%" stopColor="rgba(245,158,11,0)" />
          </linearGradient>
        </defs>
        <path id="hero-context-carrier-path" d="M 178 310 C 300 206, 390 292, 500 310 S 694 408, 826 310" fill="none" />
        {[
          "M 178 310 C 282 208, 384 238, 500 310",
          "M 272 420 C 374 372, 438 396, 500 310",
          "M 500 458 C 504 398, 504 352, 500 310",
          "M 728 420 C 638 394, 556 378, 500 310",
          "M 822 310 C 706 230, 604 238, 500 310",
          "M 500 310 C 586 256, 654 254, 694 266",
          "M 500 310 C 606 324, 724 326, 826 310"
        ].map((path) => (
          <path
            key={path}
            className="hero-context-path"
            d={path}
            fill="none"
            stroke="url(#hero-context-path-gradient)"
            strokeLinecap="round"
            strokeWidth="1.6"
          />
        ))}
        <circle className="hero-context-carrier" r="5" fill="#fff" />
      </svg>

      <div className="hero-context-source">
        <div className="hero-context-source__screen">
          {signalDots.map((dot) => (
            <span key={dot} className="hero-context-source__bit" />
          ))}
        </div>
        <span className="hero-context-source__label">approved_video.mp4</span>
      </div>

      <div className="hero-context-output">
        <div className="hero-context-output__header">
          <span>00:18-00:24</span>
          <strong className="hero-context-output__score">91</strong>
        </div>
        <div className="hero-context-output__label">Best Ad Slot</div>
        <div className="hero-context-output__bars">
          {timelineBars.map((width, index) => (
            <span key={`${width}-${index}`} className="hero-context-output__bar">
              <span className="hero-context-output__bar-fill" style={{ width: `${width}%` }} />
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
