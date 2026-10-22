// Moteur Umnia exécuté dans un Web Worker : Pyodide et l'analyse tournent hors du
// fil principal, la page reste réactive même sur un gros classeur.
"use strict";
importScripts("pyodide/pyodide.js");

let py = null, api = null;
const APP = "/home/pyodide/app";

async function boot() {
  py = await loadPyodide({indexURL: new URL("pyodide/", self.location.href).href});
  const manifest = await (await fetch("py/manifest.json", {cache: "no-store"})).json();
  const v = "?v=" + manifest.version;
  const get = async (url) => new Uint8Array(await (await fetch(url)).arrayBuffer());
  for (const w of manifest.wheels) py.unpackArchive((await get("wheels/" + w)).buffer, "wheel");
  py.FS.mkdirTree(APP + "/templates");
  py.FS.mkdirTree(APP + "/specs");
  for (const s of manifest.specs) py.FS.writeFile(APP + "/specs/" + s, await get("py/specs/" + s + v));
  for (const m of manifest.modules) py.FS.writeFile(APP + "/" + m, await get("py/" + m + v));
  for (const t of manifest.templates) py.FS.writeFile(APP + "/templates/" + t, await get("py/templates/" + t + v));
  py.runPython(`import sys; sys.path.insert(0, "${APP}")`);
  api = py.pyimport("web_api");
  return manifest.version;
}
const ready = boot();

function bytesOf(proxy) {
  const b = proxy.toJs();
  proxy.destroy();
  return b;
}

const COMMANDS = {
  version: async () => ready,
  analyze: async ({name, bytes, camp, adv, nomen, creas, instructions}) => {
    const stamp = Date.now();
    const dir = `/tmp/up_${stamp}`, cdir = `/tmp/creas_${stamp}`;
    py.FS.mkdirTree(dir);
    py.FS.mkdirTree(cdir);
    const path = dir + "/" + name.replace(/[\/\\]/g, "_");
    py.FS.writeFile(path, new Uint8Array(bytes));
    for (const f of creas) py.FS.writeFile(cdir + "/" + f.name.replace(/[\/\\]/g, "_"), new Uint8Array(f.bytes));
    return api.analyze(path, camp, adv, nomen, cdir, instructions || "");
  },
  rebuild: async ({table}) => api.rebuild(JSON.stringify(table)),
  restore: async ({table, nomen}) => api.restore(JSON.stringify(table), nomen || ""),
  run_demo: async () => api.run_demo(),
  // Reporting : objets JSON (campagne, emplacements, diffusion) -> templates
  report_demo: async ({campaign, placements, today}) =>
    api.report_demo(JSON.stringify(campaign), JSON.stringify(placements), today),
  report_parse: async ({name, bytes, campaign}) => {
    const path = `/tmp/export_${Date.now()}_` + name.replace(/[\/\\]/g, "_");
    py.FS.writeFile(path, new Uint8Array(bytes));
    return api.report_parse(path, campaign || "");
  },
  plan_targets: async ({table, nomen, source}) => api.plan_targets(JSON.stringify(table), nomen || "", source || ""),
  report_check: async ({campaign, placements, delivery, today, targets}) =>
    api.report_check(JSON.stringify(campaign), JSON.stringify(placements), JSON.stringify(delivery), today,
                     targets ? JSON.stringify(targets) : ""),
  report_regie: async ({campaign, placements, delivery, site}) =>
    api.report_regie(JSON.stringify(campaign), JSON.stringify(placements), JSON.stringify(delivery), site),
  export_report_check: async ({campaign, placements, delivery, today, targets}) =>
    bytesOf(api.export_report_check(JSON.stringify(campaign), JSON.stringify(placements), JSON.stringify(delivery), today,
                                    targets ? JSON.stringify(targets) : "")),
  export_report_regie: async ({campaign, placements, delivery, site, today}) =>
    bytesOf(api.export_report_regie(JSON.stringify(campaign), JSON.stringify(placements), JSON.stringify(delivery), site, today)),
  delivery_demo: async () => api.delivery_demo(),
  export_cm360: async () => bytesOf(api.export_cm360()),
  export_adform: async ({type}) => bytesOf(api.export_adform(type)),
};

self.onmessage = async (e) => {
  const {id, cmd, args} = e.data;
  try {
    await ready;
    const result = await COMMANDS[cmd](args || {});
    const transfer = result instanceof Uint8Array ? [result.buffer] : [];
    self.postMessage({id, ok: true, result}, transfer);
  } catch (err) {
    self.postMessage({id, ok: false, error: String((err && err.message) || err)});
  }
};
ready.catch((err) => self.postMessage({id: 0, ok: false, error: String((err && err.message) || err)}));
