"use client";

import posthog from "posthog-js";
import type { AnalyticsEvent, AnalyticsEventMap } from "./analytics-events";

let initialized = false;
const FALLBACK_VISITOR_KEY = "neuroad_telemetry_visitor";
const FALLBACK_SESSION_KEY = "neuroad_telemetry_session";

function apiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

function privacyTelemetryAllowed() {
  return typeof window === "undefined" || window.navigator.doNotTrack !== "1";
}

function createAnonymousId() {
  const browserCrypto = globalThis.crypto;
  if (typeof browserCrypto?.randomUUID === "function") return browserCrypto.randomUUID();

  if (typeof browserCrypto?.getRandomValues === "function") {
    const bytes = browserCrypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  return `anon-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function anonymousId(key: string, storage: Storage) {
  try {
    const existing = storage.getItem(key);
    if (existing) return existing;
    const value = createAnonymousId();
    storage.setItem(key, value);
    return value;
  } catch {
    return createAnonymousId();
  }
}

function analyticsEnabled() {
  const value = process.env.NEXT_PUBLIC_POSTHOG_ENABLED?.toLowerCase();
  return Boolean(process.env.NEXT_PUBLIC_POSTHOG_TOKEN) && ["1", "true", "yes", "on"].includes(value ?? "");
}

function apiHostname() {
  try {
    return new URL(apiBase()).hostname;
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
  const base = apiBase();
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
