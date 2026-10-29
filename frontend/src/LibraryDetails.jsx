import { useState } from 'react';

// What the library holds -- its precursors, fragments and digest -- read from
// the file on save. Only what the file has is shown: a library without c or z
// ions has no row for them.

function percent(value) {
  if (value === 0) return '<0.01%';  // present, just too rare to round to anything
  return `${value >= 1 ? value.toFixed(1) : value.toFixed(2)}%`;
}

function span(range, digits) {
  if (!range) return '—';
  const [low, high] = range;
  return `${low.toFixed(digits)} – ${high.toFixed(digits)}`;
}

function joined(parts) {
  return parts.length ? parts.join(' · ') : '—';
}

function Section({ title, rows }) {
  return (
    <div>
      <div style={{ fontSize: '0.75rem', color: '#666', fontWeight: 'bold', marginBottom: '0.25rem' }}>
        {title}
      </div>
      <table style={{ borderCollapse: 'collapse', fontSize: '0.8rem' }}>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td style={{ padding: '0.1rem 0.75rem 0.1rem 0', color: '#555', whiteSpace: 'nowrap', verticalAlign: 'top' }}>
                {label}
              </td>
              <td style={{ padding: '0.1rem 0' }}>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function precursorRows(p) {
  const length = p.length
    ? `${p.length.min} – ${p.length.max} (median ${p.length.median})`
    : '—';
  return [
    ['Charges', joined(Object.entries(p.charges).map(([z, share]) => `${z}+ ${percent(share)}`))],
    ['Precursor m/z', span(p.mz, 2)],
    ['Peptide length', length],
    ['Ion mobility', p.ion_mobility ? span(p.ion_mobility, 3) : 'None'],
  ];
}

function fragmentRows(f) {
  const per = f.per_precursor;
  const series = (t) => (t.first !== null && t.first !== undefined ? `${t.type}${t.first}–${t.type}${t.last}` : '');
  return [
    ['Per precursor', `min ${per.min} · median ${per.median} · mean ${per.mean} · max ${per.max}`],
    ...f.types.map((t) => [`${t.type} ions`, `${t.mean} per precursor${series(t) ? `, ${series(t)}` : ''}`]),
    ['Fragment charges', f.charges ? joined(f.charges.map((z) => `${z}+`)) : '—'],
    ['Neutral losses', f.losses ? joined(f.losses) : '—'],
    ['Fragment m/z', span(f.mz, 2)],
  ];
}

function digestRows(d) {
  const cut = d.terminus === 'C' ? 'Peptides ending in' : 'Peptides starting with';
  const shares = Object.entries(d.residues).map(([r, share]) => `${r} ${percent(share)}`);
  return [
    ['Protease', `${d.protease} (detected)`],
    [cut, joined([...shares, `other ${percent(d.other)}`])],
    ['Missed cleavages', joined(Object.entries(d.missed_cleavages).map(([n, share]) => `${n}: ${percent(share)}`))],
  ];
}

function LibraryDetails({ stats }) {
  const [open, setOpen] = useState(false);
  if (!stats) return null;

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <button type="button" onClick={() => setOpen((wasOpen) => !wasOpen)} style={{ fontSize: '0.8rem' }}>
        {open ? 'Hide' : 'Show'} library details
      </button>
      {open && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: '1rem',
          marginTop: '0.5rem',
        }}>
          {stats.precursors && <Section title="Precursors" rows={precursorRows(stats.precursors)} />}
          {stats.fragments && <Section title="Fragments" rows={fragmentRows(stats.fragments)} />}
          {stats.digest && <Section title="Digest" rows={digestRows(stats.digest)} />}
        </div>
      )}
    </div>
  );
}

export default LibraryDetails;
