const express = require('express');
const path = require('path');
const fs = require('fs');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 3000;

// Try multiple possible root directories
const POSSIBLE_ROOTS = [
  process.cwd(),
  '/app',
  '/app/repo',
  path.join(process.cwd(), 'repo'),
  __dirname,
];

let ROOT_DIR = POSSIBLE_ROOTS.find(dir => {
  try {
    return fs.existsSync(path.join(dir, 'index.html'));
  } catch { return false; }
}) || process.cwd();

console.log('=== BTC Dashboard Server ===');
console.log('PORT:', PORT);
console.log('__dirname:', __dirname);
console.log('cwd:', process.cwd());
console.log('ROOT_DIR:', ROOT_DIR);
console.log('Files:', fs.readdirSync(ROOT_DIR).join(', '));

// Static files
app.use(express.static(ROOT_DIR));

// API: get market data
app.get('/data.json', (req, res) => {
  const url = 'https://lpcrnobolifrzwrkxoli.supabase.co/storage/v1/object/public/virt-data/market_data.json';
  https.get(url, { headers: { 'apikey': 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug' } }, (apiRes) => {
    let data = '';
    apiRes.on('data', chunk => data += chunk);
    apiRes.on('end', () => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Cache-Control', 'no-cache');
      try { res.json(JSON.parse(data)); } catch { res.status(500).send('Invalid JSON'); }
    });
  }).on('error', (e) => res.status(500).send('Proxy error: ' + e.message));
});

app.get('/favicon.ico', (req, res) => res.status(204).send());

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Running on http://0.0.0.0:${PORT}`);
});
