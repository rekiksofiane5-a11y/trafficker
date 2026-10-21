// Version 100 % navigateur : le Worker se contente de servir les fichiers statiques
// (page, moteur Python pour Pyodide). Aucun traitement de données côté serveur.
export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request);
  },
};
