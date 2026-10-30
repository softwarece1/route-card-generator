/** User-facing workflow labels for route-card status codes. */

export const ROUTE_STATUS = {
  draft: "draft",
  ied_review: "ied_review",
  ied_complete: "ied_complete",
  approved: "approved",
};

/** Filter options for Extractions / IED queue. */
export const ROUTE_STATUS_FILTER_OPTIONS = [
  { label: "All workflow statuses", value: null },
  { label: "Data extracted", value: "draft" },
  { label: "Awaiting IED review", value: "ied_review" },
  { label: "Awaiting approval", value: "ied_complete" },
  { label: "Approved", value: "approved" },
  { label: "Analyzed (session)", value: "analyzed" },
  { label: "Open (session)", value: "open" },
  { label: "Failed (session)", value: "failed" },
];

export function routeStatusLabel(status) {
  const s = String(status || "").toLowerCase();
  if (s === "draft") return "Data extracted";
  if (s === "ied_review") return "Awaiting IED review";
  if (s === "ied_complete") return "Awaiting approval";
  if (s === "approved") return "Approved";
  if (s === "ready") return "Ready";
  if (!s) return "—";
  return status;
}

export function routeStatusTone(status) {
  const s = String(status || "").toLowerCase();
  if (s === "approved") return "success";
  if (s === "ied_complete") return "info";
  if (s === "ied_review" || s === "draft") return "warn";
  if (s === "failed") return "danger";
  if (s === "analyzed" || s === "open") return "info";
  return "neutral";
}

export function sessionStatusTone(status) {
  const s = String(status || "").toLowerCase();
  if (s === "analyzed" || s === "approved") return "success";
  if (s === "failed") return "danger";
  if (s === "analyzing" || s === "draft") return "warn";
  if (s === "open") return "info";
  return "neutral";
}

/** Prefer workflow (route) status; fall back to session status. */
export function displayStatusCode(row) {
  const route = String(row?.routeStatus || "").toLowerCase();
  if (route) return route;
  return String(row?.status || "").toLowerCase();
}

export function displayStatusLabel(row) {
  const route = String(row?.routeStatus || "").toLowerCase();
  if (route) return routeStatusLabel(route);
  const sess = String(row?.status || "").toLowerCase();
  if (!sess) return "—";
  if (sess === "analyzed") return "Analyzed";
  if (sess === "failed") return "Failed";
  if (sess === "open") return "Open";
  if (sess === "analyzing") return "Analyzing";
  return row.status || "—";
}

export function displayStatusTone(row) {
  const route = String(row?.routeStatus || "").toLowerCase();
  if (route) return routeStatusTone(route);
  return sessionStatusTone(row?.status);
}
