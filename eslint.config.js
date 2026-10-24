// Lint JavaScript (CI : npx eslint .) : page (scripts inline de index.html), modules web, Worker, tests Node
import html from "eslint-plugin-html";
import globals from "globals";

export default [
  {ignores: ["node_modules/", "web/dist/", "web/wheels/"]},
  {
    files: ["**/*.js", "**/*.mjs", "**/*.html"],
    plugins: {html},
    languageOptions: {ecmaVersion: 2024, sourceType: "module", globals: {...globals.browser, ...globals.node, ...globals.worker}},
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", {args: "none", caughtErrors: "none", varsIgnorePattern: "^_"}],
      "no-redeclare": "error",            // deux fonctions de même nom dans la page
      "no-dupe-keys": "error",
      "no-unreachable": "error",
      "no-constant-condition": ["error", {checkLoops: false}],
      "eqeqeq": ["error", "smart"],
    },
  },
  {
    // la page est un script classique (pas un module) : ses fonctions sont globales
    files: ["web/index.html"],
    languageOptions: {sourceType: "script", globals: {UQ: "readonly", CMPrompt: "readonly", Pivot: "readonly"}},
  },
];
