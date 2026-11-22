const fs = require('fs');
const src = fs.readFileSync(__dirname + '/correction-email.js', 'utf8').split('(function () {')[0];
const fixEmail = new Function(src + '; return fixEmail;')();
const cases = [
  ['ibahassan97@gamil.com', 'ibahassan97@gmail.com'], ['hidoyeelo@gmail.co', 'hidoyeelo@gmail.com'],
  ['a@GMAIL.COM', 'a@GMAIL.COM'], ['a.b@gmail.com ', 'a.b@gmail.com'], ['x@yahoo.fr', 'x@yahoo.fr'], ['bad', 'bad'], ['a@Gamil.Com', 'a@gmail.com']
];
let ok = true;
for (const [i, o] of cases) { const r = fixEmail(i); if (r !== o) { ok = false; console.log('FAIL', i, r, o); } }
console.log(ok ? 'OK' : 'ECHEC');
