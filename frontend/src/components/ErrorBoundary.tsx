import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Carivyo interface failure", {
      name: error.name,
      componentStack: info.componentStack
    });
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <main id="main-content" className="boot-screen" role="alert">
        <AlertTriangle aria-hidden="true" />
        <h1>This page could not finish rendering</h1>
        <p>Your local data was not changed. Reload Carivyo to restore the workspace.</p>
        <button className="button button--primary" type="button" onClick={() => window.location.reload()}>
          <RefreshCw aria-hidden="true" /> Reload workspace
        </button>
      </main>
    );
  }
}
