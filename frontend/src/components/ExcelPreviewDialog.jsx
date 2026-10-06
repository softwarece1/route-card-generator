import { useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { Message } from "primereact/message";
import { TabPanel, TabView } from "primereact/tabview";
import {
  EXCEL_PREVIEW_MAX_SHEETS,
  parseExcelPreview,
  triggerBlobDownload,
} from "@/lib/excelPreview";
import "./excel-preview-dialog.scss";

/**
 * View Excel (.xls / .xlsx) in-app: up to 5 sheets, table grid + download original.
 *
 * props:
 *  - visible, onHide
 *  - blob: Blob | null
 *  - filename: string
 */
export default function ExcelPreviewDialog({ visible, onHide, blob, filename }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(null);
  const [activeTab, setActiveTab] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!visible || !blob) {
      setPreview(null);
      setError("");
      setActiveTab(0);
      return undefined;
    }
    setLoading(true);
    setError("");
    parseExcelPreview(blob, { maxSheets: EXCEL_PREVIEW_MAX_SHEETS })
      .then((parsed) => {
        if (!cancelled) {
          setPreview(parsed);
          setActiveTab(0);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setPreview(null);
          setError(e.message || "Could not read Excel file");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, blob]);

  const footer = useMemo(
    () => (
      <div className="rc-excel-preview__footer">
        <Button
          type="button"
          label="Download"
          icon="pi pi-download"
          outlined
          disabled={!blob}
          onClick={() => blob && triggerBlobDownload(blob, filename || "workbook.xlsx")}
        />
        <Button type="button" label="Close" icon="pi pi-times" onClick={onHide} />
      </div>
    ),
    [blob, filename, onHide],
  );

  return (
    <Dialog
      header={filename ? `Excel — ${filename}` : "Excel preview"}
      visible={visible}
      onHide={onHide}
      style={{ width: "min(96vw, 72rem)" }}
      maximizable
      className="rc-excel-preview-dialog"
      footer={footer}
    >
      {loading ? (
        <p className="rc-excel-preview__hint">
          <i className="pi pi-spin pi-spinner" /> Reading workbook…
        </p>
      ) : null}
      {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}
      {preview ? (
        <div className="rc-excel-preview">
          {preview.truncatedSheets ? (
            <Message
              severity="warn"
              className="w-full mb-3"
              text={`Showing first ${preview.sheetNames.length} of ${preview.totalSheets} sheets (max ${EXCEL_PREVIEW_MAX_SHEETS}). Download the file to open all sheets in Excel.`}
            />
          ) : (
            <p className="rc-excel-preview__hint">
              {preview.sheetNames.length} sheet
              {preview.sheetNames.length === 1 ? "" : "s"} · up to {preview.maxRows} rows each
            </p>
          )}
          <TabView activeIndex={activeTab} onTabChange={(e) => setActiveTab(e.index)}>
            {preview.sheetNames.map((name) => {
              const sheet = preview.sheets[name] || { columns: [], rows: [] };
              return (
                <TabPanel key={name} header={name}>
                  <DataTable
                    value={sheet.rows}
                    size="small"
                    scrollable
                    scrollHeight="55vh"
                    emptyMessage="This sheet has no rows."
                    className="rc-excel-preview__table"
                    dataKey="__rowKey"
                  >
                    {sheet.columns.map((col) => (
                      <Column
                        key={col.field}
                        field={col.field}
                        header={col.header}
                        style={{ minWidth: "7rem" }}
                      />
                    ))}
                  </DataTable>
                </TabPanel>
              );
            })}
          </TabView>
        </div>
      ) : null}
    </Dialog>
  );
}
