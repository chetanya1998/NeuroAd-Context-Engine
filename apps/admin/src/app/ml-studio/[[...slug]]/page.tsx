"use client";

import { BarChart3, BrainCircuit, ChevronRight, CircleHelp, Database, FlaskConical, Rocket, Workflow } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AdminRequestError, adminRequest, restoreAdminSession, type AdminUser } from "@/lib/admin-client";

type Item = { label: string; href: string; icon?: React.ComponentType<{ size?: number }> };
type Group = { label: string; items: Item[] };

const groups: Group[] = [
  { label: "ML Studio", items: [{ label: "Overview", href: "/ml-studio/overview", icon: BarChart3 }] },
  { label: "Data", items: [{ label: "Datasets", href: "/ml-studio/data/datasets" }, { label: "Sources", href: "/ml-studio/data/sources" }, { label: "Collection", href: "/ml-studio/data/collection" }, { label: "Ingestion", href: "/ml-studio/data/ingestion" }] },
  { label: "Intelligence", items: [{ label: "Feature Lab", href: "/ml-studio/intelligence/features" }, { label: "Annotation Studio", href: "/ml-studio/intelligence/annotations" }, { label: "Context Explorer", href: "/ml-studio/intelligence/context" }] },
  { label: "Models", items: [{ label: "Experiments", href: "/ml-studio/models/experiments" }, { label: "Training Runs", href: "/ml-studio/models/training" }, { label: "Evaluation", href: "/ml-studio/models/evaluation" }, { label: "Model Registry", href: "/ml-studio/models/registry" }] },
  { label: "Deployment", items: [{ label: "Deployments", href: "/ml-studio/deployments" }, { label: "Monitoring", href: "/ml-studio/monitoring" }] },
  { label: "Infrastructure", items: [{ label: "Workers", href: "/ml-studio/infrastructure/workers" }, { label: "GPU Jobs", href: "/ml-studio/infrastructure/gpu-jobs" }, { label: "Queues", href: "/ml-studio/infrastructure/queues" }, { label: "Storage", href: "/ml-studio/infrastructure/storage" }] },
];

function pageFor(path: string) {
  return groups.flatMap((group) => group.items).find((item) => item.href === path)?.label ?? "ML Studio";
}

export default function MLStudioPage() {
  const params = useParams<{ slug?: string[] }>();
  const path = `/ml-studio/${(params.slug ?? ["overview"]).join("/")}`;
  const title = useMemo(() => pageFor(path), [path]);
  const [user, setUser] = useState<AdminUser | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    restoreAdminSession();
    adminRequest<{ user: AdminUser }>("/auth/me").then(({ user: currentUser }) => setUser(currentUser)).catch((reason) => {
      setError(reason instanceof AdminRequestError && reason.status === 401 ? "Your session has expired. Sign in again from the Admin dashboard." : "ML Studio could not verify your Admin session.");
    });
  }, []);

  if (!user) return <main className="ml-studio-gate"><section className="panel"><p className="eyebrow">PRIVATE CONTROL PLANE</p><h1>ML Studio</h1><p>{error || "Verifying your Admin session…"}</p><Link className="primary-action" href="/">Return to Admin</Link></section></main>;

  return <main className="ml-studio-shell">
    <aside className="ml-studio-sidebar">
      <Link href="/" className="brand"><span>N</span><div><b>NeuroAd</b><small>INTERNAL ML</small></div></Link>
      {groups.map((group) => <section key={group.label}><p>{group.label}</p>{group.items.map((item) => {
        const Icon = item.icon;
        return <Link key={item.href} className={item.href === path ? "active" : ""} href={item.href}>{Icon ? <Icon size={15} /> : <ChevronRight size={14} />}{item.label}</Link>;
      })}</section>)}
      <div className="ml-studio-user"><span>{user.email}</span><small>{user.role.replaceAll("_", " ")}</small></div>
    </aside>
    <section className="ml-studio-content">
      <header className="ml-studio-header"><div><p className="eyebrow">ML STUDIO / PHASE 1</p><h1>{title}</h1><p>Internal research and operations control plane.</p></div><Link className="quiet" href="/">Admin overview</Link></header>
      <section className="ml-studio-placeholder"><div className="ml-studio-icon"><BrainCircuit size={28} /></div><div><h2>Feature under development.</h2><p>This protected workspace is ready for the next sequential ML Studio phase. It intentionally does not show fabricated production statistics.</p></div></section>
      <section className="ml-studio-foundations">
        {[{ label: "Data", icon: Database, text: "Versioned sources, assets, datasets, and lineage." }, { label: "Processing", icon: Workflow, text: "Asynchronous CPU, GPU, and semantic jobs." }, { label: "Research", icon: FlaskConical, text: "Annotations, hypotheses, evaluations, and runs." }, { label: "Production", icon: Rocket, text: "Registry, deployment, monitoring, and rollback." }].map(({ label, icon: Icon, text }) => <article key={label}><Icon size={18} /><h3>{label}</h3><p>{text}</p></article>)}
      </section>
      <section className="ml-studio-notice"><CircleHelp size={17} /><span>Phase 2 will introduce the durable PostgreSQL and object-storage foundation before any collection, ingestion, or training workflows are enabled.</span></section>
    </section>
  </main>;
}
