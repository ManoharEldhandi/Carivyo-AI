import type { ReactNode } from "react";
import {
  BriefcaseBusiness,
  Command,
  Cpu,
  Search,
  Sparkles,
  UserRound
} from "lucide-react";
import type { Page, RuntimeState } from "../types";

interface Props {
  page: Page;
  onPageChange: (page: Page) => void;
  onOpenChat: () => void;
  runtime: RuntimeState;
  children: ReactNode;
}

const navigation: Array<{
  id: Exclude<Page, "chat">;
  label: string;
  icon: typeof Search;
}> = [
  { id: "jobs", label: "Jobs", icon: Search },
  { id: "applications", label: "Applications", icon: BriefcaseBusiness },
  { id: "profile", label: "Profile", icon: UserRound }
];

export function runtimeDisplay(runtime: RuntimeState) {
  const provider = runtime.providers.find(
    (item) => item.id === runtime.selection.provider && item.available
  );
  const model = provider?.models?.find(
    (item) => item.id === runtime.selection.model
  );
  if (!provider || !model) {
    return {
      ready: false,
      providerName: "AI off",
      modelName: "Deterministic features"
    };
  }
  return {
    ready: true,
    providerName: provider.name,
    modelName: model.name
  };
}

export function Shell({
  page,
  onPageChange,
  onOpenChat,
  runtime,
  children
}: Props) {
  const processing = runtimeDisplay(runtime);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="sidebar__brand">
          <span className="brand-mark" aria-hidden="true">C</span>
          <div>
            <strong>Carivyo</strong>
            <span>Jobs and resumes</span>
          </div>
        </div>

        <nav>
          <span className="sidebar__section-label">Workspace</span>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`nav-item ${page === id ? "nav-item--active" : ""}`}
              aria-current={page === id ? "page" : undefined}
              onClick={() => onPageChange(id)}
            >
              <Icon aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>

      </aside>

      <div className="workspace">
        <header className="topbar">
          <button className="command-bar" type="button" onClick={onOpenChat}>
            <Sparkles aria-hidden="true" />
            <span>Ask Carivyo</span>
            <kbd><Command aria-hidden="true" /> K</kbd>
          </button>
          <div className="topbar__status">
            <span
              className={`runtime-pill ${processing.ready ? "is-ready" : ""}`}
              title="Selected AI provider and model"
            >
              <Cpu aria-hidden="true" />
              <span>{processing.providerName}</span>
              <strong>{processing.modelName}</strong>
            </span>
          </div>
        </header>
        <main id="main-content" className="page-content">
          {children}
        </main>
      </div>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={page === id ? "is-active" : ""}
            aria-current={page === id ? "page" : undefined}
            onClick={() => onPageChange(id)}
          >
            <Icon aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
