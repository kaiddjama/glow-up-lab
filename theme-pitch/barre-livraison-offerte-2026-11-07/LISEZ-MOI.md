# Barre « livraison offerte dès 10 000 Fdj » (thème Pitch)

Objectif : pousser les paniers vers 10 000 Fdj (livraison offerte à Djibouti-ville) avec un message « Plus que X Fdj » et une barre de progression, dans le tiroir du panier et sur la page panier.

Le thème en ligne ne peut pas être modifié par l'API (écriture bloquée sur le thème publié) : à appliquer dans Shopify > Boutique en ligne > Thèmes > Pitch > Modifier le code.

1. Créer le fichier `snippets/free-shipping-bar.liquid` avec le contenu de `free-shipping-bar.liquid` (ce dossier).
2. `snippets/cart-drawer.liquid` : juste avant la ligne
   `{% render 'cart-summary', section_id: 'cart-drawer-section' %}`
   ajouter la ligne
   `{% render 'free-shipping-bar' %}`
3. `sections/main-cart.liquid` : dans le bloc
   `<div class="cart-page__title">` ... `{%- content_for 'block', id: 'cart-page-title', type: '_cart-title' %}`
   ajouter après cette ligne (version non vide, pas celle du `<template>`)
   `{% render 'free-shipping-bar' %}`

Retour arrière : supprimer les deux lignes `{% render 'free-shipping-bar' %}`.
Seuil : 1000000 (= 10 000 Fdj, Shopify compte en centièmes). Le seuil correspond au tarif Djibouti-ville ; Balbala reste à 750 Fdj.
