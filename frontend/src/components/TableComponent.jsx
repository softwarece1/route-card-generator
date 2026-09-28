import React from "react";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import "./table-component.scss";

/** Status pill with leading dot — matches reference table badges. */
export function TableStatusBadge({ value, tone = "neutral" }) {
  const text = value == null || value === "" ? "—" : String(value);
  return (
    <span className={`rc-table-badge rc-table-badge--${tone}`}>
      <span className="rc-table-badge__dot" aria-hidden />
      {text}
    </span>
  );
}

/** Light file/doc chip. */
export function TableFileChip({ label, onClick, title }) {
  if (!label) return <span className="rc-table-muted">—</span>;
  const Tag = onClick ? "button" : "span";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      className={`rc-table-filechip${onClick ? " rc-table-filechip--btn" : ""}`}
      onClick={onClick}
      title={title || (typeof label === "string" ? label : undefined)}
    >
      <i className="pi pi-file" aria-hidden />
      <span>{label}</span>
    </Tag>
  );
}

/** Bold primary + muted subtitle stack (Session / Employee style). */
export function TablePrimarySub({ primary, secondary }) {
  return (
    <span className="rc-table-primary-sub">
      <span className="rc-table-primary-sub__primary">{primary || "—"}</span>
      {secondary ? (
        <span className="rc-table-primary-sub__secondary">{secondary}</span>
      ) : null}
    </span>
  );
}

/** Icon action cluster (rounded bordered buttons). */
export function TableActions({ children }) {
  return <div className="rc-table-actions">{children}</div>;
}

/**
 * Reusable page table — PrimeReact DataTable with shared chrome.
 * No row selection / checkbox column.
 *
 * columns: {
 *   field?, header, sortable?, style?, className?, body?,
 *   type?: 'index' | 'status' | 'files' | 'primarySub' | 'actions' | 'text',
 *   statusTone?: (row) => string,
 *   filesLabel?: (row) => string,
 *   primary?: (row) => node, secondary?: (row) => node,
 * }
 */
export default function TableComponent({
  value = [],
  columns = [],
  loading = false,
  dataKey = "id",
  paginator = true,
  rows = 10,
  rowsPerPageOptions,
  pageLinkSize,
  emptyMessage = "No records found.",
  className = "",
  size = "normal",
  sortMode = "single",
  ...rest
}) {
  const bodyFor = (col) => {
    if (typeof col.body === "function") return col.body;

    if (col.type === "index") {
      return (_row, { rowIndex }) => (
        <span className="rc-table-index">{rowIndex + 1}</span>
      );
    }

    if (col.type === "status") {
      return (row) => (
        <TableStatusBadge
          value={col.field ? row[col.field] : col.value?.(row)}
          tone={col.statusTone ? col.statusTone(row) : "neutral"}
        />
      );
    }

    if (col.type === "files") {
      return (row) => (
        <TableFileChip
          label={col.filesLabel ? col.filesLabel(row) : col.field ? row[col.field] : ""}
          onClick={col.onFileClick ? () => col.onFileClick(row) : undefined}
        />
      );
    }

    if (col.type === "primarySub") {
      return (row) => (
        <TablePrimarySub
          primary={col.primary ? col.primary(row) : col.field ? row[col.field] : ""}
          secondary={col.secondary ? col.secondary(row) : ""}
        />
      );
    }

    if (col.type === "actions") {
      return (row) => <TableActions>{col.renderActions?.(row)}</TableActions>;
    }

    return undefined;
  };

  const totalRows = Array.isArray(value) ? value.length : 0;
  const pageSize = Number(rows) > 0 ? Number(rows) : 10;
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  // Show every page link (Prime default is 5, which hid pages 6–7 for 63 rows)
  const resolvedPageLinkSize =
    pageLinkSize != null ? pageLinkSize : Math.max(totalPages, 5);

  return (
    <div className={`rc-table ${className}`.trim()}>
      <DataTable
        value={value}
        loading={loading}
        dataKey={dataKey}
        paginator={paginator}
        rows={pageSize}
        rowsPerPageOptions={rowsPerPageOptions}
        pageLinkSize={resolvedPageLinkSize}
        emptyMessage={emptyMessage}
        size={size === "normal" ? undefined : size}
        sortMode={sortMode}
        className="rc-table__dt"
        paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink"
        currentPageReportTemplate="Showing {first}-{last} of {totalRecords} entries"
        {...rest}
      >
        {columns.map((col, i) => (
          <Column
            key={col.key || col.field || col.header || i}
            field={col.field}
            header={col.header}
            sortable={Boolean(col.sortable)}
            style={col.style}
            className={col.className}
            body={bodyFor(col)}
            headerClassName={col.headerClassName}
          />
        ))}
      </DataTable>
    </div>
  );
}
