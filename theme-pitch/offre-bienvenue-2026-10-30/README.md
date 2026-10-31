# Offre WELCOME10 plus visible (30 oct. 2026)

Fichiers poussés sur le thème Pitch :
- `snippets/gul-offre-bienvenue.liquid` (nouveau) : bandeau accueil, carte fiche produit, carte panier ; chaque bouton ouvre le popup (le code n'est jamais affiché, il part par email).
- `snippets/gul-popup-bienvenue.liquid` : ajout d'une ouverture à la demande (`window.gulOpenWelcome`, lien `#offre-bienvenue`).
- `snippets/gul-stock-default.liquid` : ajout de `{% render 'gul-offre-bienvenue' %}` en dernière ligne.
- `sections/header-group.json` : barre d'annonce bordeaux #701C32, texte crème, 14 px ; WELCOME10 en première position (lien #offre-bienvenue qui ouvre le popup, sans afficher le code), rotation 6 s.

Retour arrière :
- retirer la dernière ligne de `gul-stock-default.liquid` (le snippet peut rester) ;
- barre d'annonce d'avant : fond #1E1A17, texte 0.75rem, ordre « Livraison offerte dès 10 000 Fdj à Djibouti-ville » / « Livraison en 4 à 5 jours » / « -10 % sur votre première commande avec le code WELCOME10 » (lien best-sellers), rotation 5 s, marges 10 px.

À changer aussi dans l'éditeur du thème (accueil, bloc newsletter) : « Code WELCOME10 et nouveautés dans votre boîte mail. » devient « Votre code de bienvenue et nos nouveautés dans votre boîte mail. » (le code ne doit apparaître nulle part sur le site).

Mise à jour 30 oct. (soir) : le snippet en ligne `gul-offre-bienvenue.liquid` (10 599 octets, MD5 765e3cfa…) est une version redessinée directement sur le thème (panneau sable avec arche « -10 % », titre « Un cadeau pour votre première commande »). Elle remplace celle de ce dossier ; les sauvegardes v1 et v2 sont sur le Mac de Hoodo (~/Desktop/Glow Up Lab/sauvegardes-theme-2026-10-30/). Le fichier de ce dossier n'est plus la source de vérité : relire le thème avant toute modification.
