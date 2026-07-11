"use client";

import { Activity, FileText, Gauge, ArrowRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

function NeuroAdLogo() {
  return (
    <div className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-white/20 bg-white text-black shadow-[0_0_24px_rgba(255,255,255,0.08)]">
      <svg viewBox="0 0 44 44" className="h-7 w-7" aria-hidden="true">
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

const navItems = [
  { label: "Analyze", icon: Gauge, sectionId: "section-analyze" },
  { label: "Pipeline", icon: Activity, sectionId: "section-pipeline" },
  { label: "Reports", icon: FileText, sectionId: "section-reports" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isHome = pathname === "/";
  const [showHeader, setShowHeader] = useState(true);

  useEffect(() => {
    let lastY = window.scrollY;

    function handleScroll() {
      const currentY = window.scrollY;
      if (currentY < 32) {
        setShowHeader(true);
      } else if (currentY > lastY + 8) {
        setShowHeader(false);
      } else if (currentY < lastY - 8) {
        setShowHeader(true);
      }
      lastY = currentY;
    }

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  function scrollToSection(sectionId: string) {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <main className="min-h-screen w-screen overflow-x-clip bg-background text-slate-50">
      <header
        className={[
          "sticky top-0 z-30 w-screen border-b border-white/[0.06] bg-black/80 backdrop-blur-xl transition-transform duration-300",
          showHeader ? "translate-y-0" : "-translate-y-full"
        ].join(" ")}
      >
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 lg:px-10">
          <Link href="/" className="flex items-center gap-3 transition hover:opacity-80">
            <NeuroAdLogo />
            <div className="hidden sm:block">
              <p className="text-sm font-semibold tracking-tight text-white">NeuroAd</p>
              <p className="text-[10px] tracking-widest text-zinc-500">CONTEXT ENGINE</p>
            </div>
          </Link>

          {isHome ? (
            <button
              onClick={() => scrollToSection("input-section")}
              className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm font-semibold text-black transition hover:bg-zinc-200 md:hidden"
            >
              Upload
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          ) : (
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm font-semibold text-black transition hover:bg-zinc-200 md:hidden"
            >
              Upload
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}

          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon;
              return isHome ? (
                <button
                  key={item.label}
                  onClick={() => scrollToSection(item.sectionId)}
                  className="group flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm text-zinc-400 transition hover:bg-white/[0.06] hover:text-white"
                >
                  <Icon className="h-4 w-4 text-zinc-600 transition group-hover:text-white" />
                  {item.label}
                </button>
              ) : (
                <Link
                  key={item.label}
                  href={`/#${item.sectionId}`}
                  className="group flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm text-zinc-400 transition hover:bg-white/[0.06] hover:text-white"
                >
                  <Icon className="h-4 w-4 text-zinc-600 transition group-hover:text-white" />
                  {item.label}
                </Link>
              );
            })}

            <div className="ml-2 h-5 w-px bg-white/10" />

            {isHome ? (
              <button
                onClick={() => scrollToSection("input-section")}
                className="ml-2 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-black transition hover:bg-zinc-200"
              >
                Upload Video
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : (
              <Link
                href="/"
                className="ml-2 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-black transition hover:bg-zinc-200"
              >
                Upload Video
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
          </nav>
        </div>
      </header>
      {children}
    </main>
  );
}
