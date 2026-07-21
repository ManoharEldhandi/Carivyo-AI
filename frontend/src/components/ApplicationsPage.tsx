import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  CalendarClock,
  CheckCircle2,
  LoaderCircle,
  MapPin
} from "lucide-react";
import { api } from "../api";
import type { ApplicationRecord } from "../types";

export function ApplicationsPage() {
  const [applications, setApplications] = useState<ApplicationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      const response = await api.applications();
      setApplications(response.applications);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Applications could not load.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function update(application: ApplicationRecord, status: string) {
    try {
      await api.updateApplication(application.id, status);
      setNotice(
        status === "applied"
          ? "Application marked submitted by you."
          : `Application moved to ${status}.`
      );
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Application status was not saved.");
    }
  }

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">User-controlled progress</p>
          <h1>Applications</h1>
          <p>
            Opening an official form never counts as submission. You control every
            status transition here.
          </p>
        </div>
      </section>

      <section className="metric-strip" aria-label="Application summary">
        <div>
          <BriefcaseBusiness aria-hidden="true" />
          <span>
            <strong>{applications.length}</strong>
            tracked roles
          </span>
        </div>
        <div>
          <CheckCircle2 aria-hidden="true" />
          <span>
            <strong>
              {applications.filter((application) => application.status === "applied").length}
            </strong>
            submitted by you
          </span>
        </div>
        <div>
          <CalendarClock aria-hidden="true" />
          <span>
            <strong>
              {applications.filter((application) => application.status === "interview").length}
            </strong>
            interviews
          </span>
        </div>
      </section>

      {error ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="inline-notice" role="status">
          {notice}
        </div>
      ) : null}

      {loading ? (
        <div className="loading-panel">
          <LoaderCircle className="spin" aria-hidden="true" /> Loading applications…
        </div>
      ) : applications.length ? (
        <div className="application-list">
          {applications.map((application) => (
            <article className="application-card" key={application.id}>
              <div>
                <span className={`application-status application-status--${application.status}`}>
                  {application.status}
                </span>
                <h2>{application.title}</h2>
                <p>{application.company}</p>
                <span className="application-location">
                  <MapPin aria-hidden="true" /> {application.location}
                </span>
              </div>
              <div className="application-card__controls">
                <label>
                  <span>Current status</span>
                  <select
                    value={application.status}
                    onChange={(event) => void update(application, event.target.value)}
                    disabled={!application.allowed_transitions.length}
                  >
                    {[application.status, ...application.allowed_transitions].map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </label>
                <a
                  className="button button--secondary"
                  href={application.apply_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Official form <ArrowUpRight aria-hidden="true" />
                </a>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <BriefcaseBusiness aria-hidden="true" />
          <h2>No applications yet</h2>
          <p>Choose Apply on a verified job to prepare and track it here.</p>
        </div>
      )}
    </>
  );
}
