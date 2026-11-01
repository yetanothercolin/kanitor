#!/usr/bin/env node
'use strict';
// Only native read APIs belong here. No CLI actions, hydration, or board writes.
const fs = require('node:fs');
const path = require('node:path');

function installedKanbn() {
  for (const folder of (process.env.PATH || '').split(path.delimiter)) {
    const executable = path.join(folder, 'kanbn');
    try {
      fs.accessSync(executable, fs.constants.X_OK);
    } catch { continue; }
    let directory = path.dirname(fs.realpathSync(executable));
    while (directory !== path.dirname(directory)) {
      const manifest = path.join(directory, 'package.json');
      if (fs.existsSync(manifest)) {
        const pkg = JSON.parse(fs.readFileSync(manifest, 'utf8'));
        if (pkg.name === '@basementuniverse/kanbn') return require(directory).Kanbn;
      }
      directory = path.dirname(directory);
    }
  }
  throw new Error('kanbn was not found on PATH. Install @basementuniverse/kanbn and try again.');
}

// Check only relevant files, without following directory symlinks or visiting archives.
function fingerprint(files, folders) {
  const paths = new Set(files);
  for (const folder of folders) {
    if (!fs.existsSync(folder)) continue;
    for (const entry of fs.readdirSync(folder, {withFileTypes: true})) {
      if ((entry.isFile() || entry.isSymbolicLink()) && entry.name.endsWith('.md')) {
        paths.add(path.join(folder, entry.name));
      }
    }
  }
  return JSON.stringify([...paths].sort().map(file => {
    try {
      const stat = fs.statSync(file, {bigint: true});
      return [file, String(stat.ino), String(stat.size), String(stat.mtimeNs)];
    } catch (error) {
      if (error.code === 'ENOENT') return [file, null];
      throw error;
    }
  }));
}

async function readSnapshot(root) {
  const configNames = ['.kanitor.json', '.kanitor.yml', '.kanitor.yaml'];
  const files = ['kanbn.yml', 'kanbn.json', ...configNames].map(name => path.join(root, name));
  // Configless projects can inherit settings from a declaring ancestor.
  // Watch missing filenames too, so adding an override or roster reloads live.
  if (!configNames.some(name => fs.existsSync(path.join(root, name)))) {
    let parent = path.dirname(root);
    while (parent !== root) {
      files.push(...configNames.map(name => path.join(parent, name)));
      const next = path.dirname(parent);
      if (next === parent) break;
      parent = next;
    }
  }
  const configBefore = fingerprint(files, []);
  const Kanbn = installedKanbn();
  const main = new Kanbn(root, {actions: false});
  if (typeof main.listBoards !== 'function') {
    throw new Error('This kanbn installation lacks the multi-board API. Kanitor requires kanbn 2.6.1 or newer.');
  }
  if (!(await main.initialised())) throw new Error(`No initialized kanbn workspace at ${root}`);
  const folders = [await main.getMainFolder(), await main.getTaskFolderPath()];
  const before = fingerprint(files, folders);
  const fileStats = new Map(JSON.parse(before).map(row => [row[0], row]));
  const definitions = await main.listBoards();
  const taskCache = new Map();
  const taskErrors = new Map();
  const warnings = [];
  const boards = [];
  for (const definition of definitions) {
    const board = definition.main ? main : main.board(definition.slug);
    const index = await board.getIndex();
    const tasks = [];
    const seen = new Set();
    for (const [column, ids] of Object.entries(index.columns)) {
      for (const id of ids) {
        if (seen.has(id)) throw new Error(`Duplicate card ${id} on board ${definition.slug}`);
        seen.add(id);
        // Shared card files are read once; column membership always belongs to this board.
        if (!taskCache.has(id) && !taskErrors.has(id)) {
          try {
            taskCache.set(id, await board.getTask(id));
          } catch (error) {
            taskErrors.set(id, error.message);
          }
        }
        if (taskErrors.has(id)) {
          warnings.push({board: definition.slug, task: id, error: taskErrors.get(id)});
          continue;
        }
        tasks.push({...taskCache.get(id), id, column, board: definition.slug});
      }
    }
    const boardStat = fileStats.get(definition.path);
    let latest = boardStat?.[3] ? Number(BigInt(boardStat[3]) / 1000000n) : 0;
    for (const task of tasks) {
      const raw = task.metadata?.updated;
      const value = typeof raw === 'string' ? Date.parse(raw) : NaN;
      if (Number.isFinite(value)) latest = Math.max(latest, value);
    }
    const updated = new Date(latest).toISOString();
    boards.push({...definition, updated, options: index.options, columns: Object.keys(index.columns), tasks});
  }
  if (before !== fingerprint(files, folders) || configBefore !== fingerprint(files, [])) {
    throw new Error('Kanbn files changed during the read; retrying.');
  }
  if (!boards.length) throw new Error('No readable kanbn boards found. Check kanbn validate --all-boards.');
  // Python attaches customization using the shared JSON/YAML config loader.
  return {source: 'kanbn', readOnly: true, root, boards, warnings,
    watch: {files, folders, signature: JSON.parse(before)}};
}

if (require.main === module) {
  readSnapshot(path.resolve(process.argv[2] || '.')).then(
    snapshot => process.stdout.write(JSON.stringify(snapshot)),
    error => { console.error(error.message); process.exitCode = 1; }
  );
}
module.exports = {readSnapshot, fingerprint, installedKanbn};
