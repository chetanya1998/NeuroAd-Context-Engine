"use client";

import { useEffect, type ReactNode } from "react";
import { initAnalytics, recordPageView } from "@/lib/analytics";

export function PostHogProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    initAnalytics();
    recordPageView();
  }, []);

  return children;
}
