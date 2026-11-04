"use client";

import Link from "next/link";
import { useState } from "react";
import { signIn, signOut } from "next-auth/react";
import { left, type Doc, type Limits } from "@/lib/api";
import { docSource, docTitle } from "@/lib/title";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import { SignInButton } from "./SignInButton";
import { ThemeToggle } from "./ThemeToggle";

export type Banner = { text: string; kind: "info" | "bad" } | null;

type Props = {
  docs: Doc[];
  limits: Limits | null;
  selected: Set<string>;
  open: boolean;
  loaded: boolean;
  uploading: boolean;
  banner: Banner;
  onToggle: (id: string) => void;
  onClearSelection: () => void;
  onView: (doc: Doc) => void;
  onDelete: (doc: Doc) => void;
  onUpload: (file: File | undefined) => void;
  onDeleteAccount: () => void;
  onClose: () => void;
};

export function Library(p: Props) {
  const { docs, limits } = p;
  const [over, setOver] = useState(false);
  const uploadOff = !limits?.uploads_enabled;
  const uploadsLeft = limits ? left(limits.uploads) : Infinity;
  const blocked = uploadOff || p.uploading || uploadsLeft === 0;
  const docPct = limits?.documents.limit ? Math.min(100, (limits.documents.used / limits.documents.limit) * 100) : 0;

  return (
    <nav id="library" className="rail" data-open={p.open} aria-label="Documents">
      <div className="rail-top">
        <Logo />
        <span style={{ display: "flex", gap: 2 }}>
          <ThemeToggle />
          <button type="button" className="icon-btn rail-close" onClick={p.onClose} aria-label="Close library">
            <Icon name="x" />
          </button>
        </span>
      </div>

      <div className="rail-lib">
        <div className="rail-head">
          <h2>Library · {docs.length}</h2>
          {p.selected.size > 0 && (
            <button type="button" className="btn-text" onClick={p.onClearSelection}>
              Clear selection
            </button>
          )}
        </div>
        {p.loaded && docs.length === 0 && <p className="empty-lib">No documents yet. Add a PDF below.</p>}
        <ul className="docs">
          {docs.map((d) => {
            const on = p.selected.has(d.id);
            const meta = docSource(d.filename) ?? (d.sample ? "Sample" : "Yours");
            return (
              <li key={d.id} className={on ? "doc on" : "doc"}>
                <label>
                  <input type="checkbox" checked={on} onChange={() => p.onToggle(d.id)} />
                  <span className="box" aria-hidden="true">
                    <Icon name="check" />
                  </span>
                  <span>
                    <span className="t" title={d.filename} style={{ display: "block" }}>
                      {docTitle(d.filename)}
                    </span>
                    <span className="s">
                      {meta} · {d.pages} {d.pages === 1 ? "page" : "pages"}
                    </span>
                  </span>
                </label>
                <span className="acts">
                  <button type="button" className="icon-btn sm" onClick={() => p.onView(d)} aria-label={`View ${docTitle(d.filename)}`}>
                    <Icon name="eye" />
                  </button>
                  {limits?.uploads_enabled && !d.sample && (
                    <button type="button" className="icon-btn sm" onClick={() => p.onDelete(d)} aria-label={`Delete ${docTitle(d.filename)}`}>
                      <Icon name="trash" />
                    </button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        {docs.length > 1 && (
          <p className="muted small" style={{ padding: "8px 8px 0" }}>
            {p.selected.size ? `Searching ${p.selected.size} selected.` : "Searching all documents."} Tick documents to narrow it.
          </p>
        )}
      </div>

      <div
        className={`drop${over ? " over" : ""}${blocked ? " off" : ""}`}
        onDragOver={(e) => {
          if (blocked) return;
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!blocked) p.onUpload(e.dataTransfer.files?.[0]);
        }}
      >
        <label>
          <input
            type="file"
            accept="application/pdf,.pdf"
            disabled={blocked}
            onChange={(e) => {
              p.onUpload(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Icon name="up" />
          {p.uploading ? "Reading the PDF…" : "Add a PDF"}
        </label>
        {limits?.region_blocked ? (
          <span className="muted small">
            Uploads are not available in your region. <Link href="/privacy">Why?</Link>
          </span>
        ) : limits && !limits.uploads_enabled ? (
          <span className="muted small">{limits.signed_in ? "Uploads are turned off on this server." : "Sign in to upload your own PDFs."}</span>
        ) : limits ? (
          <>
            <span className="muted small">
              Drop a file here or browse. Up to {limits.max_upload_mb} MB
              {limits.max_upload_chunks ? `, about ${limits.max_upload_chunks} sections` : ""}.
              {Number.isFinite(uploadsLeft) && ` ${uploadsLeft} upload${uploadsLeft === 1 ? "" : "s"} left today.`}{" "}
              Text is sent to Google and Groq to answer questions, so upload only what you are fine sharing.{" "}
              <Link href="/privacy">Privacy</Link>
            </span>
            {limits.documents.limit ? (
              <>
                <div className="meter" role="img" aria-label={`${limits.documents.used} of ${limits.documents.limit} documents used`}>
                  <i style={{ width: `${docPct}%` }} />
                </div>
                <span className="muted small">
                  {limits.documents.used} of {limits.documents.limit} documents · {limits.storage_mb.used} of {limits.storage_mb.limit} MB
                </span>
              </>
            ) : null}
          </>
        ) : null}
      </div>
      {p.banner && (
        <p className={`notice ${p.banner.kind}`} role={p.banner.kind === "bad" ? "alert" : "status"}>
          {p.banner.text}
        </p>
      )}

      <div className="account">
        {limits && !limits.signed_in && (
          <>
            <SignInButton className="btn btn-primary" icon={false}>
              Sign in with Google
            </SignInButton>
            {process.env.NODE_ENV === "development" && (
              <button type="button" className="btn-text" onClick={() => signIn("dev", { redirect: false }).then(() => location.reload())}>
                dev login
              </button>
            )}
            <span>
              Samples work without an account. Sign in to upload PDFs only you can see. <Link href="/privacy">Privacy</Link>
            </span>
          </>
        )}
        {limits?.signed_in && (
          <>
            <span>Signed in</span>
            <span className="row">
              <button type="button" className="btn-text" onClick={() => signOut({ redirect: false }).then(() => location.reload())}>
                Sign out
              </button>
              <button type="button" className="btn-text danger" onClick={p.onDeleteAccount}>
                Delete my data
              </button>
            </span>
          </>
        )}
      </div>
    </nav>
  );
}
