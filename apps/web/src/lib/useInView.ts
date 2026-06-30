"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Lightweight Intersection Observer hook.
 * Returns a ref to attach to the target element and a boolean that flips
 * to `true` once the element enters the viewport (stays true — no re-hide).
 */
export function useInView(options?: IntersectionObserverInit) {
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.unobserve(el);
        }
      },
      { threshold: 0.15, ...options }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [options]);

  return { ref, inView };
}
