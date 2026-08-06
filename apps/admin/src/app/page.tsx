"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useMemo, useState } from "react";
import { LogOut } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_ADMIN_API_BASE ?? "http://localhost:8000";
type Json = Record<string, any>;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/internal/admin/v1${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? "Internal dashboard request failed.");
  }
  return response.json();
}

function MetricCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return <section className="metric"><span>{label}</span><strong>{value}</strong>{hint ? <small>{hint}</small> : null}</section>;
}

function BarList({ title, data, valueKey = "count" }: { title: string; data: Json[]; valueKey?: string }) {
  const maximum = Math.max(1, ...data.map((item) => Number(item[valueKey] ?? 0)));
  return <section className="panel chart"><div className="panel-head"><h3>{title}</h3></div>{data.length ? <div className="bars">{data.map((item, index) => {
    const value = Number(item[valueKey] ?? 0);
    const label = item.day ?? item.route ?? item.reason ?? item.status ?? item.event_name ?? "Unknown";
    return <div className="bar-row" key={`${label}-${index}`}><span title={label}>{label}</span><div className="bar-track"><i style={{ width: `${Math.max(3, value / maximum * 100)}%` }} /></div><b>{value}</b></div>;
  })}</div> : <Empty text="No recorded data yet." />}</section>;
}

function Empty({ text }: { text: string }) { return <p className="empty">{text}</p>; }

export default function AdminPage() {
  const [user, setUser] = useState<Json | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<Record<string, Json>>({});
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const paths = ["/overview", "/system-health", "/product-analytics", "/datasets/assets", "/taxonomies", "/label-tasks", "/scoring-configs", "/releases", "/audit-events"];
    const values = await Promise.all(paths.map((path) => request<Json>(path)));
    setData(Object.fromEntries(paths.map((path, index) => [path, values[index]])));
  }, []);

  useEffect(() => {
    request<Json>("/auth/me").then((result) => { setUser(result.user); return load(); }).catch(() => setUser(null));
  }, [load]);

  async function signIn(event: React.FormEvent) {
    event.preventDefault(); setLoading(true); setError("");
    try { const result = await request<Json>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }); setUser(result.user); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to sign in."); }
    finally { setLoading(false); }
  }

  async function signOut() { await request("/auth/logout", { method: "POST" }); setUser(null); setData({}); }
  async function refresh() { setLoading(true); try { await load(); setNotice("Dashboard refreshed."); } catch (reason) { setError(reason instanceof Error ? reason.message : "Refresh failed."); } finally { setLoading(false); } }

  if (!user) return <main className="login-shell"><div className="login-mark">N</div><form className="login-card" onSubmit={signIn}><p className="eyebrow">PRIVATE CONTROL PLANE</p><h1>NeuroAd Internal ML</h1><p>Authorized staff only. This workspace is not linked from the customer product.</p><label>Email<input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required /></label><label>Password<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label>{error ? <p className="error">{error}</p> : null}<button disabled={loading}>{loading ? "Signing in…" : "Sign in"}</button></form></main>;

  return <main className="app-shell"><section className="content"><header className="topbar"><div className="topbar-brand"><span className="brand-mark">N</span><div><p className="eyebrow">PRIVATE CONTROL PLANE</p><h1>NeuroAd Internal ML</h1></div></div><div className="topbar-actions"><span className="identity-chip"><i />{user.email}</span><button className="quiet" onClick={refresh} disabled={loading}>Refresh</button><button className="sign-out" onClick={signOut}><LogOut size={14} /> Sign out</button></div></header>{error ? <p className="error floating">{error}</p> : null}{notice ? <p className="notice">{notice}</p> : null}<DashboardContent data={data} user={user} reload={load} setNotice={setNotice} setError={setError} /></section></main>;
}

function Section({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return <section className="dashboard-section"><div className="section-heading"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>{children}</section>;
}

function DashboardContent({ data, user, reload, setNotice, setError }: { data: Record<string, Json>; user: Json; reload: () => Promise<void>; setNotice: (value: string) => void; setError: (value: string) => void }) {
  const overview = data["/overview"] ?? {}; const health = data["/system-health"] ?? {}; const analytics = data["/product-analytics"] ?? {};
  return <>
    <Section eyebrow="01 / LIVE OVERVIEW" title="Command center"><div className="grid four"><MetricCard label="Completed videos" value={overview.videos?.completed ?? 0} /><MetricCard label="Failed videos" value={overview.videos?.failed ?? 0} /><MetricCard label="Visitors (24h)" value={overview.unique_visitors_24h ?? 0} hint="Privacy-filtered sessions" /><MetricCard label="Active scoring config" value={overview.active_config ? `v${overview.active_config.version}` : "—"} /></div><div className="grid two"><BarList title="Video evaluation state" data={Object.entries(overview.videos ?? {}).map(([status, count]) => ({ status, count }))} /><section className="panel release-card"><h3>Live build</h3><strong>{overview.build?.git_sha ?? "development"}</strong><dl><dt>Branch</dt><dd>{overview.build?.git_branch ?? "local"}</dd><dt>Release</dt><dd>{overview.build?.release_id ?? "local"}</dd><dt>Scoring manifest</dt><dd>{overview.build?.scoring_manifest_version ?? "attention-proxy-v1"}</dd></dl></section></div></Section>
    <Section eyebrow="02 / OPERATIONS" title="System health"><div className="grid four"><MetricCard label="Queued jobs" value={health.queue?.queued ?? 0} /><MetricCard label="Processing jobs" value={health.queue?.processing ?? 0} /><MetricCard label="API routes observed" value={health.latency?.length ?? 0} /><MetricCard label="Dependency checks" value={Object.keys(health.dependencies ?? {}).length} /></div><div className="grid two"><BarList title="API status codes over seven days" data={health.request_statuses ?? []} /><BarList title="Endpoint average latency (ms)" data={(health.latency ?? []).map((item: Json) => ({ ...item, count: Math.round(item.avg_ms ?? 0) }))} /></div><div className="grid two"><BarList title="Video failure reasons" data={health.failure_reasons ?? []} /><DependencyMatrix dependencies={health.dependencies ?? {}} /></div></Section>
    <Section eyebrow="03 / PRODUCT" title="Product analytics"><div className="grid four"><MetricCard label="Videos uploaded" value={analytics.funnel?.uploaded ?? 0} /><MetricCard label="Analysis requested" value={analytics.funnel?.analysis_requested ?? 0} /><MetricCard label="Completed" value={analytics.funnel?.completed ?? 0} /><MetricCard label="Reports generated" value={analytics.funnel?.reports ?? 0} /></div><div className="grid two"><BarList title="Feature adoption and activity" data={analytics.events ?? []} /><BarList title="A/B comparison state" data={analytics.comparison_status ?? []} /></div><section className="panel"><h3>Measurement boundary</h3><p>{analytics.metric_label ?? "Events are privacy-filtered before aggregation."}</p></section></Section>
    <Section eyebrow="04 / TRAINING DATA" title="Datasets and taxonomy"><DatasetView assets={data["/datasets/assets"]?.assets ?? []} taxonomies={data["/taxonomies"]?.taxonomies ?? []} /></Section>
    <Section eyebrow="05 / HUMAN REVIEW" title="Labeling operations"><LabelView tasks={data["/label-tasks"]?.tasks ?? []} /></Section>
    <Section eyebrow="06 / CONFIGURATION" title="Algorithm studio"><StudioView configs={data["/scoring-configs"]?.configs ?? []} user={user} reload={reload} setNotice={setNotice} setError={setError} /></Section>
    <Section eyebrow="07 / DELIVERY" title="Release governance"><ReleaseView releases={data["/releases"] ?? {}} user={user} reload={reload} setNotice={setNotice} setError={setError} /></Section>
    <Section eyebrow="08 / TRACEABILITY" title="Audit history"><AuditView events={data["/audit-events"]?.events ?? []} /></Section>
  </>;
}

function DependencyMatrix({ dependencies }: { dependencies: Json }) { return <section className="panel"><div className="panel-head"><h3>Dependency health</h3><span>Runtime probe</span></div><div className="dependency-grid">{Object.entries(dependencies).map(([name, status]) => <div key={name}><i className={status && typeof status === "object" && (status as Json).available === false ? "bad" : "good"} /><span>{name}</span><small>{status && typeof status === "object" && ((status as Json).available === false || (status as Json).configured === false) ? "needs review" : "ready"}</small></div>)}</div></section>; }

function DatasetView({ assets, taxonomies }: { assets: Json[]; taxonomies: Json[] }) { const consented = assets.filter((asset) => asset.consent_status === "opted_in" && !asset.withdrawn_at); return <><div className="grid four"><MetricCard label="Assets indexed" value={assets.length} /><MetricCard label="Training-consented" value={consented.length} /><MetricCard label="Available taxonomies" value={taxonomies.length} /><MetricCard label="Eligible rate" value={`${assets.length ? Math.round(consented.length / assets.length * 100) : 0}%`} /></div><div className="grid two"><BarList title="Consent coverage" data={[{ status: "eligible", count: consented.length }, { status: "excluded", count: assets.length - consented.length }]} /><section className="panel"><h3>Taxonomy versions</h3>{taxonomies.map((taxonomy) => <div className="list-row" key={taxonomy.id}><div><b>{taxonomy.name}</b><small>Version {taxonomy.version} · {taxonomy.status}</small></div><span>{taxonomy.schema?.fields?.length ?? 0} fields</span></div>)}</section></div><section className="panel table-panel"><h3>Training-data asset inventory</h3><table><thead><tr><th>Asset</th><th>Status</th><th>Consent</th><th>Policy</th><th>Recorded</th></tr></thead><tbody>{assets.slice(0, 20).map((asset) => <tr key={asset.id}><td>{asset.title}</td><td>{asset.status}</td><td><span className={asset.consent_status === "opted_in" ? "tag ok" : "tag"}>{asset.consent_status ?? "not recorded"}</span></td><td>{asset.policy_version ?? "—"}</td><td>{asset.recorded_at ?? "—"}</td></tr>)}</tbody></table>{assets.length === 0 ? <Empty text="No customer media has been indexed yet." /> : null}</section></>;
}

function LabelView({ tasks }: { tasks: Json[] }) { const statusCounts = useMemo(() => Object.entries(tasks.reduce((acc: Json, task) => ({ ...acc, [task.status]: (acc[task.status] ?? 0) + 1 }), {})), [tasks]); return <><div className="grid two"><BarList title="Labeling task queue" data={statusCounts.map(([status, count]) => ({ status, count }))} /><section className="panel"><h3>Quality controls</h3><ul className="checks"><li>Only consented media may enter a task.</li><li>Annotations retain reviewer and taxonomy version.</li><li>Reviewers cannot approve their own work.</li><li>Submitted labels remain immutable audit records.</li></ul></section></div><section className="panel table-panel"><h3>Segment review queue</h3><table><thead><tr><th>Video</th><th>Segment</th><th>Status</th><th>Review</th><th>Confidence</th></tr></thead><tbody>{tasks.slice(0, 25).map((task) => <tr key={task.id}><td>{task.title}</td><td>{task.segment_id ?? "Video-level"}</td><td>{task.status}</td><td>{task.review_status ?? "Not submitted"}</td><td>{task.confidence ?? "—"}</td></tr>)}</tbody></table>{tasks.length === 0 ? <Empty text="Create a task from a consented dataset asset through the protected API." /> : null}</section></>;
}

function StudioView({ configs, user, reload, setNotice, setError }: { configs: Json[]; user: Json; reload: () => Promise<void>; setNotice: (value: string) => void; setError: (value: string) => void }) {
  const [draft, setDraft] = useState<Json | null>(null);
  const active = configs.find((item) => item.status === "active") ?? configs[0]; const config = draft ?? active?.config;
  if (!config) return <Empty text="No baseline scoring configuration is available." />;
  const updateWeight = (key: string, value: string) => setDraft({ ...config, weights: { ...config.weights, [key]: Number(value) } });
  const total = Object.values(config.weights).reduce((sum: number, value) => sum + Number(value), 0);
  async function createCandidate() { try { const created = await request<Json>("/scoring-configs", { method: "POST", body: JSON.stringify({ config, rationale: "Internal experiment created in Algorithm Studio." }) }); setNotice(`Draft v${created.version} created. Run an evaluation before review.`); setDraft(null); await reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create candidate."); } }
  return <><div className="grid two"><section className="panel studio"><div className="panel-head"><div><h3>Attention weight canvas</h3><span>Candidate values must sum to 1.0</span></div><b className={Math.abs(total - 1) < 0.0001 ? "sum ok" : "sum"}>{total.toFixed(2)}</b></div>{Object.entries(config.weights).map(([key, value]) => <label className="weight" key={key}><span>{key.replaceAll("_", " ")}</span><input type="range" min="0" max="0.4" step="0.01" value={Number(value)} onChange={(event) => updateWeight(key, event.target.value)} /><input type="number" min="0" max="1" step="0.01" value={Number(value)} onChange={(event) => updateWeight(key, event.target.value)} /></label>)}<button disabled={Math.abs(total - 1) >= 0.0001 || !["platform_admin", "ml_operator"].includes(user.role)} onClick={createCandidate}>Save immutable candidate</button></section><section className="panel"><h3>Versioned safety boundary</h3><p>Weights, penalties, thresholds, and approved conditional rules are versioned. Raw Python, shell commands, model-server parameters, and secrets cannot be entered from this studio.</p><h4>Current penalties</h4>{Object.entries(config.penalties ?? {}).map(([key, value]) => <div className="list-row" key={key}><span>{key}</span><b>{String(value)}</b></div>)}<h4>Current thresholds</h4>{Object.entries(config.thresholds ?? {}).map(([key, value]) => <div className="list-row" key={key}><span>{key.replaceAll("_", " ")}</span><b>{String(value)}</b></div>)}</section></div><section className="panel table-panel"><h3>Configuration history</h3><table><thead><tr><th>Version</th><th>Status</th><th>Author</th><th>Rationale</th><th>Created</th></tr></thead><tbody>{configs.map((item) => <tr key={item.id}><td>v{item.version}</td><td><span className={item.status === "active" ? "tag ok" : "tag"}>{item.status}</span></td><td>{item.created_by}</td><td>{item.rationale}</td><td>{item.created_at}</td></tr>)}</tbody></table></section></>;
}

function ReleaseView({ releases, user, reload, setNotice, setError }: { releases: Json; user: Json; reload: () => Promise<void>; setNotice: (value: string) => void; setError: (value: string) => void }) { const live = releases.live ?? {}; async function rollback(id: string) { try { await request(`/releases/${id}/rollback`, { method: "POST" }); setNotice("Rollback has been recorded for GitHub App delivery."); await reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Rollback failed."); } } return <><section className="live-release"><p className="eyebrow">CURRENT DEPLOYED MAIN VERSION</p><strong>{live.build?.git_sha ?? "development"}</strong><div><span>{live.build?.git_branch ?? "local"}</span><span>{live.build?.build_time ?? "local build"}</span><span>Scoring v{live.active_config?.version ?? "—"}</span></div></section><section className="panel table-panel"><h3>Release and rollback history</h3><table><thead><tr><th>Config</th><th>Status</th><th>Branch</th><th>Commit</th><th>Created</th><th /></tr></thead><tbody>{(releases.releases ?? []).map((release: Json) => <tr key={release.id}><td>v{release.config_version}</td><td><span className="tag">{release.status}</span></td><td>{release.branch}</td><td>{release.commit_sha}</td><td>{release.created_at}</td><td>{user.role === "platform_admin" ? <button className="danger-link" onClick={() => rollback(release.id)}>Rollback</button> : null}</td></tr>)}</tbody></table>{!(releases.releases ?? []).length ? <Empty text="Approved scoring candidates appear here when prepared for GitHub release." /> : null}</section></>;
}

function AuditView({ events }: { events: Json[] }) { return <section className="panel table-panel"><h3>Immutable internal activity log</h3><table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{event.created_at}</td><td>{event.actor_email ?? "System"}</td><td>{event.action}</td><td>{event.target_type} {event.target_id ?? ""}</td></tr>)}</tbody></table>{events.length === 0 ? <Empty text="Internal access and control-plane activity will appear here." /> : null}</section>; }
