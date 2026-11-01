import type { Viewer } from "@/auth";
import { signOut } from "@/auth";
import { NavLinks, type NavLink } from "./nav-links";

const EXPERT_LINKS: NavLink[] = [
  { href: "/queue", label: "صف بررسی", icon: "queue" },
  { href: "/matches", label: "تأیید تطبیق‌ها", icon: "matches" },
  { href: "/reports", label: "گزارش‌ها", icon: "reports" },
  { href: "/help", label: "راهنما", icon: "help" },
];
const ADMIN_LINKS: NavLink[] = [
  { href: "/catalog/imports", label: "ورود کاتالوگ", icon: "imports" },
  { href: "/rules", label: "قواعد سود", icon: "rules" },
  { href: "/sources", label: "منابع", icon: "sources" },
  { href: "/settings", label: "تنظیمات", icon: "settings" },
];

/** Sidebar on wide screens, a top bar on narrow ones. */
export function Nav({ viewer }: { viewer: Viewer }) {
  const isAdmin = viewer.roles.includes("admin");
  async function logout() {
    "use server";
    await signOut({ redirectTo: "/" });
  }
  return (
    <aside className="flex flex-col gap-4 bg-gradient-to-b from-indigo-950 to-slate-900 px-3 py-4 text-white md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0 md:py-6">
      <div className="flex items-center gap-3 px-2">
        <span aria-hidden className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-400 to-violet-500 text-lg font-bold shadow-lg">
          ق
        </span>
        <div className="flex flex-col leading-tight">
          <span className="font-semibold">دستیار قیمت‌گذاری</span>
          <span className="text-xs text-indigo-200/70">تصمیم با کارشناس است</span>
        </div>
      </div>
      <nav aria-label="منوی اصلی" className="md:flex-1" data-tour="nav">
        <NavLinks expert={EXPERT_LINKS} admin={isAdmin ? ADMIN_LINKS : []} />
      </nav>
      <div className="flex items-center gap-3 rounded-xl bg-white/6 p-3">
        <span aria-hidden className="grid size-8 place-items-center rounded-full bg-indigo-500/30 text-sm font-semibold uppercase">
          {viewer.username.slice(0, 1)}
        </span>
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <bdi className="truncate text-sm font-medium">{viewer.username}</bdi>
          <span className="text-xs text-indigo-200/70">{isAdmin ? "مدیر" : "کارشناس"}</span>
        </div>
        <form action={logout}>
          <button type="submit" className="cursor-pointer rounded-md px-2 py-1 text-xs text-indigo-100 hover:bg-white/10">
            خروج
          </button>
        </form>
      </div>
    </aside>
  );
}
