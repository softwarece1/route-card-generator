import { useCallback, useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Badge } from "primereact/badge";
import { Sidebar } from "primereact/sidebar";
import { getUser } from "@/lib/auth";
import { logout } from "@/services/authApi";
import ThemeToggle from "@/components/ThemeToggle";
import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/services/routeCardApi";
import "./app-shell.scss";

function roleLabel(role) {
  if (role === "admin") return "Admin";
  if (role === "dept_head") return "Dept head";
  return "Engineer";
}

function navItemsForRole(role) {
  const base = [
    { to: "/generator", end: true, icon: "pi pi-home", label: "Generator", id: "generator" },
    { to: "/history", end: false, icon: "pi pi-history", label: "Extractions", id: "history" },
  ];
  if (role === "admin") {
    base.push({
      to: "/uploads",
      end: false,
      icon: "pi pi-folder-open",
      label: "Uploads",
      id: "uploads",
    });
    base.push({
      to: "/system",
      end: false,
      icon: "pi pi-server",
      label: "System",
      id: "system",
    });
  }
  if (role === "admin" || role === "dept_head") {
    base.push({
      to: "/users",
      end: false,
      icon: "pi pi-users",
      label: "Users",
      id: "users",
    });
  }
  base.push({
    to: "/operation-templates",
    end: false,
    icon: "pi pi-list",
    label: "Templates",
    id: "templates",
  });
  return base;
}

/**
 * Dark chrome (Option C): sidebar + topbar same navy; pages supply PageHeader.
 */
export default function AppShell({ active = "generator", children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = getUser();
  const items = navItemsForRole(user?.role);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unread, setUnread] = useState(0);

  const loadNotifs = useCallback(async () => {
    try {
      const data = await fetchNotifications();
      setNotifications(data.items || []);
      setUnread(data.unreadCount || 0);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadNotifs();
    const t = setInterval(loadNotifs, 20000);
    return () => clearInterval(t);
  }, [loadNotifs]);

  useEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
    const toTop = () => {
      window.scrollTo({
        top: 0,
        left: 0,
        behavior: "instant" in window ? "instant" : "auto",
      });
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      const main = document.querySelector(".rca-main");
      if (main) main.scrollTop = 0;
    };
    toTop();
    const id = window.requestAnimationFrame(toTop);
    return () => window.cancelAnimationFrame(id);
  }, [location.pathname, active]);

  return (
    <div className="rca-shell rca-shell--with-sidebar">
      <aside className="rca-sidebar" aria-label="Main navigation">
        <div className="rca-sidebar__brand">
          <span className="rca-sidebar__logo" aria-hidden>
            RC
          </span>
          <div className="rca-sidebar__brand-copy">
            <span className="rca-sidebar__brand-mark">OARC</span>
            <span className="rca-sidebar__brand-text">Route Card</span>
          </div>
        </div>
        <nav className="rca-sidebar__nav">
          <p className="rca-sidebar__section">Navigate</p>
          {items.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rca-sidebar__link${isActive || active === item.id ? " is-active" : ""}`
              }
            >
              <i className={item.icon} aria-hidden />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="rca-main">
        <header className="rca-topbar">
          <div className="rca-topbar__title">
            <h1>Automated OARC Generator</h1>
            <p>From drawings to manufacturable route.</p>
          </div>
          <div className="rca-topbar__right">
            <Button
              type="button"
              icon="pi pi-bell"
              rounded
              text
              className="p-overlay-badge"
              aria-label="Notifications"
              onClick={() => {
                setNotifOpen(true);
                loadNotifs();
              }}
            >
              {unread > 0 ? <Badge value={unread} severity="danger" /> : null}
            </Button>
            <span className="rca-chip">
              <i className="pi pi-id-card" />
              {roleLabel(user?.role)}
              {user?.dept ? ` · ${user.dept}` : ""}
            </span>
            <span className="rca-chip">
              <i className="pi pi-user" />
              {user?.display_name ||
                user?.name ||
                user?.empId ||
                user?.username ||
                "User"}
            </span>
            <ThemeToggle className="rca-topbar__theme" />
            <Button
              type="button"
              icon="pi pi-sign-out"
              rounded
              text
              className="rca-topbar__logout"
              aria-label="Logout"
              tooltip="Logout"
              tooltipOptions={{ position: "bottom" }}
              onClick={() => {
                logout();
                navigate("/");
              }}
            />
          </div>
        </header>

        {children}
      </div>

      <Sidebar
        visible={notifOpen}
        position="right"
        onHide={() => setNotifOpen(false)}
        header="Notifications"
      >
        <div className="flex justify-content-end mb-2">
          <Button
            type="button"
            label="Mark all read"
            text
            size="small"
            onClick={async () => {
              await markAllNotificationsRead();
              loadNotifs();
            }}
          />
        </div>
        {(notifications || []).length === 0 && (
          <p style={{ color: "var(--pmf-text-muted)" }}>No notifications.</p>
        )}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {notifications.map((n) => (
            <li
              key={n.id}
              style={{
                padding: "0.75rem 0",
                borderBottom: "1px solid var(--pmf-border, #333)",
                opacity: n.readAt ? 0.65 : 1,
              }}
            >
              <button
                type="button"
                style={{
                  background: "none",
                  border: 0,
                  color: "inherit",
                  textAlign: "left",
                  width: "100%",
                  cursor: "pointer",
                }}
                onClick={async () => {
                  await markNotificationRead(n.id);
                  if (n.link) navigate(n.link);
                  setNotifOpen(false);
                  loadNotifs();
                }}
              >
                <strong>{n.title}</strong>
                <div style={{ fontSize: "0.85rem", marginTop: 4 }}>{n.body}</div>
              </button>
            </li>
          ))}
        </ul>
      </Sidebar>
    </div>
  );
}
