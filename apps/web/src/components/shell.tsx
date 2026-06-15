import { Activity, FileText, Gauge } from "lucide-react";
import Link from "next/link";

function NeuroAdLogo() {
  return (
    <div className="relative flex h-11 w-11 items-center justify-center rounded-xl border border-white/20 bg-white text-black shadow-[0_0_0_1px_rgba(255,255,255,0.08)]">
      <svg viewBox="0 0 44 44" className="h-8 w-8" aria-hidden="true">
        <path
          d="M9 27C14.2 27 17 22 17 15V12L27 32V29C27 22 29.8 17 35 17"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3.4"
        />
        <circle cx="9" cy="27" r="2.2" fill="currentColor" />
        <circle cx="35" cy="17" r="2.2" fill="currentColor" />
      </svg>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-background text-slate-50">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-black/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 lg:px-10">
          <Link href="/" className="flex items-center gap-3">
            <NeuroAdLogo />
            <p className="text-base font-semibold tracking-tight text-zinc-100 md:text-lg">NeuroAd Context Engine</p>
          </Link>

          <nav className="hidden items-center gap-1 text-sm text-zinc-400 md:flex">
            <Link href="/" className="flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-white/5 hover:text-white">
              <Gauge className="h-4 w-4" />
              Analyze
            </Link>
            <Link href="/" className="flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-white/5 hover:text-white">
              <Activity className="h-4 w-4" />
              Pipeline
            </Link>
            <Link href="/" className="flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-white/5 hover:text-white">
              <FileText className="h-4 w-4" />
              Reports
            </Link>
          </nav>
        </div>
      </header>
      {children}
    </main>
  );
}
