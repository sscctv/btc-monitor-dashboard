const express = require('express');
const path = require('path');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 3000;
const ROOT_DIR = process.env.RAILWAY_GIT_DIR || __dirname;

// Static files - serve from correct directory
app.use(express.static(ROOT_DIR));

// Serve index.html for root
app.get('/', (req, res) => {
  res.sendFile(path.join(ROOT_DIR, 'index.html'));
});

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
  }).on('error', (e) => {
    res.status(500).send('Proxy error: ' + e.message);
  });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`BTC Dashboard running on ${PORT} from ${ROOT_DIR}`);
  console.log(`Files in ROOT_DIR: ${require('fs').readdirSync(ROOT_DIR).join(', ')}`);
});
