import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { InputText } from "primereact/inputtext";
import { Message } from "primereact/message";
import AppShell from "@/components/AppShell";
import ExcelPreviewDialog from "@/components/ExcelPreviewDialog";
import PageHeader from "@/components/PageHeader";
import { TableActions } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { isExcelFilename, triggerBlobDownload } from "@/lib/excelPreview";
import { toast } from "@/lib/toast";
import {
  fetchAdminDocumentBlob,
  fetchAdminUploads,
} from "@/services/routeCardApi";
import "./uploads.scss";

const ROLE_LABEL = {
  drawing: "Drawing (GA)",
  partslist: "Parts List",
  wirelist: "Wire List",
};

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function canPreview(doc) {
  const t = String(doc?.fileType || doc?.filename || "").toLowerCase();
  return (
    t.includes("pdf") ||
    t.endsWith(".pdf") ||
    t.includes("tif") ||
    isExcelFilename(doc?.filename) ||
    isExcelFilename(doc?.fileType)
  );
}

function isExcelDoc(doc) {
  return isExcelFilename(doc?.filename) || isExcelFilename(doc?.fileType);
}

function deptKey(session) {
  return (session?.user?.dept || "").trim() || "Unassigned";
}

function empKey(session) {
  const u = session?.user;
  if (!u) return "unknown";
  return String(u.empId || u.id || "unknown");
}

function empLabel(session) {
  const u = session?.user;
  if (!u) return "Unknown user";
  const id = u.empId || u.id || "—";
  return u.name ? `${id} — ${u.name}` : String(id);
}

function sessionFolderLabel(session) {
  const pn = (session.partNumber || "").trim();
  return pn ? `Session ${session.sessionId} · ${pn}` : `Session ${session.sessionId}`;
}

/**
 * Build sidebar tree:
 * Uploads → Department → Employee → Session
 */
function buildTree(sessions) {
  const root = {
    id: "root",
    label: "Uploads",
    kind: "root",
    children: [],
  };
  const byDept = new Map();

  for (const s of sessions) {
    const dk = deptKey(s);
    if (!byDept.has(dk)) {
      byDept.set(dk, {
        id: `dept:${dk}`,
        label: dk,
        kind: "dept",
        dept: dk,
        children: [],
      });
    }
    const deptNode = byDept.get(dk);
    const ek = empKey(s);
    let empNode = deptNode.children.find((c) => c.empKey === ek);
    if (!empNode) {
      empNode = {
        id: `emp:${dk}:${ek}`,
        label: empLabel(s),
        kind: "emp",
        dept: dk,
        empKey: ek,
        children: [],
      };
      deptNode.children.push(empNode);
    }
    empNode.children.push({
      id: `session:${s.sessionId}`,
      label: sessionFolderLabel(s),
      kind: "session",
      sessionId: s.sessionId,
      partNumber: s.partNumber || "",
      session: s,
      children: [],
    });
  }

  const depts = [...byDept.values()].sort((a, b) => a.label.localeCompare(b.label));
  for (const d of depts) {
    d.children.sort((a, b) => a.label.localeCompare(b.label));
    for (const e of d.children) {
      e.children.sort((a, b) => (b.sessionId || 0) - (a.sessionId || 0));
    }
  }
  root.children = depts;
  return root;
}

function flattenFiles(sessions, selection) {
  const rows = [];
  for (const s of sessions) {
    if (selection?.kind === "dept" && deptKey(s) !== selection.dept) continue;
    if (selection?.kind === "emp" && (deptKey(s) !== selection.dept || empKey(s) !== selection.empKey)) {
      continue;
    }
    if (selection?.kind === "session" && s.sessionId !== selection.sessionId) continue;

    for (const doc of s.documents || []) {
      rows.push({
        ...doc,
        sessionId: s.sessionId,
        partNumber: s.partNumber || "",
        partName: s.partName || "",
        sessionStatus: s.status,
        uploadedBy:
          doc.uploadedBy || s.user?.empId || s.user?.name || "—",
        uploadedAt: doc.createdAt || s.updatedAt || s.createdAt,
        roleLabel: ROLE_LABEL[doc.role] || doc.role,
      });
    }
  }
  rows.sort((a, b) => String(b.uploadedAt || "").localeCompare(String(a.uploadedAt || "")));
  return rows;
}

function breadcrumbFor(selection) {
  const crumbs = [{ id: "root", label: "Home" }];
  if (!selection || selection.kind === "root") {
    crumbs.push({ id: "uploads", label: "Uploads" });
    return crumbs;
  }
  crumbs.push({ id: "uploads", label: "Uploads" });
  if (selection.dept) crumbs.push({ id: `dept:${selection.dept}`, label: selection.dept });
  if (selection.kind === "emp" || selection.kind === "session") {
    crumbs.push({
      id: selection.kind === "emp" ? selection.id : `emp:${selection.dept}:${selection.empKey}`,
      label: selection.kind === "emp" ? selection.label : selection.empLabel || selection.empKey,
    });
  }
  if (selection.kind === "session") {
    crumbs.push({ id: selection.id, label: selection.label });
  }
  return crumbs;
}

function filterTree(node, q) {
  if (!q) return node;
  const needle = q.toLowerCase();
  const matchSelf = String(node.label || "").toLowerCase().includes(needle);
  const kids = (node.children || []).map((c) => filterTree(c, q)).filter(Boolean);
  if (!matchSelf && !kids.length) return null;
  // Prefer matching descendants; if only this node matches, keep its full children.
  const children = kids.length ? kids : node.children || [];
  return { ...node, children };
}

function collectExpandedIds(node, into = new Set()) {
  if (!node) return into;
  if ((node.children || []).length) {
    into.add(node.id);
    for (const c of node.children) collectExpandedIds(c, into);
  }
  return into;
}

function FolderTreeNode({ node, selectedId, expanded, onToggle, onSelect, depth = 0 }) {
  const hasKids = (node.children || []).length > 0;
  const isOpen = expanded.has(node.id);
  const isSelected = selectedId === node.id;

  return (
    <div className="rc-up-tree__node">
      <div
        className={`rc-up-tree__row${isSelected ? " is-selected" : ""}`}
        style={{ paddingLeft: `${0.4 + depth * 0.75}rem` }}
      >
        {hasKids ? (
          <button
            type="button"
            className="rc-up-tree__twist"
            aria-label={isOpen ? "Collapse" : "Expand"}
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
          >
            <i className={`pi ${isOpen ? "pi-chevron-down" : "pi-chevron-right"}`} />
          </button>
        ) : (
          <span className="rc-up-tree__twist-spacer" />
        )}
        <button
          type="button"
          className="rc-up-tree__label"
          onClick={() => onSelect(node)}
        >
          <i
            className={`pi ${
              isSelected || isOpen ? "pi-folder-open" : "pi-folder"
            }`}
            aria-hidden
          />
          <span title={node.label}>{node.label}</span>
        </button>
      </div>
      {hasKids && isOpen
        ? node.children.map((child) => (
            <FolderTreeNode
              key={child.id}
              node={child}
              selectedId={selectedId}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))
        : null}
    </div>
  );
}

export default function UploadsPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selection, setSelection] = useState({ id: "root", label: "Uploads", kind: "root" });
  const [expanded, setExpanded] = useState(() => new Set(["root"]));
  const [query, setQuery] = useState("");
  const [folderQuery, setFolderQuery] = useState("");
  const [preview, setPreview] = useState(null);
  const [excelPreview, setExcelPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const tree = useMemo(() => buildTree(items), [items]);

  const visibleTree = useMemo(() => {
    const q = folderQuery.trim();
    if (q.length < 2) return tree;
    return filterTree(tree, q) || { ...tree, children: [] };
  }, [tree, folderQuery]);

  useEffect(() => {
    const q = folderQuery.trim();
    if (q.length < 2) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      collectExpandedIds(visibleTree, next);
      return next;
    });
  }, [folderQuery, visibleTree]);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true);
    try {
      const res = await fetchAdminUploads({});
      setItems(res.items || []);
      setExpanded((prev) => {
        const next = new Set(prev);
        next.add("root");
        return next;
      });
    } catch (e) {
      toast.error(e.message || "Could not load uploads");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(
    () => () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    },
    [preview?.url],
  );

  const files = useMemo(() => {
    let rows = flattenFiles(items, selection);
    const q = query.trim().toLowerCase();
    if (q.length >= 2) {
      rows = rows.filter((r) => {
        const hay = `${r.filename || ""} ${r.uploadedBy || ""} ${r.partNumber || ""} ${r.roleLabel || ""}`.toLowerCase();
        return hay.includes(q);
      });
    }
    return rows;
  }, [items, selection, query]);

  const crumbs = useMemo(() => {
    const enriched = { ...selection };
    if (selection?.kind === "session") {
      const s = items.find((x) => x.sessionId === selection.sessionId);
      if (s) {
        enriched.empKey = empKey(s);
        enriched.empLabel = empLabel(s);
        enriched.dept = deptKey(s);
      }
    }
    return breadcrumbFor(enriched);
  }, [selection, items]);

  const onToggle = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onSelect = (node) => {
    setSelection(node);
    if ((node.children || []).length) {
      setExpanded((prev) => new Set(prev).add(node.id));
    }
  };

  const openPreview = async (doc) => {
    if (!doc?.id) return;
    setPreviewLoading(true);
    try {
      const blob = await fetchAdminDocumentBlob(doc.id);
      if (isExcelDoc(doc)) {
        if (preview?.url) URL.revokeObjectURL(preview.url);
        setPreview(null);
        setExcelPreview({ blob, name: doc.filename });
      } else {
        if (preview?.url) URL.revokeObjectURL(preview.url);
        setExcelPreview(null);
        setPreview({
          url: URL.createObjectURL(blob),
          name: doc.filename,
          type: doc.fileType,
        });
      }
    } catch (e) {
      toast.error(e.message || "Could not open preview");
    } finally {
      setPreviewLoading(false);
    }
  };

  const downloadDoc = async (doc) => {
    if (!doc?.id) return;
    try {
      const blob = await fetchAdminDocumentBlob(doc.id);
      triggerBlobDownload(blob, doc.filename || `document-${doc.id}`);
      toast.success(`Downloaded ${doc.filename || "file"}`);
    } catch (e) {
      toast.error(e.message || "Could not download file");
    }
  };

  if (!isAdmin) {
    return (
      <AppShell active="uploads">
        <div className="rc-uploads">
          <PageHeader title="Uploads" subtitle="Admin only" icon="pi pi-folder" />
          <Message severity="warn" text="Only administrators can browse uploaded documents." className="w-full" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell active="uploads">
      <div className="rc-uploads">
        <PageHeader
          title="Uploads"
          subtitle="Browse session folders and documents. Preview or download files."
          icon="pi pi-folder-open"
          actions={
            <Button
              type="button"
              label="Refresh"
              icon="pi pi-refresh"
              size="small"
              outlined
              loading={loading}
              onClick={load}
            />
          }
        />

        <div className="rc-up-layout">
          <aside className="rc-up-side" aria-label="Folders">
            <div className="rc-up-side__head">
              <h2>Folders</h2>
            </div>
            <div className="rc-up-side__search">
              <i className="pi pi-search" aria-hidden />
              <InputText
                value={folderQuery}
                onChange={(e) => setFolderQuery(e.target.value)}
                placeholder="Search folders…"
              />
            </div>
            <div className="rc-up-tree">
              {(visibleTree?.children || []).length === 0 && folderQuery.trim().length >= 2 ? (
                <p className="rc-up-tree__empty">No folders match “{folderQuery.trim()}”.</p>
              ) : (
                <FolderTreeNode
                  node={visibleTree}
                  selectedId={selection?.id}
                  expanded={expanded}
                  onToggle={onToggle}
                  onSelect={onSelect}
                />
              )}
            </div>
          </aside>

          <section className="rc-up-main">
            <nav className="rc-up-crumb" aria-label="Breadcrumb">
              {crumbs.map((c, i) => (
                <span key={c.id} className="rc-up-crumb__item">
                  {i > 0 ? <span className="rc-up-crumb__sep">›</span> : null}
                  <button
                    type="button"
                    className={i === crumbs.length - 1 ? "is-current" : ""}
                    onClick={() => {
                      if (c.id === "root" || c.id === "uploads") {
                        onSelect(tree);
                        return;
                      }
                      const find = (n) => {
                        if (n.id === c.id) return n;
                        for (const ch of n.children || []) {
                          const hit = find(ch);
                          if (hit) return hit;
                        }
                        return null;
                      };
                      const node = find(tree);
                      if (node) onSelect(node);
                    }}
                  >
                    {c.label}
                  </button>
                </span>
              ))}
            </nav>

            <div className="rc-up-toolbar">
              <div className="rc-up-search">
                <i className="pi pi-search" aria-hidden />
                <InputText
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search documents (min. 2 characters)…"
                />
              </div>
              <Button
                type="button"
                label="Clear"
                size="small"
                outlined
                disabled={!query}
                onClick={() => setQuery("")}
              />
            </div>

            <div className="rc-up-table-wrap">
            <DataTable
              value={files}
              loading={loading || previewLoading}
              dataKey="id"
              paginator
              rows={10}
              rowsPerPageOptions={[10, 25, 50]}
              pageLinkSize={5}
              paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
              currentPageReportTemplate="Showing {first}-{last} of {totalRecords} files"
              emptyMessage="No documents found"
              className="rc-up-table"
              size="small"
              scrollable
              scrollHeight="flex"
            >
              <Column
                header="Filename"
                body={(row) => (
                  <div className="rc-up-filecell">
                    <i
                      className={`pi ${
                        String(row.fileType || "").toUpperCase() === "PDF"
                          ? "pi-file-pdf"
                          : "pi-file"
                      }`}
                      aria-hidden
                    />
                    <div>
                      <strong title={row.filename}>{row.filename}</strong>
                      <span>{row.roleLabel}</span>
                    </div>
                  </div>
                )}
                style={{ minWidth: "14rem" }}
              />
              <Column
                field="uploadedBy"
                header="Uploaded by"
                style={{ minWidth: "8rem" }}
              />
              <Column
                header="At"
                body={(row) => formatWhen(row.uploadedAt)}
                style={{ minWidth: "10rem" }}
              />
              <Column
                header="Part Number"
                body={(row) => row.partNumber || "—"}
                style={{ minWidth: "9rem" }}
              />
              <Column
                header="Actions"
                body={(row) => (
                  <TableActions>
                    {canPreview(row) ? (
                      <Button
                        type="button"
                        icon="pi pi-eye"
                        rounded
                        text
                        size="small"
                        aria-label="Preview"
                        onClick={() => openPreview(row)}
                      />
                    ) : null}
                    <Button
                      type="button"
                      icon="pi pi-download"
                      rounded
                      text
                      size="small"
                      aria-label="Download"
                      onClick={() => downloadDoc(row)}
                    />
                  </TableActions>
                )}
                style={{ width: "7rem" }}
              />
            </DataTable>
            </div>
          </section>
        </div>
      </div>

      <Dialog
        header={preview?.name ? `Preview — ${preview.name}` : "Preview"}
        visible={Boolean(preview)}
        onHide={() => {
          if (preview?.url) URL.revokeObjectURL(preview.url);
          setPreview(null);
        }}
        style={{ width: "min(92vw, 56rem)" }}
        maximizable
      >
        {preview?.url ? (
          <object
            className="rc-uploads__preview"
            data={preview.url}
            type="application/pdf"
            aria-label={preview.name}
          >
            <p>
              Preview not available.{" "}
              <a href={preview.url} download={preview.name}>
                Download instead
              </a>
              .
            </p>
          </object>
        ) : null}
      </Dialog>

      <ExcelPreviewDialog
        visible={Boolean(excelPreview)}
        blob={excelPreview?.blob || null}
        filename={excelPreview?.name || ""}
        onHide={() => setExcelPreview(null)}
      />
    </AppShell>
  );
}
