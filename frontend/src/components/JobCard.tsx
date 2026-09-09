import {
  Bookmark,
  BookmarkCheck,
  Building2,
  ChevronRight,
  Clock3,
  MapPin,
  ShieldCheck
} from "lucide-react";
import type { Job } from "../types";

interface Props {
  job: Job;
  onSelect: (job: Job) => void;
  onFeedback: (job: Job, action: "save" | "hide") => void;
  busyAction?: string;
}

export function JobCard({ job, onSelect, onFeedback, busyAction }: Props) {
  const saved = job.latest_feedback === "save";
  const saveBusy = busyAction === `save-${job.id}`;
  const workMode = job.work_mode
    ? job.work_mode.charAt(0).toUpperCase() + job.work_mode.slice(1)
    : "Work mode not listed";

  return (
    <article className="job-card">
      <div className="job-card__content">
        <header className="job-card__header">
          <div className="job-card__identity">
            <h3>{job.title}</h3>
            <p className="company-line">
              <Building2 aria-hidden="true" /> {job.company}
            </p>
          </div>
          <span className={`fit-label fit-label--${job.tier}`}>
            {job.tier} fit
          </span>
        </header>

        <div className="job-meta" role="group" aria-label="Job summary">
          <span><MapPin aria-hidden="true" /> {job.location} · {workMode}</span>
          <span><Clock3 aria-hidden="true" /> {postedLabel(job.posted_at)}</span>
          <span className={`freshness-badge freshness-badge--${job.freshness_class}`}>
            {freshnessLabel(job.freshness_class)}
          </span>
          <span><ShieldCheck aria-hidden="true" /> Official {job.source_family}</span>
          <span><ShieldCheck aria-hidden="true" /> {verificationLabel(job.verified_at)}</span>
        </div>

        {job.reasons[0] ? (
          <p className="job-signal">
            <strong>Why this job</strong>
            <span>{job.reasons[0].text}</span>
          </p>
        ) : null}
        {job.risks[0] ? (
          <p className="job-signal job-signal--risk">
            <strong>Check</strong>
            <span>{job.risks[0]}</span>
          </p>
        ) : null}
        {!job.reasons[0] && !job.risks[0] ? (
          <p className="job-signal job-signal--muted">
            No match explanation was returned for this role.
          </p>
        ) : null}
      </div>

      <div className="job-card__actions" role="group" aria-label={`Actions for ${job.title}`}>
        <button
          className="button button--secondary job-card__detail-button"
          type="button"
          onClick={() => onSelect(job)}
        >
          View details <ChevronRight aria-hidden="true" />
        </button>
        <button
          className={`button button--quiet save-button ${saved ? "is-saved" : ""}`}
          type="button"
          aria-label={`${saved ? "Saved" : "Save"} ${job.title}`}
          aria-pressed={saved}
          onClick={() => onFeedback(job, "save")}
          disabled={saveBusy}
        >
          {saved ? <BookmarkCheck aria-hidden="true" /> : <Bookmark aria-hidden="true" />}
          {saved ? "Saved" : "Save"}
        </button>
      </div>
    </article>
  );
}

export function freshnessLabel(value: string) {
  return {
    verified_24h: "≤24h",
    verified_48h: "≤48h",
    live_date_unverified: "Date unverified",
    older_live: "Older",
    uncertain: "Needs recheck",
    closed: "Closed"
  }[value] ?? value.replaceAll("_", " ");
}

export function postedLabel(value?: string) {
  if (!value) return "Posted date unavailable";
  const date = parseUtcTimestamp(value);
  if (Number.isNaN(date.getTime())) return "Posted date unavailable";
  return `Posted ${new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric"
  }).format(date)}`;
}

export function verificationLabel(value?: string) {
  if (!value) return "Verification time unavailable";
  const checked = parseUtcTimestamp(value);
  if (Number.isNaN(checked.getTime())) return "Verification time unavailable";
  const minutes = Math.max(0, Math.round((Date.now() - checked.getTime()) / 60_000));
  if (minutes < 2) return "Verified just now";
  if (minutes < 60) return `Verified ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Verified ${hours}h ago`;
  return `Verified ${new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric"
  }).format(checked)}`;
}

export function parseUtcTimestamp(value: string) {
  const normalized = value.trim().replace(/^(\d{4}-\d{2}-\d{2})\s/, "$1T");
  if (!normalized) return new Date(Number.NaN);
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    return new Date(`${normalized}T00:00:00Z`);
  }
  const hasExplicitTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  return new Date(hasExplicitTimezone ? normalized : `${normalized}Z`);
}
