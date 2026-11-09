# Popup « Obtenir 10 % » : correction automatique des fautes de frappe d'e-mail

Cause constatée le 9 nov. : des clientes tapent « gamil.com » ou « gmail.co » ; le code part dans le vide et elles se réinscrivent (ex. ibahassan97@gamil.com, hidoyeelo@gmail.co).

`correction-email.js` corrige le domaine (gmail, hotmail, yahoo, outlook, icloud) quand la cliente quitte le champ ou valide, et affiche « Nous avons corrigé votre adresse ». `test.js` vérifie la logique (`node test.js`).

## Application (à faire dans le thème Pitch publié, l'API l'interdit)
Admin Shopify > Boutique en ligne > Thèmes > Pitch > Modifier le code > `snippets/gul-popup-bienvenue.liquid`.
Coller le contenu de `correction-email.js` dans le `<script>` du bas, juste avant la dernière ligne `})();`.
Retour arrière : supprimer le bloc collé.
