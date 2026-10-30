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
