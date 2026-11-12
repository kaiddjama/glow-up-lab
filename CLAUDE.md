# glow-up-lab (consignes pour Claude)

Dépôt PUBLIC de la boutique Aimé Essentials (Shopify, Djibouti, prix en Fdj). Il contient la synchro stock/prix Amazon.ae (`stock-sync/`, lancée par GitHub Actions dans `.github/workflows/`) et des copies de fichiers du thème Pitch (`theme-pitch/`). Répondre à Hoodo en français, de façon brève.

## À lire avant de toucher à la synchro
- **`PROTOCOLE-INVENTAIRE.md` est la référence unique** (règles de Hoodo, quand une variante est vendable, garde-fous, registre des erreurs). Ne pas le recopier ici ni en changer les règles : on l'enrichit seulement, daté, en suivant les consignes en tête de ce fichier. `stock-sync/protocol_check.py` vérifie qu'il reste aligné avec le code.
- Réglages = variables d'environnement des workflows ; les changer passe par une pull request.
- Une modification du code de synchro doit être additive, testée hors ligne (`stock-sync/test_*.py`) et prouvée sans régression avant mise en service.

## Objectif ultime (Hoodo, 11 nov)
Que rien ne casse et que le business soit pérenne. Pas de décision brutale : pour tout blocage (Amazon.ae, GitHub Actions, Shopify), chercher des solutions durables avec des secours, pas une règle isolée.

## Interdits
- Rien de privé dans ce dépôt : ni formule de prix, ni identifiants, ni adresse complète, ni numéros. Tout cela vit dans les secrets et variables GitHub.
- Ne jamais créer ni toucher un autre dépôt.
- Ne jamais fusionner ni fermer la PR #15 (boîte d'alertes).
- Ne jamais dépenser, rembourser ni écrire aux clientes sans Hoodo.
- Ne pas utiliser le Chrome du Mac : tout tourne dans le cloud / GitHub.
- Ne jamais mettre un produit en ligne sans lecture réussie du stock ET du délai ; nouveaux produits en brouillon.

## Pull requests
Ouvrir en brouillon, décrire ce qui change et comment c'est vérifié. Hoodo décide de la fusion.
