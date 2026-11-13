# CLAUDE.md (lu par des agents IA uniquement)
Repo PUBLIC, boutique Aimé Essentials (Shopify, Djibouti, Fdj). Contenu: `stock-sync/` (synchro stock/prix Amazon.ae, GitHub Actions `.github/workflows/`), `theme-pitch/` (copies de fichiers du thème). Répondre à Hoodo en français, bref.

## Avant de toucher à la synchro
- Lire `PROTOCOLE-INVENTAIRE.md` : référence UNIQUE (règles de Hoodo, vendabilité d'une variante, garde-fous, registre des erreurs sect. 12). Ne pas dupliquer ni changer ses règles ; seulement AJOUTER, daté, selon ses consignes d'en-tête. `stock-sync/protocol_check.py` vérifie l'alignement code/protocole.
- Réglages = variables d'environnement des workflows ; changement = PR.
- Changement de code: additif, testé hors ligne (`stock-sync/test_*.py`), sans régression prouvée avant mise en service.

## Objectif ultime (Hoodo, 11 nov)
Rien ne casse, business pérenne. Blocage (Amazon.ae, Actions, Shopify) = solution durable avec secours, jamais règle brutale.

## Interdits
- Rien de privé dans le dépôt (formule de prix, identifiants, adresse complète, numéros) : secrets/variables GitHub.
- Aucun autre dépôt. Ne jamais fusionner/fermer la PR #15 (boîte d'alertes).
- Ne jamais dépenser, rembourser, écrire aux clientes sans Hoodo. Pas de Chrome du Mac : tout dans le cloud/GitHub.
- Jamais de produit en ligne sans stock ET délai lus ; nouveaux produits en brouillon.

## PR
Brouillon ; dire quoi/pourquoi/comment vérifié. Hoodo fusionne.
