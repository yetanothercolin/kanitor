#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {installedKanbn, fingerprint} = require('../bridge.cjs');

async function resolveSubject(root, ref, watch = false) {
  const configs = ['kanbn.json', 'kanbn.yml'].map(name => path.join(root, name));
  const configBefore = watch ? fingerprint(configs, []) : null;
  if (!ref || ref.includes('/') || ref.includes('\\') || ref.includes('\0') || ['.', '..'].includes(ref)) {
    return {state: 'unresolved'};
  }
  const Kanbn = installedKanbn();
  const board = new Kanbn(root, {actions: false});
  if (!(await board.initialised())) throw new Error('No initialized kanbn workspace at ' + root);
  const taskPath = path.join(await board.getTaskFolderPath(), ref.endsWith('.md') ? ref : ref + '.md');
  const archived = path.join(await board.getArchiveFolderPath(), ref.endsWith('.md') ? ref : ref + '.md');
  const files = [...configs, await board.getIndexPath(), taskPath, archived];
  const before = watch ? fingerprint(files, []) : null;
  let state = 'unresolved';
  if (fs.existsSync(taskPath)) {
    await board.loadTask(ref);
    state = 'active';
  } else if (fs.existsSync(archived)) {
    await board.loadArchivedTask(ref);
    state = 'archived';
  }
  if (watch && (before !== fingerprint(files, []) || configBefore !== fingerprint(configs, []))) {
    throw new Error('Subject files changed during lookup; retrying.');
  }
  return watch ? {state, watch: {files, signature: JSON.parse(before)}} : {state};
}

if (require.main === module) {
  resolveSubject(path.resolve(process.argv[2]), process.argv[3], process.argv[4] === '--watch').then(
    value => process.stdout.write(JSON.stringify(value)),
    error => { console.error(error.message); process.exitCode = 1; }
  );
}
module.exports = {resolveSubject};
