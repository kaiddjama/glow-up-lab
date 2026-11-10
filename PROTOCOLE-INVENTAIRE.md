# Protocole inventaire Aimé Essentials (référence unique)

Ce fichier GitHub est la SEULE version qui fait foi (le fichier du projet ne fait que pointer ici, donc aucun décalage possible). Dépôt public : ni formule de prix, ni identifiants, ni adresse complète (ils sont dans les secrets du dépôt et les notes privées du projet). À chaque modification du code, la vérification « Protocol matches the code » échoue si ce fichier ne dit plus la même chose que le code (réglages, heures des contrôles).

Créé le 5 nov 2026 à partir des consignes de Hoodo et des erreurs passées. Ce fichier est suivi à la lettre à chaque contrôle.
On ne le modifie qu'en AJOUTANT ce qu'on apprend d'une erreur, daté, dans le journal en bas (et en mettant la règle à jour au même endroit).
Rien n'y est écrit sans avoir été vérifié ; ce qui n'est pas vérifié est marqué « à vérifier ».

## 1. Consignes de Hoodo (non négociables)
- Source unique : Amazon.ae (noon abandonné le 30 oct).
- Adresse de lecture : Dubaï, quartier Ras Al Khor (adresse complète gardée hors du dépôt public).
- 5 contrôles complets par jour, toutes les variantes ; chaque produit lié à son stock.
- Masquer l'indisponible au fur et à mesure (toutes les 50 pages lues) ; remises en vente et prix à la fin du contrôle.
- Autopilote : corriger soi-même les échecs ; prévenir Hoodo seulement si l'échec persiste ; en dernier recours, une ALERTE qui la prévient vraiment.
- Dans le doute : masquer.
- Ne jamais : utiliser le Chrome du Mac (considéré éteint, 5 nov) ; dépenser ; rembourser ; écrire aux clientes sans elle ; toucher un autre dépôt que glow-up-lab ; fusionner ou fermer la PR #15.
- Heures données à Hoodo : heure de Djibouti (GMT+3).

## 2. Quand une variante est vendable
Page Amazon.ae lue avec l'adresse de Dubaï ET en stock ET date de livraison GRATUITE à Dubaï de 2 jours maximum (MAX_DAYS=2 ; l'option express payante n'est jamais lue).
Tout le reste = Épuisé : page sans date de livraison (depuis le 5 nov), délai trop long, vendeur en liste de blocage (seller-hold.json), variante sans ASIN.
Délai affiché en boutique : « 4 à 5 jours » (2 jours jusqu'à Dubaï + 2 à 3 jours Dubaï → Djibouti).

## 3. Quand un produit est visible
- Toutes ses variantes Épuisé → masqué (brouillon + tag epuise-auto). Remis en ligne seulement par le système, quand une variante redevient vendable.
- Jamais lu sur Amazon.ae (pas de supplier.checked_at) → masqué sous 30 min, lu tout de suite (produits créés depuis moins de 3 jours), remis en ligne seulement si vendable.
- Les nouveaux produits doivent être créés en brouillon par les fils d'ajout.
- Un produit masqué (brouillon) disparaît de tous les thèmes, y compris un aperçu de thème.
- Produit actif, vérifié et vendable mais non publié sur le canal Boutique en ligne (page en 404) → publié automatiquement.

## 4. Déroulé (GitHub Actions, dépôt glow-up-lab)
| Quand (Djibouti) | Quoi |
|---|---|
| 03:07, 08:07, 13:07, 18:07, 22:07 | Contrôle complet (stock-sync.yml) : 16 lecteurs, masquage toutes les 50 pages, relecture lente des pages ratées ou sans date, couverture (relit 2 fois ce qui n'est pas vérifié, puis met en Épuisé ce qui n'a pas été vérifié depuis 6 h), masquage des produits entièrement épuisés |
| 03:37, 08:37, 13:37, 18:37, 22:37 | Tâche de secours : relance le contrôle et le contrôle des commandes s'ils ne sont pas partis |
| toutes les 30 min et après chaque contrôle des commandes | park-soldout.yml : masque les produits jamais vérifiés, lit les nouveaux produits, remet en ligne ce qui est vendable |
| toutes les 10 min | Contrôle des commandes : étiquettes amazon-ok / amazon-ko / amazon-incertain |

## 5. Garde-fous contre les mauvaises lectures
- Plus de 35 % des variantes lues passent en Épuisé d'un coup → aucun changement de stock (lecture probablement faussée) + alerte.
- Plus de 60 % du catalogue serait masqué → rien n'est masqué + alerte.
- Variation de prix de plus de 150 % → prix retenu pour vérification.
- Plus de 150 variantes sans ASIN à couper d'un coup → rien n'est changé.
- Adresse de Dubaï non prise au démarrage → 3 essais, puis le lecteur s'arrête sans rien changer (alerte).
- Adresse de Dubaï perdue pendant la lecture → le lecteur s'arrête, rien n'est changé pour le reste.
- CAPTCHA Amazon → pause d'1 à 2 min ; 5 de suite → le lecteur s'arrête (le reste est relu par la couverture).

## 6. Alertes
- Échec non résolu (contrôle, couverture, masquage, garde-fou déclenché, erreurs Shopify) → issue GitHub « alerte-inventaire » dans glow-up-lab : GitHub envoie un e-mail et une notification de l'appli GitHub au propriétaire du dépôt. Au plus un rappel toutes les 3 h.
- Contrôle du matin (03:40 environ) : lit le résultat de la nuit ; message à Hoodo si un échec persiste.

## 7. Obstacles connus et voie retenue
| Obstacle | Voie retenue | Statut |
|---|---|---|
| Contrôle anti-robot Amazon | Lecture lente, pauses, relectures ; jamais de contournement de la détection | En place |
| Le robot ne voit pas le compte connecté de Hoodo (Prime) : dates différentes | Liste de blocage pour les cas signalés ; piste : API officielle Amazon (Associates / Creators API) | À étudier, rien de payé, rien affirmé |
| Pages sans date de livraison | Relecture lente une fois, puis considérées indisponibles | En place |
| Variantes sans ASIN (36 produits le 5 nov) | Restent masquées tant qu'elles ne sont pas reliées | À relier |
| Exécutions GitHub sautées | Tâche de secours 5 fois par jour | En place |
| Débit Shopify limité | 30 tentatives avec attente | En place |

## 8. Réglages (variables, sans toucher au code)
MAX_DAYS=2 · STOCK_GUARD=0,35 · NO_DATE_KEEPS=0 (1 = l'ancienne règle « page sans date laissée telle quelle ») · RETRY_MAX=40.

## 9. Journal des leçons (on ajoute, on n'efface pas)
- 22 oct : règle « vendeur » retirée (SELLER_RULE=0).
- 2 nov : le robot lisait l'option express payante (1 jour) au lieu de la date gratuite → lecture de la date gratuite seulement, 2 jours (PR #33).
- 2 nov : adresse réglée sur Ras Al Khor (PR #31). Majestic Pure : le compte de Hoodo voit 8 nov → liste de blocage (PR #32).
- 3-4 nov : plantages dus au débit Shopify → 30 tentatives (PR #35). Firecrawl testé et écarté (ne règle pas l'adresse, bloqué 5 pages sur 6).
- 5 nov : produits entièrement épuisés restés visibles (Tree Hut) → masquage automatique du produit (PR #39), 239 produits masqués.
- 5 nov : eos commandée (#1019) alors qu'épuisée : mise en ligne sans lecture + page sans date laissée en vente → page sans date = indisponible, produit jamais lu masqué sous 30 min (PR #40) ; relecture des pages ratées, lecture des nouveaux produits, alerte GitHub (PR #41).
- 5 nov : Chrome du Mac interdit (Hoodo).
- 5 nov : protocole tenu dans GitHub, vérifié automatiquement contre le code à chaque modification (Hoodo : pas de décalage d'informations).
- 5 nov : un lecteur sur 16 n'a pas pris l'adresse de Dubaï au démarrage (06:30 UTC) → 3 essais. Le contrôle de 13:07 et le masquage toutes les 30 min n'ont pas été lancés par GitHub → masquage aussi après chaque contrôle des commandes. La formule de prix apparaissait dans les journaux publics (variable non masquée) → à mettre en secret PRICE_FORMULA.
- 5 nov : le contrôle des commandes (planifié toutes les 10 min à :00) n'a pas été lancé par GitHub de 08:32 à 15:40 UTC → minutes décalées (:04, :14…) ; la tâche de secours le relance s'il manque depuis plus de 2 h (toujours avec dry_run=false).
- 5 nov : deux contrôles (18:39 et 20:58 Djibouti) en échec partiel : Shopify n'a pas répondu à temps (pas de nouvel essai) et l'installation du navigateur a dépassé 8 min → 6 essais sur les coupures Shopify, installation du navigateur en 3 essais (25 min max).
- 5 nov : un produit créé par API (productSet) peut être ACTIVE mais non publié sur la Boutique en ligne : sa page répond 404 (Owala) → park_soldout.py publie tout produit actif, vérifié et vendable qui ne l'est pas.
- 5 nov (soir) : alerte #49, 2 lecteurs sans navigateur : l'installation « avec dépendances » téléchargeait des polices très lentement depuis le miroir Ubuntu, et l'apt-get interrompu gardait son verrou (les nouveaux essais échouaient) → navigateur installé sans dépendances système (déjà présentes), qui ne sont ajoutées que si Chromium ne démarre pas (.github/install-browser.sh).
- 9 nov : alerte #58, un lecteur sur 16 (contrôle de 13h37 Djibouti) coupé par GitHub (« The hosted runner lost communication with the server ») : panne de la machine GitHub, pas du script. Rien à corriger : la vérification de couverture masque ce qui n'est pas relu en 6 h, et le contrôle suivant (16h46) a tout relu (0 variante non vérifiée) → alerte fermée. Règle : si un seul lecteur tombe pour cette raison et que le contrôle suivant est complet, on ferme l'alerte sans changer le code.

## 10. Deuxième fournisseur : MedX Pharmacy (medxpharmacy.com, Dubaï), ajouté le 10 nov 2026
Compléments sport (pré-workout, shots, whey, isolats, boissons protéinées, barres, gainers). Une variante MedX se reconnaît à son SKU `MEDX-<alias de la fiche MedX>`. Le code est dans `stock-sync/medx.py`, `medx_sync.py`, `medx_create.py` ; l'Amazon n'est pas touché (le contrôle Amazon ignore les SKU MEDX).
- Lecture : page produit publique en HTML (pas de navigateur, pas de CAPTCHA), qui donne le stock exact de la pharmacie, le prix en AED (TVA comprise) et l'état de publication. MedX livre à Dubaï en 12 à 24 h : étape Dubaï = 1 jour, délai affiché « 4 à 5 jours ».
- Vendable : page lue ET publiée ET stock d'au moins MEDX_MIN_QTY=8. Une variante déjà Épuisé ne revient que si le stock atteint MEDX_BACK_QTY=12 (pas de va-et-vient). Page illisible : rien ne change. Fiche disparue (404) ou retirée : Épuisé.
- Création d'une variante : stock d'au moins 20 le jour de l'ajout, sauf pour les produits que Hoodo a approuvés même à stock bas ou nul (`low_ok` dans `medx/selection.json`) : créés en Épuisé, ils se mettent en vente seuls quand MedX atteint 12 en stock et repassent Épuisé sous 8 (contrôle toutes les 10 minutes). Un produit approuvé mais sans stock à la mise en ligne reste masqué (tag epuise-auto) et est remis en ligne par `park_soldout.py`. Les nouveaux produits sont créés en brouillon (tag medx-revue), montrés à Hoodo, puis mis en ligne sur son accord seulement.
- Rythme : `medx-sync.yml` toutes les 10 minutes (à partir de :03). Ensuite `coverage.py medx` met en Épuisé toute variante MedX en vente non lue depuis MEDX_STALE_HOURS=1 heure, puis `park_soldout.py` masque les produits entièrement épuisés (tag epuise-auto) et les remet en ligne.
- Garde-fous : plus de 35 % des variantes lues qui passent Épuisé d'un coup, ou plus de la moitié des pages illisibles, ou des erreurs Shopify : alerte GitHub (le masquage est appliqué quand même, c'est le sens sûr). Prix : variation de plus de 150 % retenue pour vérification.
- Poids et prix : le prix vient de la formule de prix (secret du dépôt, jamais écrite ici) appliquée au prix MedX et au poids d'expédition de la variante (poids de la variante d'abord, sinon celui de la fiche). Une fiche qui regroupe plusieurs formats porte un poids par variante.
- Produit mixte (variantes Amazon et MedX sur la même fiche) : la synchro MedX ne touche que ses propres variantes et laisse les champs fournisseur de la fiche à la synchro Amazon.
- Contrôle des commandes : une ligne MedX est vérifiée sur la page MedX (stock au moins MEDX_MIN_QTY), sans navigateur ; sinon la commande passe en amazon-ko (même étiquette) avec le motif « stock MedX insuffisant ».
- Achat : la commande se passe à la main sur medxpharmacy.com, livrée à l'adresse de Dubaï (adresse hors du dépôt public), puis acheminée vers Djibouti comme pour l'Amazon.
- Réglages (variables, sans toucher au code) : MEDX_MIN_QTY=8 · MEDX_BACK_QTY=12 · MEDX_STALE_HOURS=1 · MEDX_MIN_CREATE_QTY=20.
- 10 nov : premier ajout, 20 gammes / 51 variantes. Photos : seulement des emballages propres ; écartées les photos avec le shaker « MedX » offert ou tronquées, et une photo dont le parfum ne correspondait pas à la fiche (Kevin Levrone Gold Iso, vanille affichée pour un chocolat).
