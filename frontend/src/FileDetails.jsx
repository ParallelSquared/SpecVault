import { useState } from 'react';

// The files behind a library -- the library itself, its creation log, FASTA
// and source runs -- one full path per line, kept out of the field grid where
// long paths broke mid-word across narrow columns.

// Long paths wrap only after a separator, so a line never breaks inside a name
function wrappable(path) {
  return path.split(/(?<=[\\/])/).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
}

const MISSING = '#b45309';

function PathLine({ path, missing }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(path).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };
  return (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline' }}>
      <span style={{
        fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.8rem',
        color: missing ? MISSING : undefined,
      }}>
        {wrappable(path)}
      </span>
      {/* A library can be recorded in several places; one of them being gone
          is worth seeing here, where the paths are, rather than only as the
          whole library counting as found because another copy is fine. */}
      {missing && (
        <span style={{ color: MISSING, fontSize: '0.75rem', flexShrink: 0 }} title="No file at this path">
          ⚠ not found
        </span>
      )}
      <button type="button" onClick={copy} style={{ fontSize: '0.7rem', flexShrink: 0 }}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

function FileDetails({ lib }) {
  const [open, setOpen] = useState(false);
  // The display_* paths: the same files, written the way this machine writes
  // paths, so Copy puts something on the clipboard that works when pasted.
  const log = lib.display_creation_log_path || lib.creation_log_path;
  const fasta = lib.display_fasta_path || lib.fasta_path;
  // Every place the library's file is, each saying whether it is there. Older
  // responses carried only the one path.
  const libraryPaths = lib.path_details?.length
    ? lib.path_details.map((d) => ({ path: d.display, missing: !d.exists }))
    : [{ path: lib.display_path || lib.path, missing: !lib.path_exists }];
  const plain = (paths) => paths.map((path) => ({ path, missing: false }));
  const groups = [
    [libraryPaths.length > 1 ? `Library (${libraryPaths.length} copies)` : 'Library', libraryPaths],
    ['Creation log', log ? plain([log]) : []],
    // Several FASTAs are saved as one field, joined by "; "
    ['FASTA', fasta ? plain(fasta.split('; ')) : []],
    ['Source runs', plain(lib.source_runs || [])],
  ].filter(([, paths]) => paths.length);
  const count = groups.reduce((n, [, paths]) => n + paths.length, 0);
  const missingCount = libraryPaths.filter((p) => p.missing).length;

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <button
        type="button"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        style={{ fontSize: '0.8rem', color: missingCount ? MISSING : undefined }}
      >
        {open ? 'Hide' : 'Show'} files ({count}){missingCount ? ' ⚠' : ''}
      </button>
      {/* Visible without opening the list: a copy that has gone is something
          to fix, and the library still counts as found while another is there. */}
      {missingCount > 0 && (
        <p style={{ fontSize: '0.8rem', color: MISSING, margin: '0.4rem 0 0' }}>
          ⚠ {missingCount} of this library&apos;s {libraryPaths.length} recorded
          {libraryPaths.length === 1 ? ' path is' : ' paths are'} not there.
        </p>
      )}
      {open && (
        <table style={{ borderCollapse: 'collapse', marginTop: '0.5rem', width: '100%' }}>
          <tbody>
            {groups.map(([label, paths]) => (
              <tr key={label}>
                <td style={{
                  padding: '0.25rem 1rem 0.25rem 0', fontSize: '0.75rem', color: '#666',
                  fontWeight: 'bold', whiteSpace: 'nowrap', verticalAlign: 'top', width: '1%',
                }}>
                  {label}
                </td>
                <td style={{ padding: '0.25rem 0' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    {paths.map(({ path, missing }) => (
                      <PathLine key={path} path={path} missing={missing} />
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default FileDetails;
