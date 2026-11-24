import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { ConfirmDialog, confirmDialog } from "primereact/confirmdialog";
import SafeInputText from "@/components/SafeInputText";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import { triggerBlobDownload } from "@/lib/excelPreview";
import {
  createRefFolder,
  deleteRefDocument,
  deleteRefDocumentVersion,
  deleteRefFolder,
  fetchRefDocumentBlob,
  fetchRefDocumentVersions,
  fetchRefDocuments,
  fetchRefFolders,
  updateRefFolder,
  uploadRefDocument,
} from "@/services/routeCardApi";
import { normalizeFolderCode } from "@/lib/refDocLinks";
import "./reference-sheets.scss";

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  return `${(v / (1024 * 1024)).toFixed(1)} MB`;
}

/** Match backend: PS200 / ps-0200.pdf → PS200 for category PS */
function docCodeFromFilename(categoryCode, filename) {
  const fc = normalizeFolderCode(categoryCode);
  if (!fc || !filename) return null;
  const stem = String(filename).replace(/\.pdf$/i, "").trim();
  const m = stem.match(/^([A-Za-z]{1,6})\s*[-_]?\s*0*(\d{1,6})$/i);
  if (m && normalizeFolderCode(m[1]) === fc) return `${fc}${parseInt(m[2], 10)}`;
  if (/^\d{1,6}$/.test(stem)) return `${fc}${parseInt(stem, 10)}`;
  return null;
}

function nextVersionForDoc(docs, docCode) {
  if (!docCode) return 1;
  const existing = (docs || []).find(
    (d) => String(d.docCode || "").toUpperCase() === String(docCode).toUpperCase(),
  );
  if (!existing) return 1;
  return (Number(existing.versionNumber) || 1) + 1;
}

const emptyAddFile = () => ({
  visible: false,
  file: null,
  filename: "",
  version: 1,
  docCode: null,
  dragOver: false,
});

export default function ReferenceSheetsPage() {
  const user = getUser();
  const role = user?.role;
  const canManage = role === "admin" || role === "dept_head";
  // Engineers (and managers) may browse / view / download; IED stays on review queue
  const canView = canManage || role === "engineer";

  const [folders, setFolders] = useState([]);
  const [loadingFolders, setLoadingFolders] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [folderDialog, setFolderDialog] = useState({
    visible: false,
    mode: "create",
    id: null,
    code: "",
    name: "",
  });
  const [uploading, setUploading] = useState(false);
  const [addFile, setAddFile] = useState(emptyAddFile);
  const [preview, setPreview] = useState(null);
  const [versionsDialog, setVersionsDialog] = useState({
    visible: false,
    doc: null,
    items: [],
    loading: false,
  });
  const [versionPick, setVersionPick] = useState({
    visible: false,
    action: null, // view | download | delete
    doc: null,
    items: [],
    loading: false,
  });
  const addFileInputRef = useRef(null);

  const selected = useMemo(
    () => folders.find((f) => f.id === selectedId) || null,
    [folders, selectedId],
  );

  const loadFolders = useCallback(async () => {
    setLoadingFolders(true);
    try {
      const res = await fetchRefFolders();
      const items = res?.items || [];
      setFolders(items);
      setSelectedId((prev) => {
        if (prev && items.some((f) => f.id === prev)) return prev;
        return items[0]?.id ?? null;
      });
    } catch (e) {
      toast.error(e.message || "Could not load categories");
      setFolders([]);
    } finally {
      setLoadingFolders(false);
    }
  }, []);

  const loadDocs = useCallback(async (folderId) => {
    if (!folderId) {
      setDocs([]);
      return;
    }
    setLoadingDocs(true);
    try {
      const res = await fetchRefDocuments(folderId);
      setDocs(res?.items || []);
    } catch (e) {
      toast.error(e.message || "Could not load documents");
      setDocs([]);
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    if (!canView) return;
    loadFolders();
  }, [canView, loadFolders]);

  useEffect(() => {
    if (!canView) return;
    loadDocs(selectedId);
  }, [canView, selectedId, loadDocs]);

  useEffect(
    () => () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    },
    [preview?.url],
  );

  if (!canView) {
    return <Navigate to="/generator" replace />;
  }

  const downloadDoc = async (row, version = null) => {
    try {
      const blob = await fetchRefDocumentBlob(row.id ?? row.documentId, version);
      const name =
        row.originalFilename ||
        `${row.docCode || row.code || "sheet"}${version != null ? `_v${version}` : ""}.pdf`;
      triggerBlobDownload(blob, name);
    } catch (e) {
      toast.error(e.message || "Could not download");
    }
  };

  const openCreateFolder = () =>
    setFolderDialog({ visible: true, mode: "create", id: null, code: "", name: "" });

  const openRenameFolder = (folder) =>
    setFolderDialog({
      visible: true,
      mode: "rename",
      id: folder.id,
      code: folder.code,
      name: folder.name || folder.code,
    });

  const saveFolder = async () => {
    try {
      if (folderDialog.mode === "create") {
        const code = folderDialog.code.trim();
        if (!code) {
          toast.error("Category code is required");
          return;
        }
        if (folders.some((f) => f.code === code.toUpperCase())) {
          toast.error(`Category '${code.toUpperCase()}' already exists`);
          return;
        }
        const created = await createRefFolder({
          code,
          name: folderDialog.name.trim(),
        });
        toast.success(`Category ${created.code} created`);
        setFolderDialog((d) => ({ ...d, visible: false }));
        await loadFolders();
        setSelectedId(created.id);
      } else {
        await updateRefFolder(folderDialog.id, { name: folderDialog.name.trim() });
        toast.success("Category updated");
        setFolderDialog((d) => ({ ...d, visible: false }));
        await loadFolders();
      }
    } catch (e) {
      toast.error(e.message || "Save failed");
    }
  };

  const confirmDeleteFolder = (folder) => {
    confirmDialog({
      message: `Delete category ${folder.code} and all sheets inside?`,
      header: "Delete category",
      icon: "pi pi-exclamation-triangle",
      acceptClassName: "p-button-danger p-button-sm",
      rejectClassName: "p-button-text p-button-sm",
      accept: async () => {
        try {
          await deleteRefFolder(folder.id);
          toast.success(`Deleted ${folder.code}`);
          if (selectedId === folder.id) setSelectedId(null);
          await loadFolders();
        } catch (e) {
          toast.error(e.message || "Delete failed");
        }
      },
    });
  };

  const openAddFile = () => {
    if (!selected) return;
    setAddFile({ ...emptyAddFile(), visible: true });
  };

  const applyAddFile = (file) => {
    if (!file || !selected) return;
    if (!/\.pdf$/i.test(file.name || "")) {
      toast.error("Only PDF files are allowed");
      return;
    }
    const filename = file.name || "upload.pdf";
    const docCode = docCodeFromFilename(selected.code, filename);
    const version = nextVersionForDoc(docs, docCode);
    setAddFile((s) => ({
      ...s,
      file,
      filename,
      docCode,
      version,
      dragOver: false,
    }));
  };

  const onAddFileInputChange = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) applyAddFile(file);
  };

  const onAddFilenameChange = (value) => {
    const filename = value;
    const docCode = docCodeFromFilename(selected?.code, filename);
    const version = nextVersionForDoc(docs, docCode);
    setAddFile((s) => ({ ...s, filename, docCode, version }));
  };

  const submitAddFile = async () => {
    if (!selectedId || !addFile.file) {
      toast.error("Choose a PDF file first");
      return;
    }
    if (!addFile.docCode) {
      toast.error(
        `Filename must match category (e.g. ${selected?.code || "PS"}200.pdf)`,
      );
      return;
    }
    // Ensure upload uses the (possibly edited) display name
    const uploadFile =
      addFile.filename && addFile.filename !== addFile.file.name
        ? new File([addFile.file], addFile.filename, {
            type: addFile.file.type || "application/pdf",
          })
        : addFile.file;

    setUploading(true);
    try {
      const doc = await uploadRefDocument(selectedId, uploadFile);
      if (doc.isNewVersion) {
        toast.success(`Uploaded ${doc.docCode} as version ${doc.versionNumber}`);
      } else {
        toast.success(`Uploaded ${doc.docCode} (v${doc.versionNumber || 1})`);
      }
      setAddFile(emptyAddFile());
      await loadDocs(selectedId);
      await loadFolders();
    } catch (err) {
      toast.error(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const openPreview = async (row, version = null) => {
    try {
      if (preview?.url) URL.revokeObjectURL(preview.url);
      const documentId = row.id ?? row.documentId;
      const blob = await fetchRefDocumentBlob(documentId, version);
      const url = URL.createObjectURL(blob);
      const verLabel =
        version != null
          ? ` v${version}`
          : row.versionNumber
            ? ` v${row.versionNumber}`
            : "";
      setPreview({
        url,
        title: `${row.docCode || row.code || "Sheet"}${verLabel}`,
        filename: row.originalFilename,
        documentId,
        version,
        docCode: row.docCode || row.code,
      });
    } catch (e) {
      toast.error(e.message || "Could not open PDF");
    }
  };

  const openVersions = async (row) => {
    setVersionsDialog({ visible: true, doc: row, items: [], loading: true });
    try {
      const res = await fetchRefDocumentVersions(row.id);
      setVersionsDialog({
        visible: true,
        doc: row,
        items: res?.items || [],
        loading: false,
      });
    } catch (e) {
      toast.error(e.message || "Could not load versions");
      setVersionsDialog({ visible: false, doc: null, items: [], loading: false });
    }
  };

  const confirmDeleteDoc = (row) => {
    confirmDialog({
      message: `Delete ${row.docCode} and all versions?`,
      header: "Delete sheet",
      icon: "pi pi-exclamation-triangle",
      acceptClassName: "p-button-danger p-button-sm",
      rejectClassName: "p-button-text p-button-sm",
      accept: async () => {
        try {
          await deleteRefDocument(row.id);
          toast.success(`Deleted ${row.docCode}`);
          await loadDocs(selectedId);
          await loadFolders();
        } catch (e) {
          toast.error(e.message || "Delete failed");
        }
      },
    });
  };

  const confirmDeleteVersion = (row, versionNumber) => {
    confirmDialog({
      message: `Delete ${row.docCode} version ${versionNumber}?`,
      header: "Delete version",
      icon: "pi pi-exclamation-triangle",
      acceptClassName: "p-button-danger p-button-sm",
      rejectClassName: "p-button-text p-button-sm",
      accept: async () => {
        try {
          const res = await deleteRefDocumentVersion(row.id, versionNumber);
          toast.success(
            res.documentDeleted
              ? `Deleted ${row.docCode}`
              : `Deleted ${row.docCode} v${versionNumber}`,
          );
          await loadDocs(selectedId);
          await loadFolders();
        } catch (e) {
          toast.error(e.message || "Delete failed");
        }
      },
    });
  };

  const runDocAction = (row, action, version = null, versionMeta = null) => {
    const payload = {
      ...row,
      originalFilename: versionMeta?.originalFilename || row.originalFilename,
    };
    if (action === "view") openPreview(payload, version);
    else if (action === "download") downloadDoc(payload, version);
    else if (action === "delete") {
      if (version != null && (Number(row.versionNumber) || 1) > 1) {
        confirmDeleteVersion(row, version);
      } else {
        confirmDeleteDoc(row);
      }
    }
  };

  const requestDocAction = async (row, action) => {
    // History always opens the version list (selection happens there for view/download)
    if (action === "history") {
      openVersions(row);
      return;
    }
    const latestVer = Number(row.versionNumber) || 1;
    if (latestVer <= 1) {
      runDocAction(row, action, 1);
      return;
    }
    setVersionPick({
      visible: true,
      action,
      doc: row,
      items: [],
      loading: true,
    });
    try {
      const res = await fetchRefDocumentVersions(row.id);
      const items = res?.items || [];
      if (items.length <= 1) {
        setVersionPick({ visible: false, action: null, doc: null, items: [], loading: false });
        runDocAction(row, action, items[0]?.versionNumber ?? latestVer, items[0]);
        return;
      }
      setVersionPick({
        visible: true,
        action,
        doc: row,
        items,
        loading: false,
      });
    } catch (e) {
      toast.error(e.message || "Could not load versions");
      setVersionPick({ visible: false, action: null, doc: null, items: [], loading: false });
    }
  };

  const onPickVersion = (ver) => {
    const { doc, action } = versionPick;
    setVersionPick({ visible: false, action: null, doc: null, items: [], loading: false });
    if (!doc || !action) return;
    runDocAction(doc, action, ver.versionNumber, ver);
  };

  const versionPickTitle = () => {
    const code = versionPick.doc?.docCode || "sheet";
    if (versionPick.action === "view") return `Select version to view — ${code}`;
    if (versionPick.action === "download") return `Select version to download — ${code}`;
    if (versionPick.action === "delete") return `Select version to delete — ${code}`;
    return `Select version — ${code}`;
  };

  const docColumns = [
    { field: "docCode", header: "Code", sortable: true, style: { width: "7rem" } },
    { field: "originalFilename", header: "Filename", sortable: true },
    {
      field: "versionNumber",
      header: "Ver",
      style: { width: "4rem" },
      body: (row) => row.versionNumber ?? 1,
    },
    {
      field: "sizeBytes",
      header: "Size",
      style: { width: "6rem" },
      body: (row) => formatBytes(row.sizeBytes),
    },
    {
      field: "uploadedBy",
      header: "Uploaded by",
      style: { width: "8rem" },
      body: (row) => row.uploadedBy || "—",
    },
    {
      type: "actions",
      header: "",
      style: { width: canManage ? "10.5rem" : "7.5rem" },
      renderActions: (row) => (
        <>
          <Button
            type="button"
            icon="pi pi-eye"
            rounded
            text
            size="small"
            aria-label="View"
            tooltip="View"
            tooltipOptions={{ position: "top" }}
            onClick={() => requestDocAction(row, "view")}
          />
          <Button
            type="button"
            icon="pi pi-download"
            rounded
            text
            size="small"
            aria-label="Download"
            tooltip="Download"
            tooltipOptions={{ position: "top" }}
            onClick={() => requestDocAction(row, "download")}
          />
          <Button
            type="button"
            icon="pi pi-history"
            rounded
            text
            size="small"
            aria-label="Versions"
            tooltip="Versions"
            tooltipOptions={{ position: "top" }}
            onClick={() => requestDocAction(row, "history")}
          />
          {canManage ? (
            <Button
              type="button"
              icon="pi pi-trash"
              rounded
              text
              size="small"
              severity="danger"
              aria-label="Delete"
              onClick={() => requestDocAction(row, "delete")}
            />
          ) : null}
        </>
      ),
    },
  ];

  return (
    <AppShell active="refdocs">
      <ConfirmDialog />
      <div className="rc-refdocs">
        <PageHeader
          title="Reference sheets"
          subtitle={
            canManage
              ? "Shared process / safety / SOP PDFs"
              : "View and download shared process / safety / SOP PDFs"
          }
        />

        <div className="rc-refdocs__layout">
          <div className="rc-refdocs__shell">
            <div className="rc-refdocs__pane-head">
              <h3 className="rc-refdocs__pane-title">Categories</h3>
              {canManage ? (
                <div className="rc-refdocs__pane-tools">
                  <Button
                    type="button"
                    label="Add"
                    icon="pi pi-plus"
                    size="small"
                    onClick={openCreateFolder}
                  />
                </div>
              ) : null}
            </div>
            <div className="rc-refdocs__body">
              {loadingFolders ? (
                <p className="rc-refdocs__empty">Loading…</p>
              ) : folders.length === 0 ? (
                <p className="rc-refdocs__empty">No categories yet.</p>
              ) : (
                <ul className="rc-refdocs__folder-list">
                  {folders.map((f) => (
                    <li key={f.id}>
                      <button
                        type="button"
                        className={`rc-refdocs__folder-btn${
                          f.id === selectedId ? " rc-refdocs__folder-btn--active" : ""
                        }`}
                        onClick={() => setSelectedId(f.id)}
                      >
                        <span>
                          <strong>{f.code}</strong>
                          {f.name && f.name !== f.code ? ` · ${f.name}` : ""}
                        </span>
                        <span className="rc-refdocs__folder-meta">{f.documentCount ?? 0}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="rc-refdocs__shell">
            <div className="rc-refdocs__pane-head">
              <h3 className="rc-refdocs__pane-title">
                {selected ? `${selected.code} sheets` : "Sheets"}
              </h3>
              {selected && canManage ? (
                <div className="rc-refdocs__pane-tools">
                  <Button
                    type="button"
                    label="Rename"
                    icon="pi pi-pencil"
                    size="small"
                    outlined
                    onClick={() => openRenameFolder(selected)}
                  />
                  <Button
                    type="button"
                    label="Delete"
                    icon="pi pi-trash"
                    size="small"
                    outlined
                    severity="danger"
                    onClick={() => confirmDeleteFolder(selected)}
                  />
                  <Button
                    type="button"
                    label="Add file"
                    icon="pi pi-plus"
                    size="small"
                    disabled={!selected || uploading}
                    onClick={openAddFile}
                  />
                </div>
              ) : null}
            </div>

            <div className="rc-refdocs__body">
              {!selected ? (
                <p className="rc-refdocs__empty">Select or create a category.</p>
              ) : (
                <div className="rc-refdocs__table-wrap">
                  <TableComponent
                    value={docs}
                    loading={loadingDocs}
                    columns={docColumns}
                    emptyMessage={`No PDFs in ${selected.code} yet.`}
                    paginator
                    rows={10}
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <Dialog
        header={selected ? `Add file — ${selected.code}` : "Add file"}
        visible={addFile.visible}
        style={{ width: "min(94vw, 36rem)" }}
        className="rc-refdocs-dialog rc-refdocs-dialog--add-file"
        modal
        dismissableMask
        onHide={() => !uploading && setAddFile(emptyAddFile())}
        footer={
          <div className="flex justify-content-end gap-2">
            <Button
              type="button"
              label="Cancel"
              size="small"
              outlined
              disabled={uploading}
              onClick={() => setAddFile(emptyAddFile())}
            />
            <Button
              type="button"
              label="Upload"
              icon="pi pi-upload"
              size="small"
              loading={uploading}
              disabled={uploading || !addFile.file}
              onClick={submitAddFile}
            />
          </div>
        }
      >
        <div className="rc-refdocs__add-form">
          <div
            className={`rc-refdocs__drop${addFile.dragOver ? " rc-refdocs__drop--active" : ""}${
              addFile.file ? " rc-refdocs__drop--filled" : ""
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setAddFile((s) => ({ ...s, dragOver: true }));
            }}
            onDragLeave={() => setAddFile((s) => ({ ...s, dragOver: false }))}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) applyAddFile(file);
              else setAddFile((s) => ({ ...s, dragOver: false }));
            }}
            onClick={() => addFileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                addFileInputRef.current?.click();
              }
            }}
          >
            <i className="pi pi-cloud-upload" aria-hidden />
            {addFile.file ? (
              <p>
                <strong>{addFile.file.name}</strong>
                <span className="rc-refdocs__drop-meta">
                  {" "}
                  · {formatBytes(addFile.file.size)} · click or drop to replace
                </span>
              </p>
            ) : (
              <p>
                Drag & drop a PDF here, or{" "}
                <span className="rc-refdocs__drop-link">browse</span>
              </p>
            )}
            <input
              ref={addFileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={onAddFileInputChange}
            />
          </div>

          <div className="rc-refdocs__field">
            <label htmlFor="ref-add-filename">Filename</label>
            <SafeInputText
              id="ref-add-filename"
              className="w-full"
              value={addFile.filename}
              placeholder={`${selected?.code || "PS"}200.pdf`}
              onChange={(e) => onAddFilenameChange(e.target.value)}
            />
            <p className="rc-refdocs__field-hint">
              Filename should be {selected?.code || "PS"}xxx.pdf in this format (e.g.{" "}
              {selected?.code || "PS"}200.pdf).
            </p>
            {addFile.file && !addFile.docCode ? (
              <p className="rc-refdocs__field-hint rc-refdocs__field-hint--warn">
                Current name does not match {selected?.code || "PS"}xxx.pdf
              </p>
            ) : null}
          </div>

          <div className="rc-refdocs__field">
            <label htmlFor="ref-add-version">Version</label>
            <SafeInputText
              id="ref-add-version"
              className="w-full"
              value={String(addFile.version)}
              readOnly
              title={
                addFile.docCode
                  ? docs.some(
                      (d) =>
                        String(d.docCode || "").toUpperCase() ===
                        String(addFile.docCode).toUpperCase(),
                    )
                    ? `Existing ${addFile.docCode} — next version`
                    : `New sheet ${addFile.docCode}`
                  : "Pick a file first"
              }
            />
            {addFile.file && addFile.docCode ? (
              <p className="rc-refdocs__field-hint">
                {addFile.version > 1
                  ? `${addFile.docCode} already exists — uploading as v${addFile.version}`
                  : `New sheet ${addFile.docCode} (v1)`}
              </p>
            ) : null}
          </div>
        </div>
      </Dialog>

      <Dialog
        header={folderDialog.mode === "create" ? "New category" : `Rename ${folderDialog.code}`}
        visible={folderDialog.visible}
        style={{ width: "min(92vw, 22rem)" }}
        className="rc-refdocs-dialog"
        modal
        dismissableMask
        onHide={() => setFolderDialog((d) => ({ ...d, visible: false }))}
        footer={
          <div className="flex justify-content-end gap-2">
            <Button
              type="button"
              label="Cancel"
              size="small"
              outlined
              onClick={() => setFolderDialog((d) => ({ ...d, visible: false }))}
            />
            <Button type="button" label="Save" size="small" onClick={saveFolder} />
          </div>
        }
      >
        {folderDialog.mode === "create" ? (
          <>
            <label className="block mb-1" style={{ fontSize: "0.8rem" }} htmlFor="ref-folder-code">
              Code (1–6 letters)
            </label>
            <SafeInputText
              id="ref-folder-code"
              className="w-full mb-2"
              value={folderDialog.code}
              onChange={(e) =>
                setFolderDialog((d) => ({ ...d, code: e.target.value.toUpperCase() }))
              }
              placeholder="PS"
              maxLength={6}
            />
          </>
        ) : null}
        <label className="block mb-1" style={{ fontSize: "0.8rem" }} htmlFor="ref-folder-name">
          Display name
        </label>
        <SafeInputText
          id="ref-folder-name"
          className="w-full"
          value={folderDialog.name}
          onChange={(e) => setFolderDialog((d) => ({ ...d, name: e.target.value }))}
          placeholder="Process Sheets"
        />
      </Dialog>

      <Dialog
        header={versionPickTitle()}
        visible={versionPick.visible}
        style={{ width: "min(94vw, 32rem)" }}
        className="rc-refdocs-dialog"
        modal
        dismissableMask
        onHide={() =>
          setVersionPick({ visible: false, action: null, doc: null, items: [], loading: false })
        }
      >
        {versionPick.loading ? (
          <p className="rc-refdocs__empty">Loading versions…</p>
        ) : (versionPick.items || []).length === 0 ? (
          <p className="rc-refdocs__empty">No versions found.</p>
        ) : (
          <>
            <p className="rc-refdocs__field-hint" style={{ marginBottom: "0.75rem" }}>
              This sheet has multiple versions. Choose one to continue.
            </p>
            <ul className="rc-refdocs__folder-list">
              {versionPick.items.map((v) => (
                <li key={v.id}>
                  <button
                    type="button"
                    className="rc-refdocs__folder-btn"
                    onClick={() => onPickVersion(v)}
                  >
                    <span>
                      <strong>v{v.versionNumber}</strong>
                      {v.originalFilename ? ` · ${v.originalFilename}` : ""}
                      {v.uploadedBy ? ` · ${v.uploadedBy}` : ""}
                      {v.versionNumber === versionPick.doc?.versionNumber ? " · latest" : ""}
                    </span>
                    <span className="rc-refdocs__folder-meta">{formatBytes(v.sizeBytes)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Dialog>

      <Dialog
        header={
          versionsDialog.doc
            ? `Versions — ${versionsDialog.doc.docCode}`
            : "Versions"
        }
        visible={versionsDialog.visible}
        style={{ width: "min(92vw, 28rem)" }}
        className="rc-refdocs-dialog"
        modal
        dismissableMask
        onHide={() =>
          setVersionsDialog({ visible: false, doc: null, items: [], loading: false })
        }
      >
        {versionsDialog.loading ? (
          <p className="rc-refdocs__empty">Loading…</p>
        ) : (versionsDialog.items || []).length === 0 ? (
          <p className="rc-refdocs__empty">No versions.</p>
        ) : (
          <ul className="rc-refdocs__folder-list">
            {versionsDialog.items.map((v) => (
              <li key={v.id} className="rc-refdocs__version-row">
                <button
                  type="button"
                  className="rc-refdocs__folder-btn"
                  onClick={() =>
                    openPreview(
                      {
                        ...versionsDialog.doc,
                        id: versionsDialog.doc.id,
                        originalFilename: v.originalFilename,
                      },
                      v.versionNumber,
                    )
                  }
                >
                  <span>
                    <strong>v{v.versionNumber}</strong>
                    {v.originalFilename ? ` · ${v.originalFilename}` : ""}
                    {v.uploadedBy ? ` · ${v.uploadedBy}` : ""}
                  </span>
                  <span className="rc-refdocs__folder-meta">{formatBytes(v.sizeBytes)}</span>
                </button>
                <Button
                  type="button"
                  icon="pi pi-download"
                  rounded
                  text
                  size="small"
                  aria-label={`Download v${v.versionNumber}`}
                  onClick={() =>
                    downloadDoc(
                      {
                        id: versionsDialog.doc.id,
                        originalFilename: v.originalFilename,
                        docCode: versionsDialog.doc.docCode,
                      },
                      v.versionNumber,
                    )
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </Dialog>

      <Dialog
        header={preview?.title || "PDF"}
        visible={Boolean(preview?.url)}
        style={{ width: "min(96vw, 56rem)" }}
        className="rc-refdocs-dialog"
        modal
        dismissableMask
        onHide={() => {
          if (preview?.url) URL.revokeObjectURL(preview.url);
          setPreview(null);
        }}
        footer={
          <div className="flex justify-content-end gap-2">
            <Button
              type="button"
              label="Download"
              icon="pi pi-download"
              size="small"
              outlined
              disabled={!preview?.documentId}
              onClick={() =>
                downloadDoc(
                  {
                    id: preview.documentId,
                    originalFilename: preview.filename,
                    docCode: preview.docCode,
                  },
                  preview.version,
                )
              }
            />
            <Button
              type="button"
              label="Close"
              size="small"
              onClick={() => {
                if (preview?.url) URL.revokeObjectURL(preview.url);
                setPreview(null);
              }}
            />
          </div>
        }
      >
        {preview?.url ? (
          <object
            data={preview.url}
            type="application/pdf"
            className="rc-refdocs__preview-frame"
            aria-label={preview.title}
          >
            <a href={preview.url} download={preview.filename || "sheet.pdf"}>
              Download PDF
            </a>
          </object>
        ) : null}
      </Dialog>
    </AppShell>
  );
}
