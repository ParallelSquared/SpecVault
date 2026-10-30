import { useState, useEffect, useMemo, Fragment } from 'react';
import AddLibraryForm from './AddLibraryForm';
import FilterBar from './FilterBar';
import ModDetails from './ModDetails';
import LibraryDetails from './LibraryDetails';
import FileDetails from './FileDetails';
import { PRIMARY_FIELDS, GRID_FIELDS, ALL_FILTERABLE_FIELDS, COMPUTED_FIELDS, valueOf } from './libraryFields';
import { formatBytes, formatDate } from './formatters';
import { libraryUrl } from './api';


// GET /libraries/ is paged. PAGE_SIZE must stay <= the backend's MAX_PAGE_SIZE.
const PAGE_SIZE = 500;
// Safety stop so a huge catalog cannot lock up the browser; if we hit it the
// table says so rather than pretending the first rows are the whole catalog.
const MAX_ROWS = 5000;

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

  const fileFormatOptions = useMemo(() => {
    const formats = libraries.map((lib) => lib.file_format).filter(Boolean);
    return [...new Set(formats)].sort();
  }, [libraries]);

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
        if (field.filterType === 'multiselect') return (lib[field.name] || []).includes(filterValue);
        if (field.filterType === 'boolean') {
          if (filterValue === 'all') return true;
          if (filterValue === 'exists') return lib[field.name] === true;
          if (filterValue === 'missing') return lib[field.name] === false;
        }
        return true;
      });
    });
  }, [libraries, filters]);

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '1.5rem', fontFamily: 'system-ui, sans-serif' }}>
      <h1 style={{ margin: '0 0 1.5rem' }}>
        <img src="/logo-full.svg" alt="SpecVault" style={{ height: '96px', width: 'auto', display: 'block' }} />
      </h1>

      <nav style={{ marginBottom: '1.5rem', display: 'flex', gap: '0.5rem' }}>
        <button onClick={() => setView('browse')} style={{ fontWeight: view === 'browse' ? 'bold' : 'normal' }}>
          Browse Libraries
        </button>
        <button onClick={() => setView('add')} style={{ fontWeight: view === 'add' ? 'bold' : 'normal' }}>
          Add Library
        </button>
      </nav>

      {view === 'add' && (
        <AddLibraryForm onLibraryAdded={handleLibraryAdded} fieldOptions={fieldOptions} />
      )}

      {view === 'browse' && (
        <>
          {error && <p>Error loading libraries: {error}</p>}
          <h2>Libraries ({filteredLibraries.length} of {totalCount})</h2>
          {libraries.length < totalCount && (
            <p style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
              ⚠ Loaded the first {libraries.length} of {totalCount} libraries; filters
              below apply only to those.
            </p>
          )}
          <FilterBar filters={filters} onChange={setFilters} fieldOptions={{ ...fieldOptions, file_format: fileFormatOptions }}/>

          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #ccc' }}>
                <th style={{ width: '2rem' }}></th>
                {PRIMARY_FIELDS.map((field) => (
                  <th
                    key={field.name}
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
              </tr>
            </thead>
            <tbody>
              {filteredLibraries.map((lib) => (
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
                  </tr>
                  {expandedId === lib.id && (
                    <tr>
                      <td colSpan={PRIMARY_FIELDS.length + 1} style={{ background: '#fafafa', padding: '1rem' }}>
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