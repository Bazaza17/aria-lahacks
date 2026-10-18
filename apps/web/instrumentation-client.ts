import * as Sentry from "@sentry/nextjs";

// Origin of the FastAPI backend, so browser traces continue into it (its CORS
// allows the sentry-trace and baggage headers).
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").match(
  /^https?:\/\/[^/]+/,
)?.[0];
// /^\// keeps same-origin requests to the Next server traced on the deployed site.
const TRACE_TARGETS: (string | RegExp)[] = [
  "localhost",
  /^\//,
  ...(API_ORIGIN ? [API_ORIGIN] : []),
];

// No DSN means Sentry stays off: no integrations are set up and nothing is sent.
// SDK v11 removed sendDefaultPii and enableLogs; PII collection and Logs are on by default.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "laptop",
  tracesSampleRate: 1.0,
  tracePropagationTargets: TRACE_TARGETS,
  integrations: [
    // No user data in this app, and readable replays are the evidence we want.
    Sentry.replayIntegration({ maskAllText: false, blockAllMedia: false }),
  ],
  replaysSessionSampleRate: 1.0,
  replaysOnErrorSampleRate: 1.0,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
