// Where the backend is. Empty means "the same origin this page came from",
// which is how SpecVault runs both ways: deployed, one process serves this
// page and the API; in development, Vite proxies /libraries to the backend
// (see vite.config.js). Same-origin either way means no CORS, and no hostname
// baked into the built bundle -- a build that hardcoded http://127.0.0.1:8000
// works only on the machine that served it.
//
// Set VITE_API_BASE only to point at a backend somewhere else entirely.
export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export const libraryUrl = (path = '') => `${API_BASE}/libraries/${path}`;

// Who the catalog records as having made a change.
//
// There are no accounts. This is whatever the person said they were called,
// kept in this browser and sent with every request that changes a library, so
// the history can answer "who should I ask about this entry" -- which is the
// question people actually have. It is self-reported, and meant to be: it is
// not a login and must never be read as one.
//
// Per browser, so on a shared machine two people inherit one name. That is
// why it sits in the page header rather than out of sight: wrong is obvious
// and one click to fix.
const WHO = 'specvault.who';

// Storage throws rather than returning null in a browser with site data
// blocked, which should cost the name, not the page.
export function whoAmI() {
  try {
    return localStorage.getItem(WHO) || '';
  } catch {
    return '';
  }
}

export function setWhoAmI(name) {
  try {
    if (name) localStorage.setItem(WHO, name);
    else localStorage.removeItem(WHO);
  } catch {
    // Not remembered for next time; this session still sends it.
  }
}

// Headers for a request that changes something. Saying nothing is allowed --
// the server records the change either way, just without a name.
export function changeHeaders(extra = {}) {
  const who = whoAmI();
  return who ? { ...extra, 'X-SpecVault-User': who } : { ...extra };
}
