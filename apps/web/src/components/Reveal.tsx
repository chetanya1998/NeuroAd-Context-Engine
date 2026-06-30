"use client";

import { clsx } from "clsx";
import { useInView } from "@/lib/useInView";

/**
 * Scroll-triggered reveal wrapper.
 * Children fade-in and slide-up when they enter the viewport.
 */
export function Reveal({
  children,
  delay = 0,
  className
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const { ref, inView } = useInView();

  return (
    <div
      ref={ref}
      className={clsx("reveal-hidden", inView && "reveal-visible", className)}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}
