// What a library is called when browsing: its Name, or else its folder and
// file -- `PSMtag_d0d4_predicted_lib_mbr\lib.parquet` -- since so many
// libraries are lib.parquet that the file name alone tells nobody which.

// The separator this machine's paths use, read off the path shown to it
const separatorOf = (displayPath) => (displayPath?.includes('\\') ? '\\' : '/');

const partsOf = (path) => (path || '').split(/[\\/]+/).filter(Boolean);

// The last folder and the file, written with *separator*
export const folderAndFile = (path, separator = separatorOf(path)) =>
  partsOf(path).slice(-2).join(separator);

export const titleOf = (lib) =>
  lib.name || folderAndFile(lib.path, separatorOf(lib.display_path)) || '—';
