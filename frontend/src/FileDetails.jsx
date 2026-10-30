import { useState } from 'react';

// The files behind a library -- the library itself, its creation log, FASTA
// and source runs -- one full path per line, kept out of the field grid where
// long paths broke mid-word across narrow columns.

// Long paths wrap only after a separator, so a line never breaks inside a name
function wrappable(path) {
  return path.split(/(?<=[\\/])/).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
}

function PathLine({ path }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(path).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };
  return (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline' }}>
      <span style={{ fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.8rem' }}>{wrappable(path)}</span>
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
  const library = lib.display_path || lib.path;
  const log = lib.display_creation_log_path || lib.creation_log_path;
  const fasta = lib.display_fasta_path || lib.fasta_path;
  const groups = [
    ['Library', [library]],
    ['Creation log', log ? [log] : []],
    // Several FASTAs are saved as one field, joined by "; "
    ['FASTA', fasta ? fasta.split('; ') : []],
    ['Source runs', lib.source_runs || []],
  ].filter(([, paths]) => paths.length);
  const count = groups.reduce((n, [, paths]) => n + paths.length, 0);

  return (
    <div style={{ marginTop: '0.75rem' }}>
      <button type="button" onClick={() => setOpen((wasOpen) => !wasOpen)} style={{ fontSize: '0.8rem' }}>
        {open ? 'Hide' : 'Show'} files ({count})
      </button>
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
                    {paths.map((path) => <PathLine key={path} path={path} />)}
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
