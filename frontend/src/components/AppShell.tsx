import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  IconChart,
  IconClose,
  IconFlask,
  IconMap,
  IconMenu,
  IconMonitor,
  IconMoon,
  IconOverview,
  IconShield,
  IconSparkle,
  IconStore,
  IconSun,
  IconTruck,
  IconUpload,
  IconUsers,
} from "./icons";
import { useActiveDatasets } from "../features/datasets/useDatasets";
import { useOlistOverview } from "../features/olist/queries";
import { formatNumber } from "../lib/format";
import { useTheme, type ThemePreference } from "../lib/theme";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
}

const OLIST_NAV: NavItem[] = [
  { to: "/olist/overview", label: "Executive overview", icon: <IconOverview className="nav-icon" /> },
  { to: "/olist/delivery", label: "Delivery & reviews", icon: <IconTruck className="nav-icon" /> },
  { to: "/olist/customers", label: "Customers & retention", icon: <IconUsers className="nav-icon" /> },
  { to: "/olist/sellers", label: "Sellers & concentration", icon: <IconStore className="nav-icon" /> },
  { to: "/olist/markets", label: "Categories & regions", icon: <IconMap className="nav-icon" /> },
  { to: "/olist/insights", label: "Decision center", icon: <IconSparkle className="nav-icon" /> },
  { to: "/olist/research", label: "Research findings", icon: <IconFlask className="nav-icon" /> },
];

const PAGE_TITLES: Record<string, [string, string]> = {
  "/olist/overview": ["Olist demo", "Executive overview"],
  "/olist/delivery": ["Olist demo", "Delivery & reviews"],
  "/olist/customers": ["Olist demo", "Customers & retention"],
  "/olist/sellers": ["Olist demo", "Sellers & concentration"],
  "/olist/markets": ["Olist demo", "Categories & regions"],
  "/olist/insights": ["Olist demo", "Decision center"],
  "/olist/research": ["Olist demo", "Research findings"],
  "/data": ["Your data", "Upload a spreadsheet"],
};

function breadcrumbFor(pathname: string): [string, string] {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname];
  if (pathname.startsWith("/data/") && pathname.endsWith("/performance")) return ["Your data", "Performance"];
  if (pathname.startsWith("/data/") && pathname.endsWith("/quality")) return ["Your data", "Data quality impact"];
  if (pathname.startsWith("/data/") && pathname.endsWith("/insights")) return ["Your data", "Decision center"];
  if (pathname.startsWith("/data/") && pathname.endsWith("/customers")) return ["Your data", "Customers"];
  if (pathname.startsWith("/data/")) return ["Your data", "Dashboard"];
  return ["MIERU", "Home"];
}

function Sidebar({ menuOpen, onToggleMenu }: { menuOpen: boolean; onToggleMenu: () => void }) {
  const datasets = useActiveDatasets();
  return (
    <nav className={`sidebar${menuOpen ? " open" : ""}`} aria-label="Primary">
      <div className="sidebar-head">
        <NavLink to="/olist/overview" className="brand" aria-label="MIERU home">
          <span className="brand-mark" aria-hidden="true">
            見
          </span>
          <span>
            <span className="brand-name">MIERU</span>
            <span className="brand-tagline">Commerce Intelligence Studio</span>
          </span>
        </NavLink>
        <button type="button" className="sidebar-toggle" aria-expanded={menuOpen} aria-controls="primary-navigation" onClick={onToggleMenu}>
          {menuOpen ? <IconClose /> : <IconMenu />}
          <span>{menuOpen ? "Close" : "Menu"}</span>
        </button>
      </div>

      <div className="nav-groups" id="primary-navigation">
        <div className="nav-group">
          <div className="nav-group-label">Olist marketplace demo</div>
          {OLIST_NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              {item.icon}
              {item.label}
            </NavLink>
          ))}
        </div>

        <div className="nav-group">
          <div className="nav-group-label">Your data</div>
          <NavLink to="/data" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <IconUpload className="nav-icon" />
            Upload spreadsheet
          </NavLink>
          {datasets.map((dataset) => (
            <div key={dataset.dataset_id} className="stack" style={{ gap: 2 }}>
              <NavLink to={`/data/${dataset.dataset_id}`} end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`} title={dataset.display_name}>
                <IconChart className="nav-icon" />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{dataset.display_name}</span>
                {dataset.status !== "ready" && <span className="nav-badge">{dataset.status === "failed" ? "error" : "…"}</span>}
              </NavLink>
              {dataset.status === "ready" && (
                <>
                  <NavLink
                    to={`/data/${dataset.dataset_id}/performance`}
                    className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                    style={{ paddingLeft: 42, fontSize: "0.8125rem" }}
                  >
                    <IconChart className="nav-icon" style={{ width: 15, height: 15 }} />
                    Performance
                  </NavLink>
                  <NavLink
                    to={`/data/${dataset.dataset_id}/customers`}
                    className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                    style={{ paddingLeft: 42, fontSize: "0.8125rem" }}
                  >
                    <IconUsers className="nav-icon" style={{ width: 15, height: 15 }} />
                    Customers
                  </NavLink>
                  <NavLink
                    to={`/data/${dataset.dataset_id}/quality`}
                    className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                    style={{ paddingLeft: 42, fontSize: "0.8125rem" }}
                  >
                    <IconShield className="nav-icon" style={{ width: 15, height: 15 }} />
                    Data quality
                  </NavLink>
                  <NavLink
                    to={`/data/${dataset.dataset_id}/insights`}
                    className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                    style={{ paddingLeft: 42, fontSize: "0.8125rem" }}
                  >
                    <IconSparkle className="nav-icon" style={{ width: 15, height: 15 }} />
                    Insights
                  </NavLink>
                </>
              )}
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          Uploads stay private to this browser session and expire automatically.
          <br />
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API reference
          </a>{" "}
          · v0.1
          <br />
          Olist data:{" "}
          <a href="https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce" target="_blank" rel="noreferrer">
            Olist
          </a>
          ,{" "}
          <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noreferrer">
            CC BY-NC-SA 4.0
          </a>
          . Non-commercial demo.
        </div>
      </div>
    </nav>
  );
}

function ThemeToggle() {
  const { preference, resolved, setPreference } = useTheme();
  const next: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
  const Icon = preference === "system" ? IconMonitor : preference === "light" ? IconSun : IconMoon;
  const label = `Theme: ${preference}${preference === "system" ? ` (${resolved})` : ""}. Switch to ${next[preference]} theme.`;
  return (
    <button type="button" className="btn theme-toggle" aria-label={label} title={label} onClick={() => setPreference(next[preference])}>
      <Icon />
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [workspace, page] = breadcrumbFor(location.pathname);
  const isOlist = location.pathname.startsWith("/olist");
  const overview = useOlistOverview();
  const deliveredOrders = overview.data?.kpis.find((kpi) => kpi.metric_id === "olist.delivered_orders")?.value ?? null;
  const [menuOpen, setMenuOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    document.title = `${page} · MIERU`;
    setMenuOpen(false);
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    window.scrollTo({ top: 0 });
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname, page]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <Sidebar menuOpen={menuOpen} onToggleMenu={() => setMenuOpen((open) => !open)} />
      <div className="main">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>{workspace}</span>
            <span aria-hidden="true">/</span>
            <strong>{page}</strong>
          </div>
          <div className="topbar-spacer" />
          {isOlist && deliveredOrders !== null && (
            <span className="badge badge-accent topbar-badge">
              <span className="badge-dot" />
              Real data · {formatNumber(deliveredOrders)} delivered orders · {overview.data?.dataset.currency}
            </span>
          )}
          <ThemeToggle />
        </header>
        <main className="content" id="main-content" ref={mainRef} tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
