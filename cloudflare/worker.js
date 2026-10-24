// Point d'entrée Cloudflare : toutes les requêtes du navigateur sont transmises au
// conteneur Python (UI Agopis). HTTPS est assuré par Cloudflare.
import { Container } from "@cloudflare/containers";

export class TraffickerContainer extends Container {
  defaultPort = 8000;
  // Arrêt après 30 min sans activité (redémarrage automatique à la requête suivante)
  sleepAfter = "30m";

  constructor(ctx, env) {
    super(ctx, env);
    // Secrets Cloudflare (wrangler secret put ...) -> variables du conteneur
    this.envVars = {
      TRAFFICKER_PASSWORD_HASH: env.TRAFFICKER_PASSWORD_HASH || "",
      TRAFFICKER_PASSWORD: env.TRAFFICKER_PASSWORD || "",
      // Sans clé fournie, l'UI en tire une au hasard (sessions perdues au redémarrage)
      TRAFFICKER_SECRET_KEY: env.TRAFFICKER_SECRET_KEY || "",
      TRAFFICKER_USER: env.TRAFFICKER_USER || "admin",
      TRAFFICKER_SECURE_COOKIE: "1",
      TRAFFICKER_TRUST_CF: "1",
      TRAFFICKER_WORKERS: "2",
    };
  }
}

export default {
  async fetch(request, env) {
    // Refus explicite si le mot de passe n'est pas configuré : jamais d'UI ouverte en ligne
    if (!env.TRAFFICKER_PASSWORD && !env.TRAFFICKER_PASSWORD_HASH) {
      return new Response(
        "Agopis : ajoutez le secret TRAFFICKER_PASSWORD (Cloudflare > Worker > Settings > " +
          "Variables and Secrets, type Secret), puis redéployez.",
        { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    // Une seule instance : l'état (SQLite) vit dans ce conteneur
    return env.TRAFFICKER.getByName("main").fetch(request);
  },
};
