// Point d'entrée Cloudflare : toutes les requêtes du navigateur sont transmises au
// conteneur Python (UI Trafficker). HTTPS est assuré par Cloudflare.
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
    if (!env.TRAFFICKER_PASSWORD_HASH || !env.TRAFFICKER_SECRET_KEY) {
      return new Response(
        "Trafficker : configurez les secrets TRAFFICKER_PASSWORD_HASH et TRAFFICKER_SECRET_KEY " +
          "(npx wrangler secret put ...).", { status: 503 });
    }
    // Une seule instance : l'état (SQLite) vit dans ce conteneur
    return env.TRAFFICKER.getByName("main").fetch(request);
  },
};
