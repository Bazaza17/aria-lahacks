import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import prettier from "eslint-config-prettier/flat";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  // Turns off stylistic rules that would fight Prettier.
  prettier,
  {
    // React Compiler rules (eslint-plugin-react-hooks v6). Existing code in
    // BuildingScan and AgentActivity predates them; they're
    // warnings until those components are refactored and verified in-browser.
    // New code should not add to these warnings.
    rules: {
      "react-hooks/refs": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "test-results/**",
    "playwright-report/**",
  ]),
]);
