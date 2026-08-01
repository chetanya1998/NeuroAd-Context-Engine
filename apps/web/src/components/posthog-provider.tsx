"use client";

import type { ReactNode } from "react";
import posthog from "posthog-js";

const token = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN;
const host = process.env.NEXT_PUBLIC_POSTHOG_HOST;

if ((!token || !host) && process.env.NODE_ENV !== "production") {
  throw new Error(
    `${!token ? "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN" : "NEXT_PUBLIC_POSTHOG_HOST"} variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once ${!token ? "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN" : "NEXT_PUBLIC_POSTHOG_HOST"} is configured`
  );
}

if (token && host) {
  posthog.init(token, {
    api_host: host,
    capture_exceptions: true,
    debug: process.env.NODE_ENV === "development"
  });
}

export function capturePostHogEvent(event: string, properties?: Record<string, unknown>) {
  if (token && host) {
    posthog.capture(event, properties);
  }
}

export function PostHogProvider({ children }: { children: ReactNode }) {
  return children;
}
