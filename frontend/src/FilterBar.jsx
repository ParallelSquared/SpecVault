import { useState } from 'react';
import {
  ALL_FILTERABLE_FIELDS, FILTER_SECTIONS, ME_FILTER, TOP_FILTERS,
} from './libraryFields';
import { sha256OfFile } from './hashFile';
import { useWho } from './useWho';

// The same column tracks for the top row and every section, so filters line up
// down the page whatever row they are in. auto-fill rather than auto-fit: a
// short row keeps its columns the width of a full one instead of stretching.
const GRID = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '0.6rem 0.75rem',
};
const FILL = { width: '100%', boxSizing: 'border-box' };
const SECTION_TITLE = {
  margin: '0 0 0.35rem', fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.05em',
  textTransform: 'uppercase', color: '#888', borderBottom: '1px solid #e2e2e2', paddingBottom: '0.2rem',
};

function FilterBar({ filters, onChange, fieldOptions }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const who = useWho();
  // The file being looked for, by name, and how far through hashing it is
  const [hashedName, setHashedName] = useState(null);
  const [hashLookupStatus, setHashLookupStatus] = useState(null);

  const handleChange = (name, value) => {
    onChange((prev) => ({ ...prev, [name]: value }));
  };

  // Any file the person can open -- on their own disk or on the share --
  // hashed here in the browser; see hashFile.js for why not on the server.
  const handleHashLookup = async (file) => {
    if (!file) return;
    setHashedName(file.name);
    handleChange('content_hash', '');
    setHashLookupStatus('Hashing... 0%');
    try {
      const hash = await sha256OfFile(file, (done) => {
        setHashLookupStatus(`Hashing... ${Math.round(done * 100)}%`);
      });
      handleChange('content_hash', hash);
      setHashLookupStatus(null);
    } catch (err) {
      setHashLookupStatus(`Could not read ${file.name}: ${err.message}`);
    }
  };

  const clearHashLookup = () => {
    setHashedName(null);
    setHashLookupStatus(null);
    handleChange('content_hash', '');
  };

  const renderFilterInput = (field) => {
    if (field.name === 'content_hash') {
      return (
        <div key={field.name}>
          <label style={{ display: 'block', fontSize: '0.75rem', color: '#555' }}>
            {field.label}
          </label>
          {hashedName && !hashLookupStatus ? (
            <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center', fontSize: '0.8rem' }}>
              <span title={filters.content_hash}>{hashedName}</span>
              <button type="button" onClick={clearHashLookup} style={{ fontSize: '0.75rem' }}>
                Clear
              </button>
            </div>
          ) : (
            <input
              type="file"
              // Whatever was picked last is gone once it has been read, so the
              // same file can be picked again after a Clear
              onChange={(e) => { handleHashLookup(e.target.files?.[0]); e.target.value = ''; }}
              disabled={hashLookupStatus?.startsWith('Hashing')}
              title="Find libraries with exactly the same contents as a file on your computer or the share"
              style={{ fontSize: '0.8rem' }}
            />
          )}
          {hashLookupStatus && (
            <span style={{ fontSize: '0.75rem', color: '#666' }}>{hashLookupStatus}</span>
          )}
        </div>
      );
    }

    return (
      <div key={field.name}>
        <label style={{ display: 'block', fontSize: '0.75rem', color: '#555' }}>{field.label}</label>

        {field.filterType === 'text' && (
          <input
            type="text"
            placeholder="Filter..."
            value={filters[field.name] || ''}
            onChange={(e) => handleChange(field.name, e.target.value)}
            style={FILL}
          />
        )}

        {(field.filterType === 'select' || field.filterType === 'multiselect') && (
          <select
            value={filters[field.name] || ''}
            onChange={(e) => handleChange(field.name, e.target.value)}
            style={FILL}
          >
            <option value="">All</option>
            {field.meOption && (
              <option value={ME_FILTER}>{who ? `Me (${who})` : 'Me'}</option>
            )}
            {(fieldOptions[field.name] || []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        )}

        {field.filterType === 'boolean' && (
          <select
            value={filters[field.name] || 'all'}
            onChange={(e) => handleChange(field.name, e.target.value)}
            style={FILL}
          >
            <option value="all">All</option>
            <option value="exists">{field.trueLabel || 'Yes'} only</option>
            <option value="missing">{field.falseLabel || 'No'} only</option>
          </select>
        )}
      </div>
    );
  };

  const filterable = ALL_FILTERABLE_FIELDS.filter((f) => f.filterType);
  const byName = Object.fromEntries(filterable.map((f) => [f.name, f]));
  const pick = (names) => names.map((name) => byName[name]).filter(Boolean);
  const placed = new Set([...TOP_FILTERS, ...FILTER_SECTIONS.flatMap(([, names]) => names)]);
  const unplaced = filterable.filter((f) => !placed.has(f.name));
  const sections = [
    ...FILTER_SECTIONS.map(([title, names]) => [title, pick(names)]),
    ...(unplaced.length ? [['Other', unplaced]] : []),
  ];

  return (
    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#f7f7f7', borderRadius: '6px' }}>
      <div style={GRID}>{pick(TOP_FILTERS).map(renderFilterInput)}</div>

      <button
        type="button"
        onClick={() => setShowAdvanced((s) => !s)}
        style={{ marginTop: '0.75rem', fontSize: '0.85rem', background: 'none', border: 'none', color: '#4a5', cursor: 'pointer', padding: 0 }}
      >
        {showAdvanced ? '▾ Hide more filters' : '▸ More filters'}
      </button>

      {showAdvanced && sections.map(([title, fields]) => (
        <section key={title} style={{ marginTop: '0.75rem' }}>
          <h3 style={SECTION_TITLE}>{title}</h3>
          <div style={GRID}>{fields.map(renderFilterInput)}</div>
        </section>
      ))}
    </div>
  );
}

export default FilterBar;