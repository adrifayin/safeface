/**
 * Keycloak OIDC login (authorization code + PKCE) via oidc-client-ts.
 *
 * - Tokens are kept in memory only (never localStorage), so closing the tab
 *   ends the client session; Keycloak's SSO cookie allows a silent re-login.
 * - After 15 minutes without user activity the client signs out (NFR-S4);
 *   Keycloak enforces the same idle limit server-side.
 */
import { InMemoryWebStorage, User, UserManager, WebStorageStateStore } from "oidc-client-ts";

const origin = window.location.origin;
export const IDLE_LIMIT_MS = 15 * 60 * 1000;

export const userManager = new UserManager({
  authority: `${origin}/auth/realms/safeface`,
  client_id: "safeface-web",
  redirect_uri: `${origin}/callback`,
  post_logout_redirect_uri: `${origin}/`,
  response_type: "code",
  scope: "openid profile",
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
  stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  monitorSession: false,
});

let current: User | null = null;
userManager.events.addUserLoaded((u) => {
  current = u;
});
userManager.events.addUserUnloaded(() => {
  current = null;
});

export async function getUser(): Promise<User | null> {
  if (current && !current.expired) return current;
  current = await userManager.getUser();
  return current && !current.expired ? current : null;
}

export function accessToken(): string | null {
  return current?.access_token ?? null;
}

export async function login(): Promise<void> {
  await userManager.signinRedirect({ state: window.location.pathname });
}

export async function logout(): Promise<void> {
  try {
    const token = accessToken();
    if (token) {
      await fetch("/api/v1/session/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
    }
  } finally {
    await userManager.signoutRedirect();
  }
}

/** Start the idle timer. Returns a cleanup function. */
export function watchIdle(onIdle: () => void): () => void {
  let last = Date.now();
  const bump = () => (last = Date.now());
  const events = ["mousemove", "keydown", "mousedown", "touchstart", "wheel"];
  events.forEach((e) => window.addEventListener(e, bump, { passive: true }));
  const timer = window.setInterval(() => {
    if (Date.now() - last > IDLE_LIMIT_MS) onIdle();
  }, 15_000);
  return () => {
    events.forEach((e) => window.removeEventListener(e, bump));
    window.clearInterval(timer);
  };
}
