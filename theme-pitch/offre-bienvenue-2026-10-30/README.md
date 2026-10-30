# Offre WELCOME10 plus visible (30 oct. 2026)

Fichiers poussés sur le thème Pitch :
- `snippets/gul-offre-bienvenue.liquid` (nouveau) : bandeau accueil, carte fiche produit, carte panier, bouton « Copier ».
- `snippets/gul-stock-default.liquid` : ajout de `{% render 'gul-offre-bienvenue' %}` en dernière ligne.
- `sections/header-group.json` : barre d'annonce bordeaux #701C32, texte crème, 14 px ; WELCOME10 en première position (lien /discount/WELCOME10 qui applique le code), rotation 6 s.

Retour arrière :
- retirer la dernière ligne de `gul-stock-default.liquid` (le snippet peut rester) ;
- barre d'annonce d'avant : fond #1E1A17, texte 0.75rem, ordre « Livraison offerte dès 10 000 Fdj à Djibouti-ville » / « Livraison en 4 à 5 jours » / « -10 % sur votre première commande avec le code WELCOME10 » (lien best-sellers), rotation 5 s, marges 10 px.
