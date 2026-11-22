/* Correction des fautes de frappe d'e-mail du popup « Obtenir 10 % » (9 nov. 2026).
   À coller dans snippets/gul-popup-bienvenue.liquid, dans le <script> existant,
   juste avant la dernière ligne « })(); ». Ne change rien d'autre. */
var DOMAIN_FIXES = {
  'gamil.com': 'gmail.com', 'gmial.com': 'gmail.com', 'gmai.com': 'gmail.com', 'gmal.com': 'gmail.com',
  'gnail.com': 'gmail.com', 'gmaill.com': 'gmail.com', 'gmail.co': 'gmail.com', 'gmail.con': 'gmail.com',
  'gmail.cm': 'gmail.com', 'gmail.om': 'gmail.com', 'gmail.coom': 'gmail.com', 'gmail.vom': 'gmail.com',
  'hotmial.com': 'hotmail.com', 'hotnail.com': 'hotmail.com', 'hotmail.con': 'hotmail.com',
  'yaho.com': 'yahoo.com', 'yahoo.con': 'yahoo.com', 'yahoo.fr.com': 'yahoo.fr',
  'outlok.com': 'outlook.com', 'outlook.con': 'outlook.com',
  'iclod.com': 'icloud.com', 'icloud.con': 'icloud.com'
};
function fixEmail(value) {
  var v = String(value || '').trim().replace(/\s+/g, '');
  var at = v.lastIndexOf('@');
  if (at < 1) return v;
  var domain = v.slice(at + 1).toLowerCase();
  return DOMAIN_FIXES[domain] ? v.slice(0, at + 1) + DOMAIN_FIXES[domain] : v;
}
(function () {
  var input = root.querySelector('input[type="email"]');
  var form = root.querySelector('form');
  if (!input || !form) return;
  var note = document.createElement('p');
  note.className = 'gul-wp__error';
  note.setAttribute('role', 'status');
  note.hidden = true;
  note.style.color = '#5A4136';
  input.insertAdjacentElement('afterend', note);
  function apply() {
    var fixed = fixEmail(input.value);
    if (fixed !== input.value) {
      var wrong = input.value.trim();
      input.value = fixed;
      note.textContent = 'Nous avons corrigé votre adresse : ' + fixed + ' (au lieu de ' + wrong + ').';
      note.hidden = false;
    }
  }
  input.addEventListener('blur', apply);
  form.addEventListener('submit', apply, true);
})();
