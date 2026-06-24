import { Container, getContainer } from "@cloudflare/containers";

import { handleRequest, type EdgeEnv } from "./edge";

const CONTAINER_KEY = "public-jaffle-shop";

export interface Env extends EdgeEnv {
  BACKEND: DurableObjectNamespace<SemanticRailsContainer>;
  SEMANTIC_RAILS_CORS_ORIGINS: string;
  SEMANTIC_RAILS_PUBLIC_DEMO: string;
}

export class SemanticRailsContainer extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = "10m";
  envVars = {
    SEMANTIC_RAILS_PACKAGE: "jaffle_shop",
    SEMANTIC_RAILS_PUBLIC_DEMO: "1",
    SEMANTIC_RAILS_CORS_ORIGINS:
      "https://semantic-rails.com,https://www.semantic-rails.com",
  };

  override onStart(): void {
    console.log("Semantic Rails public demo container started.");
  }

  override onStop(): void {
    console.log("Semantic Rails public demo container stopped.");
  }

  override onError(error: unknown): void {
    console.error("Semantic Rails public demo container error.", error);
  }
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.BACKEND, CONTAINER_KEY);
    return handleRequest(request, env, (forwarded) => container.fetch(forwarded));
  },
} satisfies ExportedHandler<Env>;
