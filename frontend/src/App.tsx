import { Suspense, lazy, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RouteLoadingFallback } from "./components/PageState";

const HomePage = lazy(async () => ({
  default: (await import("./pages/HomePage")).HomePage,
}));
const SessionsPage = lazy(async () => ({
  default: (await import("./pages/SessionsPage")).SessionsPage,
}));
const SessionDetailPage = lazy(async () => ({
  default: (await import("./pages/SessionDetailPage")).SessionDetailPage,
}));
const LapReviewPage = lazy(async () => ({
  default: (await import("./pages/LapReviewPage")).LapReviewPage,
}));
const LapComparePage = lazy(async () => ({
  default: (await import("./pages/LapComparePage")).LapComparePage,
}));

function RouteElement({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteLoadingFallback />}>{children}</Suspense>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route
            path="/"
            element={
              <RouteElement>
                <HomePage />
              </RouteElement>
            }
          />
          <Route
            path="/sessions"
            element={
              <RouteElement>
                <SessionsPage />
              </RouteElement>
            }
          />
          <Route
            path="/sessions/:sessionId"
            element={
              <RouteElement>
                <SessionDetailPage />
              </RouteElement>
            }
          />
          <Route
            path="/sessions/:sessionId/laps/:lapNumber"
            element={
              <RouteElement>
                <LapReviewPage />
              </RouteElement>
            }
          />
          <Route
            path="/compare/laps"
            element={
              <RouteElement>
                <LapComparePage />
              </RouteElement>
            }
          />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
