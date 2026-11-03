import { createSHA256 } from 'hash-wasm';

// The SHA-256 of a file on the person's own computer, worked out in the
// browser.
//
// Not sent to the server to hash: the server can only open paths on its own
// disks, so a path to someone's Desktop would be looked for on the host's
// Desktop instead. Reading the file here means anyone can check whether a
// library they have locally is already catalogued, and the file itself never
// leaves their machine -- only the hash is used to search.
//
// hash-wasm rather than the browser's own crypto.subtle, which only exists on
// HTTPS or localhost; SpecVault is reached over plain HTTP on the network.
// It is also the only way to hash in pieces: crypto.subtle wants the whole
// file in memory at once, and libraries run to gigabytes.

const CHUNK = 8 * 1024 * 1024;

export async function sha256OfFile(file, onProgress) {
  const hasher = await createSHA256();
  hasher.init();
  for (let offset = 0; offset < file.size; offset += CHUNK) {
    const piece = await file.slice(offset, offset + CHUNK).arrayBuffer();
    hasher.update(new Uint8Array(piece));
    onProgress?.(Math.min(1, (offset + CHUNK) / file.size));
  }
  return hasher.digest('hex');
}
