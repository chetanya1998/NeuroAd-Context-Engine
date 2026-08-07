"use client";

import posthog from "posthog-js";
import type { AnalyticsEvent, AnalyticsEventMap } from "./analytics-events";

let initialized = false;
const FALLBACK_VISITOR_KEY = "neuroad_telemetry_visitor";
const FALLBACK_SESSION_KEY = "neuroad_telemetry_session";

function privacyTelemetryAllowed() {
  return typeof window === "undefined" || window.navigator.doNotTrack !== "1";
}

function anonymousId(key: string, storage: Storage) {
  const existing = storage.getItem(key);
  if (existing) return existing;
  const value = crypto.randomUUID();
  storage.setItem(key, value);
  return value;
}

function analyticsEnabled() {
  const value = process.env.NEXT_PUBLIC_POSTHOG_ENABLED?.toLowerCase();
  return Boolean(process.env.NEXT_PUBLIC_POSTHOG_TOKEN) && ["1", "true", "yes", "on"].includes(value ?? "");
}

function apiHostname() {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").hostname;
  } catch {
    return undefined;
  }
}

function redactRequest<T extends { name?: string }>(request: T): T {
  if (request.name) request.name = request.name.split("?")[0];
  return request;
}

export function initAnalytics() {
  if (initialized || typeof window === "undefined" || !analyticsEnabled()) return;
  const token = process.env.NEXT_PUBLIC_POSTHOG_TOKEN;
  if (!token) return;

  const tracingHost = apiHostname();
  posthog.init(token, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
    capture_pageview: "history_change",
    capture_pageleave: true,
    autocapture: false,
    disable_session_recording: true,
    person_profiles: "identified_only",
    persistence: "localStorage",
    respect_dnt: true,
    tracing_headers: tracingHost ? [tracingHost] : [],
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "*",
      maskCapturedNetworkRequestFn: redactRequest
    },
    loaded: (client) => {
      client.register({
        schema_version: 1,
        environment: process.env.NEXT_PUBLIC_APP_ENV ?? process.env.NODE_ENV ?? "production"
      });
    }
  });
  initialized = true;
}

export function capture<E extends AnalyticsEvent>(event: E, properties: AnalyticsEventMap[E]) {
  initAnalytics();
  if (!initialized) return;
  const safeProperties = Object.fromEntries(
    Object.entries(properties).filter(([, value]) => value !== undefined && value !== null)
  );
  posthog.capture(event, safeProperties);
}

export function analyticsHeaders(): Record<string, string> {
  initAnalytics();
  if (!privacyTelemetryAllowed() || typeof window === "undefined") return {};
  const distinctId = initialized ? posthog.get_distinct_id() : anonymousId(FALLBACK_VISITOR_KEY, window.localStorage);
  const sessionId = initialized ? posthog.get_session_id() : anonymousId(FALLBACK_SESSION_KEY, window.sessionStorage);
  return {
    ...(distinctId ? { "X-POSTHOG-DISTINCT-ID": distinctId } : {}),
    ...(sessionId ? { "X-POSTHOG-SESSION-ID": sessionId } : {})
  };
}

export function recordPageView() {
  if (typeof window === "undefined" || !privacyTelemetryAllowed()) return;
  const base = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
  void fetch(`${base}/api/telemetry/pageview`, { method: "POST", headers: analyticsHeaders(), keepalive: true }).catch(() => undefined);
}

export function optOutAnalytics() {
  initAnalytics();
  if (initialized) posthog.opt_out_capturing();
}

export function optInAnalytics() {
  initAnalytics();
  if (initialized) posthog.opt_in_capturing();
}

export function resetAnalytics() {
  if (initialized) posthog.reset();
}
