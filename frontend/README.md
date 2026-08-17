# SpecVault — Frontend

React 19 + Vite UI for browsing and registering spectral libraries.

## Setup

```bash
npm install
cp .env.example .env   # optional; only needed if the backend isn't on 127.0.0.1:8000
npm run dev
```

Runs on http://localhost:5173. The backend must be running separately — see
[`../backend`](../backend).

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Oxlint |

## Layout

| File | Role |
|---|---|
| `src/libraryFields.js` | **Field registry.** Single source of truth — drives the add form, table columns, and filters. Add a field here and it appears in all three. |
| `src/api.js` | Backend base URL, from `VITE_API_BASE` |
| `src/App.jsx` | Shell, table, browse/add view switch |
| `src/AddLibraryForm.jsx` | Add form, incl. auto-fill from file |
| `src/FilterBar.jsx` | Filter controls, incl. hash lookup |
| `src/ComboBoxField.jsx` | Free-text-or-pick-existing input |
| `src/MultiComboBoxField.jsx` | Multi-value variant |
| `src/formatters.js` | Byte/date display helpers |
