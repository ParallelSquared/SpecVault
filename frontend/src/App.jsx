import { useState, useEffect, useMemo, Fragment } from 'react';
import AddLibraryForm from './AddLibraryForm';
import FilterBar from './FilterBar';
import ModDetails from './ModDetails';
import LibraryDetails from './LibraryDetails';
import FileDetails from './FileDetails';
import LibraryMenu from './LibraryMenu';
import HistoryDetails from './HistoryDetails';
import WhoAmI from './WhoAmI';
import StarButton from './StarButton';
import { useWho } from './useWho';
import {
  PRIMARY_FIELDS, GRID_FIELDS, ALL_FILTERABLE_FIELDS, COMPUTED_FIELDS, ME_FILTER, valueOf,
} from './libraryFields';
import { formatBytes, formatDate } from './formatters';
import { libraryUrl } from './api';


// GET /libraries/ is paged. PAGE_SIZE must stay <= the backend's MAX_PAGE_SIZE.
const PAGE_SIZE = 500;
// Safety stop so a huge catalog cannot lock up the browser; if we hit it the
// table says so rather than pretending the first rows are the whole catalog.
const MAX_ROWS = 5000;

// The orders the list can be in. Each is a number to sort by, biggest first
// unless reversed; clicking the sort already in use reverses it. Ties go to
// the library added most recently, in either direction, so something new is
// never buried among its equals.
const SORTS = [
  { value: 'stars', label: 'Stars', key: (lib) => lib.stars },
  // How big a library is. One saved without being readable has no count, and
  // stays at the bottom whichever way round rather than reading as empty.
  { value: 'precursors', label: 'Precursors', key: (lib) => lib.precursors ?? null },
  { value: 'added', label: 'Date Added', key: (lib) => lib.id },
  // The Modified column: when the library file was last changed on the share,
  // not when its entry was edited here. A library whose file cannot be found
  // has no time, and stays at the bottom whichever way round.
  { value: 'modified', label: 'Date Modified',
    key: (lib) => (lib.updated_at ? new Date(lib.updated_at).getTime() : null) },
];

const newestAdded = (a, b) => b.id - a.id;

function compareBy({ by, descending }) {
  const { key } = SORTS.find((sort) => sort.value === by) ?? SORTS[0];
  return (a, b) => {
    const [ka, kb] = [key(a), key(b)];
    if (ka === null || kb === null) {
      return ka === kb ? newestAdded(a, b) : (ka === null ? 1 : -1);
    }
    return (descending ? kb - ka : ka - kb) || newestAdded(a, b);
  };
}

const defaultFilters = () => {
  const defaults = {};
  COMPUTED_FIELDS.forEach((f) => { if (f.default) defaults[f.name] = f.default; });
  return defaults;
};

function renderCellValue(field, lib) {
  const value = valueOf(field, lib);
  if (field.name === 'path_exists') return value ? '✅' : '❌';
  if (field.name === 'file_size') return formatBytes(value);
  if (field.name === 'updated_at' || field.name === 'date_created') return formatDate(value);
  // A plain YYYY-MM-DD, shown as it is: going through Date would read it as UTC
  // midnight and show the day before anywhere west of Greenwich
  if (field.type === 'date') return value || '—';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

function App() {
  const [view, setView] = useState('browse');
  const [libraries, setLibraries] = useState([]);
  const [fieldOptions, setFieldOptions] = useState({});
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState(defaultFilters());
  const [expandedId, setExpandedId] = useState(null);
  const [menuId, setMenuId] = useState(null);
  // Most-starred first by default, ties to the newest; "Newest" is there so a
  // library added today, with no stars yet, can still be found.
  const [sort, setSort] = useState({ by: 'stars', descending: true });
  // A new sort starts biggest first -- most stars, newest, most recently
  // changed; the one in use flips.
  const chooseSort = (by) => setSort((current) => (
    current.by === by ? { by, descending: !current.descending } : { by, descending: true }
  ));
  const who = useWho();
  // The library the edit form is showing, or null. Held rather than looked up
  // by id so the form keeps what it was given while the listing refreshes.
  const [editing, setEditing] = useState(null);
  const [totalCount, setTotalCount] = useState(0);

  // Walk every page before rendering. A bare GET /libraries/ returned only the
  // first page, and the table displayed it as if it were the entire catalog --
  // so library 101 of 240 simply did not exist as far as the UI was concerned.
  const fetchLibraries = async () => {
    try {
      const collected = [];
      let reportedTotal = null;
      for (let skip = 0; skip < MAX_ROWS; skip += PAGE_SIZE) {
        const res = await fetch(libraryUrl(`?skip=${skip}&limit=${PAGE_SIZE}`));
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        const header = res.headers.get('X-Total-Count');
        if (header !== null) reportedTotal = Number(header);
        const page = await res.json();
        collected.push(...page);
        if (page.length < PAGE_SIZE) break;
      }
      setLibraries(collected);
      setTotalCount(reportedTotal ?? collected.length);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  };

  const fetchFieldOptions = () => {
    fetch(libraryUrl('options'))
      .then((res) => res.json())
      .then((data) => setFieldOptions((prev) => ({ ...prev, ...data })))
      .catch(() => {});
  };

  useEffect(() => {
    fetchLibraries();
    fetchFieldOptions();
  }, []);

  const handleLibraryAdded = () => {
    fetchLibraries();
    fetchFieldOptions();
    setView('browse');
  };

  const handleLibraryEdited = () => {
    setEditing(null);
    fetchLibraries();
    fetchFieldOptions();
    setView('browse');
  };

  const handleEditRequested = (lib) => {
    setMenuId(null);
    setEditing(lib);
    setView('edit');
  };

  const handleLibraryDeleted = () => {
    setMenuId(null);
    setExpandedId(null);
    // The options too: a creator or project only the deleted library used
    // should stop being offered in the filters and the Add form.
    fetchLibraries();
    fetchFieldOptions();
  };

  const fileFormatOptions = useMemo(() => {
    const formats = libraries.map((lib) => lib.file_format).filter(Boolean);
    return [...new Set(formats)].sort();
  }, [libraries]);

  // Everyone who has starred anything, for the "Starred By" filter
  const starrerOptions = useMemo(() => {
    const names = libraries.flatMap((lib) => lib.starred_by || []);
    return [...new Set(names)].sort((a, b) => a.localeCompare(b));
  }, [libraries]);

  // A star changes one library; swap it in rather than reloading them all
  const handleLibraryUpdated = (updated) => {
    setLibraries((prev) => prev.map((lib) => (lib.id === updated.id ? updated : lib)));
  };

  const filteredLibraries = useMemo(() => {
    return libraries.filter((lib) => {
      return ALL_FILTERABLE_FIELDS.every((field) => {
        const filterValue = filters[field.name];
        if (!filterValue) return true;
        if (field.filterType === 'text') {
          // Matched against what is on screen: someone filtering paths types
          // what their own machine calls the folder, not the stored form.
          const cellValue = (valueOf(field, lib) || '').toString().toLowerCase();
          return cellValue.includes(filterValue.toLowerCase());
        }
        if (field.filterType === 'select') return lib[field.name] === filterValue;
        if (field.filterType === 'multiselect') {
          // "Me" is whoever this browser says it is now
          const wanted = field.meOption && filterValue === ME_FILTER ? who : filterValue;
          return (lib[field.name] || []).includes(wanted);
        }
        if (field.filterType === 'boolean') {
          if (filterValue === 'all') return true;
          if (filterValue === 'exists') return lib[field.name] === true;
          if (filterValue === 'missing') return lib[field.name] === false;
        }
        return true;
      });
    });
  }, [libraries, filters, who]);

  const sortedLibraries = useMemo(() => {
    return [...filteredLibraries].sort(compareBy(sort));
  }, [filteredLibraries, sort]);

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ margin: '0 0 1.5rem' }}>
        <img src="/logo-full.svg" alt="SpecVault" style={{ height: '96px', width: 'auto', display: 'block' }} />
      </h1>

      <nav style={{
        marginBottom: '1.5rem', display: 'flex', gap: '0.5rem', alignItems: 'center',
      }}>
        <button onClick={() => setView('browse')} style={{ fontWeight: view === 'browse' ? 'bold' : 'normal' }}>
          Browse Libraries
        </button>
        <button onClick={() => setView('add')} style={{ fontWeight: view === 'add' ? 'bold' : 'normal' }}>
          Add Library
        </button>
        {/* Out here rather than inside the forms: it applies to everything
            that changes a library, and on a shared machine it being visible
            is what makes a wrong name obvious. */}
        <div style={{ marginLeft: 'auto' }}>
          <WhoAmI options={fieldOptions.creator || []} />
        </div>
      </nav>

      {view === 'add' && (
        <AddLibraryForm onLibraryAdded={handleLibraryAdded} fieldOptions={fieldOptions} />
      )}

      {view === 'edit' && editing && (
        <AddLibraryForm
          key={editing.id}
          library={editing}
          onLibraryAdded={handleLibraryEdited}
          // Refetched even on Cancel: removing a path takes effect at once
          // rather than waiting for Save, so the listing may be out of date.
          onCancel={() => { setEditing(null); fetchLibraries(); setView('browse'); }}
          fieldOptions={fieldOptions}
        />
      )}

      {view === 'browse' && (
        <>
          {error && <p>Error loading libraries: {error}</p>}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '1rem', flexWrap: 'wrap' }}>
            <h2>Libraries ({filteredLibraries.length} of {totalCount})</h2>
            <div style={{ fontSize: '0.8rem', color: '#555' }}>
              Sort:{' '}
              {SORTS.map(({ value, label }) => {
                const active = sort.by === value;
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => chooseSort(value)}
                    aria-pressed={active}
                    title={active ? 'Click to reverse' : `Sort by ${label.toLowerCase()}`}
                    style={{ fontSize: '0.8rem', marginLeft: '0.25rem', fontWeight: active ? 'bold' : 'normal' }}
                  >
                    {label}{active && (sort.descending ? ' ↓' : ' ↑')}
                  </button>
                );
              })}
            </div>
          </div>
          {libraries.length < totalCount && (
            <p style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
              ⚠ Loaded the first {libraries.length} of {totalCount} libraries; filters
              below apply only to those.
            </p>
          )}
          <FilterBar filters={filters} onChange={setFilters} fieldOptions={{ ...fieldOptions, file_format: fileFormatOptions, starred_by: starrerOptions }}/>

          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #ccc' }}>
                <th style={{ width: '2rem' }}></th>
                {PRIMARY_FIELDS.map((field) => (
                  <th
                    key={field.name}
                    title={field.title ?? field.label}
                    style={{
                      padding: '0.5rem',
                      width: field.name === 'path' ? '50%' : `${50 / (PRIMARY_FIELDS.length - 1)}%`,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      textAlign: 'center',
                    }}
                  >
                    {field.label}
                  </th>
                ))}
                <th style={{ width: '3.5rem' }} title="Stars: how many people use it">★</th>
                <th style={{ width: '2.5rem' }}></th>
              </tr>
            </thead>
            <tbody>
              {sortedLibraries.map((lib) => (
                <Fragment key={lib.id}>
                  <tr
                    onClick={() => setExpandedId(expandedId === lib.id ? null : lib.id)}
                    style={{ borderBottom: '1px solid #eee', cursor: 'pointer' }}
                  >
                    <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                      {expandedId === lib.id ? '▾' : '▸'}
                    </td>
                    {PRIMARY_FIELDS.map((field) => (
                      <td
                        key={field.name}
                        title={String(renderCellValue(field, lib))}
                        style={{
                          padding: '0.5rem',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          maxWidth: 0,
                          textAlign: field.name === 'path' ? 'left' : 'center',
                        }}
                      >
                        {renderCellValue(field, lib)}
                      </td>
                    ))}
                    <td style={{ padding: '0.5rem 0', textAlign: 'center' }}>
                      <StarButton
                        lib={lib}
                        creators={fieldOptions.creator || []}
                        onUpdated={handleLibraryUpdated}
                        onError={setError}
                      />
                    </td>
                    <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                      <LibraryMenu
                        lib={lib}
                        creators={fieldOptions.creator || []}
                        open={menuId === lib.id}
                        onToggle={setMenuId}
                        onEdit={() => handleEditRequested(lib)}
                        onDeleted={handleLibraryDeleted}
                        onError={setError}
                      />
                    </td>
                  </tr>
                  {expandedId === lib.id && (
                    <tr>
                      <td colSpan={PRIMARY_FIELDS.length + 3} style={{ background: '#fafafa', padding: '1rem' }}>
                        <div style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                          gap: '0.75rem',
                        }}>
                          {GRID_FIELDS.map((field) => (
                            <div key={field.name} style={{ gridColumn: field.wide ? '1 / -1' : undefined }}>
                              <div style={{ fontSize: '0.75rem', color: '#666', fontWeight: 'bold' }}>
                                {field.label}
                              </div>
                              <div style={{ wordBreak: 'break-word', whiteSpace: field.wide ? 'pre-wrap' : undefined }}>
                                {renderCellValue(field, lib)}
                              </div>
                            </div>
                          ))}
                        </div>
                        <FileDetails lib={lib} />
                        <ModDetails details={lib.mod_details} />
                        <LibraryDetails stats={lib.library_stats} />
                        <HistoryDetails lib={lib} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export default App;