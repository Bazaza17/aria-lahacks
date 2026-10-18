import * as Sentry from "@sentry/nextjs";

// No DSN means Sentry stays off. SDK v11 removed sendDefaultPii and enableLogs;
// PII collection and Logs are on by default.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "laptop",
  tracesSampleRate: 1.0,
});
