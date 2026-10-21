// Moteur Trafficker exécuté dans un Web Worker : Pyodide et l'analyse tournent hors du
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
  analyze: async ({name, bytes, camp, adv, nomen, creas}) => {
    const stamp = Date.now();
    const dir = `/tmp/up_${stamp}`, cdir = `/tmp/creas_${stamp}`;
    py.FS.mkdirTree(dir);
    py.FS.mkdirTree(cdir);
    const path = dir + "/" + name.replace(/[\/\\]/g, "_");
    py.FS.writeFile(path, new Uint8Array(bytes));
    for (const f of creas) py.FS.writeFile(cdir + "/" + f.name.replace(/[\/\\]/g, "_"), new Uint8Array(f.bytes));
    return api.analyze(path, camp, adv, nomen, cdir);
  },
  run_demo: async () => api.run_demo(),
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
