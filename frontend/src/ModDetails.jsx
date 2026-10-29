import { useState } from 'react';

// One row per modification per site, so a label that sits on every amino acid
// reads as exactly that rather than being summarised away. Long lists scroll
// instead of pushing the rest of the table off the screen.
const MAX_HEIGHT = '18rem';
const WARN = '#b45309';

// A mass this far from what the modification should weigh is a real
// disagreement, not rounding. Matches MASS_TOLERANCE in the backend.
const MASS_TOLERANCE = 0.005;

function isMisweighed(detail) {
  return (
    detail.mass !== null && detail.mass !== undefined &&
    detail.expected_mass !== null && detail.expected_mass !== undefined &&
    Math.abs(detail.mass - detail.expected_mass) > MASS_TOLERANCE
  );
}

// Weighs nothing at all: the library names the modification and left its
// mass out. Distinct from weighing the wrong amount, which is a mislabel.
function isMassless(detail) {
  return isMisweighed(detail) && Math.abs(detail.mass) <= MASS_TOLERANCE;
}

function isUnweighed(detail) {
  return detail.mass === null || detail.mass === undefined;
}

function formatMass(mass) {
  if (mass === null || mass === undefined) return '—';
  return `${mass >= 0 ? '+' : ''}${mass.toFixed(5)}`;
}

function formatIdentity(detail) {
  if (!detail.identified_as) return '—';
  // The channel is only given when one channel explains the mass; when several
  // could, the tag is still named but the channel is left off rather than picked.
  return detail.channel ? `${detail.identified_as} (channel ${detail.channel})` : detail.identified_as;
}

function ModDetails({ details }) {
  const [open, setOpen] = useState(false);

  if (!details || details.length === 0) return null;

  const sites = details.length;
  const names = new Set(details.map((d) => d.name)).size;
  const unique = (rows) => [...new Set(rows.map((d) => d.name))];
  const missingNames = unique(details.filter(isMassless));
  const wrongNames = unique(details.filter((d) => isMisweighed(d) && !isMassless(d)));
  const unweighedNames = unique(details.filter(isUnweighed));
  const warn = missingNames.length > 0 || wrongNames.length > 0 || unweighedNames.length > 0;

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        style={{ fontSize: '0.8rem', color: warn ? WARN : undefined }}
      >
        {open ? 'Hide' : 'Show'} mod details ({names} {names === 1 ? 'mod' : 'mods'}
        {sites !== names ? `, ${sites} sites` : ''}){warn ? ' ⚠' : ''}
      </button>

      {/* Visible without opening the table. A modification declared without its
          mass means the library is broken; one we could not weigh at all means
          its identity and mass are unchecked, which is worth knowing too. */}
      {missingNames.length > 0 && (
        <p style={{ fontSize: '0.8rem', color: WARN, margin: '0.4rem 0 0' }}>
          ⚠ {missingNames.join(', ')} {missingNames.length === 1 ? 'is' : 'are'} declared
          in this library but {missingNames.length === 1 ? 'its' : 'their'} mass is missing
          from the precursor m/z.
        </p>
      )}
      {wrongNames.length > 0 && (
        <p style={{ fontSize: '0.8rem', color: WARN, margin: '0.4rem 0 0' }}>
          ⚠ {wrongNames.join(', ')} {wrongNames.length === 1 ? 'weighs' : 'weigh'} something
          other than UniMod lists — the annotation may name the wrong modification.
        </p>
      )}
      {unweighedNames.length > 0 && (
        <p style={{ fontSize: '0.8rem', color: WARN, margin: '0.4rem 0 0' }}>
          ⚠ No mass could be worked out for {unweighedNames.join(', ')}, so{' '}
          {unweighedNames.length === 1 ? 'it' : 'they'} could not be checked or
          identified by mass.
        </p>
      )}

      {open && (
        <div style={{ maxHeight: MAX_HEIGHT, overflowY: 'auto', marginTop: '0.5rem' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #ccc', textAlign: 'left' }}>
                <th style={{ padding: '0.25rem 0.5rem' }}>Modification</th>
                <th style={{ padding: '0.25rem 0.5rem' }}>Site</th>
                <th style={{ padding: '0.25rem 0.5rem', textAlign: 'right' }}>Precursors</th>
                <th style={{ padding: '0.25rem 0.5rem', textAlign: 'right' }}>Mass (Da)</th>
                <th style={{ padding: '0.25rem 0.5rem' }}>Identified as</th>
              </tr>
            </thead>
            <tbody>
              {details.map((detail, i) => {
                const bad = isMisweighed(detail);
                const unweighed = isUnweighed(detail);
                return (
                  <tr
                    key={`${detail.name}-${detail.site}-${i}`}
                    style={{ borderBottom: '1px solid #eee', color: bad || unweighed ? WARN : undefined }}
                  >
                    <td style={{ padding: '0.25rem 0.5rem', fontFamily: 'monospace' }}>{detail.name}</td>
                    <td style={{ padding: '0.25rem 0.5rem' }}>{detail.site}</td>
                    <td style={{ padding: '0.25rem 0.5rem', textAlign: 'right' }}>
                      {detail.precursors.toLocaleString()}
                    </td>
                    <td style={{ padding: '0.25rem 0.5rem', textAlign: 'right', fontFamily: 'monospace' }}>
                      {formatMass(detail.mass)}
                      {unweighed && <span title="No mass could be worked out"> ⚠</span>}
                      {bad && (
                        <span title="What this modification should weigh">
                          {' '}⚠ expected {formatMass(detail.expected_mass)}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '0.25rem 0.5rem' }}>{formatIdentity(detail)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default ModDetails;
