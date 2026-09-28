import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';

const output = 'zepp_report/static/dist';
await build({
  entryPoints: ['zepp_report/static/app.js', 'zepp_report/static/beta.js'],
  bundle: true,
  minify: true,
  outdir: output,
  target: ['es2020'],
  legalComments: 'eof',
});

// Keep notices beside the locally served bundle, including ECharts' embedded D3 code.
const notices = {
  echarts: ['LICENSE', 'NOTICE', 'licenses/LICENSE-d3'],
  zrender: ['LICENSE'],
  flatpickr: ['LICENSE.md'],
  tslib: ['LICENSE.txt', 'CopyrightNotice.txt'],
};
const sections = [];
for (const [name, files] of Object.entries(notices)) {
  const manifest = JSON.parse(await readFile(`node_modules/${name}/package.json`, 'utf8'));
  for (const file of files) {
    const text = await readFile(`node_modules/${name}/${file}`, 'utf8');
    sections.push(`${name} ${manifest.version} — ${file}\n${'='.repeat(72)}\n${text}`);
  }
}
await writeFile(`${output}/THIRD_PARTY_LICENSES.txt`, sections.join('\n\n'));
