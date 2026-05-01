const express = require('express');
const path = require('path');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 3000;

// Serve static files
app.use(express.static(__dirname));

// API: get market data from Supabase
app.get('/data.json', (req, res) => {
  const url = 'https://lpcrnobolifrzwrkxoli.supabase.co/storage/v1/object/public/virt-data/market_data.json';
  https.get(url, { headers: { 'apikey': 'sb_publishable_8gEsCRNRc7py6BmypYuRIw_sNtKooug' } }, (apiRes) => {
    let data = '';
    apiRes.on('data', chunk => data += chunk);
    apiRes.on('end', () => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Cache-Control', 'no-cache');
      res.json(JSON.parse(data));
    });
  }).on('error', () => res.status(500).send('Error'));
});

// Serve index.html for root
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`BTC Dashboard running on port ${PORT}`);
});
