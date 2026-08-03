import { useEffect, type ReactNode } from "react";
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
      modelName: "Core mode"
    };
  }
  return {
    ready: true,
    providerName: runtime.selection.fully_local ? "Local only" : provider.name,
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

  useEffect(() => {
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [page]);

  return (
    <div className="app-shell">
      <div className="product-orbit" aria-hidden="true" />
      <header className="product-nav">
        <button
          className="product-nav__brand"
          type="button"
          onClick={() => onPageChange("jobs")}
          aria-label="Carivyo home"
        >
          <span className="brand-mark" aria-hidden="true"><span /></span>
          <span>CARIVYO</span>
        </button>

        <nav className="product-nav__links" aria-label="Primary navigation">
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

        <div className="product-nav__actions">
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
        </div>
      </header>

      <div className="workspace">
        <main id="main-content" className="page-content">
          {children}
        </main>
      </div>
    </div>
  );
}
