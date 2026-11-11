# Protocole inventaire Aimé Essentials (référence unique)

Ce fichier GitHub est la SEULE version qui fait foi (le fichier du projet ne fait que pointer ici, donc aucun décalage possible). Dépôt public : ni formule de prix, ni identifiants, ni adresse complète (ils sont dans les secrets du dépôt et les notes privées du projet). À chaque modification du code, la vérification « Protocol matches the code » échoue si ce fichier ne dit plus la même chose que le code (réglages, heures des contrôles).

Créé le 5 nov 2026 à partir des consignes de Hoodo et des erreurs passées. Ce fichier est suivi à la lettre à chaque contrôle.
On ne le modifie qu'en AJOUTANT ce qu'on apprend d'une erreur, daté, dans le journal en bas (et en mettant la règle à jour au même endroit).
Apprendre d'une erreur (depuis le 11 nov), c'est quatre gestes, toujours les mêmes : 1) une ligne dans le registre des erreurs (section 12), dans la bonne colonne : vente à tort ou masquage à tort ; 2) la cause mesurée sur de vraies pages et sur les rapports des contrôles, pas supposée ; 3) la règle corrigée ici et dans le code ; 4) un test hors ligne qui rejoue l'erreur, pour qu'elle ne revienne pas.
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
Page Amazon.ae lue avec l'adresse de Dubaï ET en stock ET date de livraison à Dubaï de 2 jours maximum (MAX_DAYS=2).
- Quelle date compte (depuis le 11 nov) : celle que le compte de Hoodo obtient, pas celle d'un visiteur sans compte. Offre expédiée par Amazon lui-même (« Fulfilled by Amazon », quel que soit le vendeur, ou « Shipper / Seller Amazon.ae ») : la date « Or fastest delivery » compte, comme la date gratuite. Offre expédiée par le vendeur, « Delivered by Amazon.ae » ou import (Amazon US / UK) : la date gratuite ; à défaut, une livraison standard payante. Les options Rush, « Overnight » et « même jour sur créneau » ne comptent jamais.
- Tolérance du soir (depuis le 11 nov) : de 19 h à minuit à Dubaï (18 h à 23 h à Djibouti), les dates d'Amazon.ae glissent d'un jour puis reviennent après minuit. Pendant ces heures, une variante DÉJÀ EN VENTE garde 1 jour de plus (3 jours au lieu de 2). Une variante en Épuisé ne revient qu'avec la règle stricte (2 jours), à toute heure : la tolérance ne remet jamais rien en vente, et un article vraiment lent sort au premier contrôle du matin. L'étiquette de délai de la boutique ne bouge pas.
Tout le reste = Épuisé : stock presque fini sur Amazon.ae (« Only N left in stock » avec N ≤ 3, LOW_STOCK_MAX=3, depuis le 10 nov ; une variante sortie pour cette raison ne revient qu'au-dessus de 5 unités ou sans mention « Only N left », LOW_STOCK_BACK=5, depuis le 11 nov, pour ne plus entrer et sortir à chaque contrôle), page sans date de livraison (depuis le 5 nov), délai trop long, article retenu à la main (voir ci-dessous), variante sans ASIN, fiche supprimée sur Amazon.ae, page qui affiche un AUTRE article (un autre ASIN que celui demandé).
- Souplesse (Hoodo, 10 nov) : le vendeur n'est jamais un motif de masquage, ni un titre, une description ou un nom de teinte qui change sur le même ASIN. Seule la preuve d'un autre article masque (autre ASIN affiché, fiche supprimée). Les noms d'options différents sont listés dans le rapport, pour information.
- Plusieurs offres dans la même page (deux vendeurs) : la première offre achetable dans les règles est retenue, avec son prix.
- Livraison : la date la plus proche parmi celles qui comptent (voir ci-dessus) ; s'il n'existe qu'une livraison standard PAYANTE, sa date compte et ses frais sont ajoutés au prix d'achat avant la formule. Précommande ou « disponible à partir du… » = pas en stock.
- Motif noté (depuis le 11 nov) : chaque variante en Épuisé porte son motif dans le métachamp `supplier.sync_state` (« why » : rupture, delai:3, delai:4+, stock-bas, sans-date, retenue, pause-commande, prix, autre-article, fiche-supprimee). L'audit (toutes les 30 min) et chaque rapport de contrôle comptent les variantes en Épuisé et les produits masqués par motif.
- Retenue à la main : étiquette produit Shopify `bloque` (tout le produit) ou `bloque:B0XXXXXXXX` (une variante), ou l'ASIN dans stock-sync/seller-hold.json. Une variante retenue passe en Épuisé avant toute lecture et n'est jamais remise en vente tant que la retenue existe.
- Après une commande amazon-ko pour une raison de STOCK (rupture, stock presque fini, fiche supprimée ou remplacée), la variante reste en Épuisé 24 h même si le robot la relit « disponible » (commandes #1014, #1040). Pour une raison de DATE (trop lent, pas de date), pas de blocage de 24 h : le contrôle de stock suivant décide (depuis le 11 nov, commande #1048).
- Second fournisseur (Hoodo, 10 nov) : une variante Amazon.ae peut porter le métachamp `supplier.fallback` = `PSAE-<handle>` ou `MEDX-<alias>`. Amazon.ae d'abord ; s'il ne peut pas la vendre et que ce fournisseur le peut, elle reste en vente à son prix (produit étiqueté `source-2`), confirmée toutes les 10 min (fallback-sync.yml), et repasse sur Amazon.ae dès qu'il peut la vendre.
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
| toutes les 30 min (:23 et :53) et après chaque contrôle complet | inventory-audit.yml : audit de TOUS les produits (hors archivés) : suivi du stock activé (corrigé automatiquement), Épuisé réellement non commandable, produits actifs jamais lus ou non relus depuis 8 h, variantes en vente sans ASIN ni référence d'un autre fournisseur (les SKU MEDX- et PSAE- sont lus par leurs propres contrôles, les cartes cadeaux sont ignorées), produits non publiés (404), prix absent ; tableau « Pourquoi c'est en Épuisé et masqué » (variantes et produits par motif). Alerte GitHub si un problème subsiste |
| toutes les 10 min | Contrôle des commandes (toutes les commandes des 72 dernières heures pas encore étiquetées), avec la même règle que le contrôle de stock (tolérance du soir comprise) ; un article jugé non commandable est relu une seconde fois avant le verdict, et l'alerte dit ce que la page affichait (vendeur, expéditeur, toutes les dates) pour que Hoodo compare avec son compte : étiquettes amazon-ok / amazon-ko / amazon-incertain ; amazon-qte si la quantité commandée dépasse ce qu'Amazon.ae montre ou autorise ; source-2 si l'article est à acheter chez le second fournisseur |
| toutes les 10 min | fallback-sync.yml : confirme les variantes vendues via leur second fournisseur |
| en continu | heartbeat.yml, l'horloge : le planning de GitHub prend des heures de retard ou saute des passages (mesuré le 10 nov). Une petite tâche reste éveillée 3 h, lance chaque contrôle à l'heure (commandes, MedX, PadelShop, second fournisseur, audit, et le contrôle complet s'il n'est pas parti 12 min après son heure), puis passe le relais à la suivante. Elle est relancée si elle disparaît (toutes les heures, à chaque contrôle des commandes et à chaque contrôle complet). Un contrôle complet lancé moins de 2 h après un autre qui s'est bien passé est annulé (pas de doublon). Les plannings GitHub restent en seconde chance |

## 5. Garde-fous contre les mauvaises lectures
- Plus de 35 % des variantes lues passent en Épuisé d'un coup (en comptant celles déjà masquées pendant la lecture) → aucun changement de stock, et ces variantes ne sont PAS marquées « vérifiées » : la couverture les relit tout de suite + alerte.
- Couverture : tout ce que le contrôle en cours n'a pas lu est relu (2 passes). Non vérifié depuis 6 h → Épuisé ; si cela dépasse 10 % de ce qui est en vente → alerte, et seul ce qui n'est pas vérifié depuis 12 h (HARD_STALE_HOURS) est mis en Épuisé, quel que soit le nombre : un stock qu'on ne peut pas confirmer pendant une demi-journée n'est pas vendu. Cette étape tourne même si une étape précédente a échoué.
- Une variante n'est marquée « vérifiée » que si sa décision a vraiment été écrite dans Shopify.
- Prix : une hausse de plus de 150 % ou une baisse de plus de 40 % n'est pas appliquée tout de suite ; elle l'est si une lecture au moins 3 h plus tard donne le même montant. En attendant, hausse = Épuisé (coût réel inconnu), baisse = ancien prix gardé.
- Page lue avec une autre ville que Dubaï → jamais utilisée ; l'adresse est remise une fois, sinon le lecteur s'arrête.
- Beaucoup de pages « supprimées » ou « autre article » d'un coup (plus de 10 % d'un lecteur) → prises pour une mauvaise lecture, rien n'est changé.
- Fiche supprimée ou autre article : relu une seconde fois avant de compter.
- Identifiants Shopify absents dans GitHub → échec et alerte (avant : le contrôle se terminait « en vert » sans rien faire).
- Plus de 60 % du catalogue serait masqué → rien n'est masqué + alerte.
- Plus de 150 variantes sans ASIN à couper d'un coup → rien n'est changé + alerte.
- Adresse de Dubaï non prise au démarrage → 3 essais, puis le lecteur s'arrête sans rien changer (alerte).
- Adresse de Dubaï perdue pendant la lecture → le lecteur s'arrête, rien n'est changé pour le reste.
- CAPTCHA Amazon → pause d'1 à 2 min ; 5 de suite → le lecteur s'arrête (le reste est relu par la couverture).

## 6. Alertes
- Échec non résolu (contrôle, couverture, masquage, garde-fou déclenché, erreurs Shopify) → issue GitHub « alerte-inventaire » dans glow-up-lab : GitHub envoie un e-mail et une notification de l'appli GitHub au propriétaire du dépôt. Une issue par type d'alerte (une nouvelle panne n'est plus cachée par une ancienne alerte ouverte), au plus un rappel toutes les 3 h par type.
- Contrôle des commandes en échec, horloge en échec, second fournisseur en échec : même alerte. Si le commentaire sur la PR #15 échoue, l'alerte de commande part en issue.
- Contrôle du matin (03:40 environ) : lit le résultat de la nuit ; message à Hoodo si un échec persiste.

## 7. Obstacles connus et voie retenue
| Obstacle | Voie retenue | Statut |
|---|---|---|
| Contrôle anti-robot Amazon | Lecture lente, pauses, relectures ; jamais de contournement de la détection | En place |
| Le robot ne voit pas le compte connecté de Hoodo : dates différentes | Depuis le 11 nov, le robot lit la date « fastest delivery » pour tout ce qu'Amazon expédie lui-même (ce que son compte obtient) ; retenue à la main (`bloque`) pour les cas signalés. À vérifier avec Hoodo : cette date est-elle gratuite sur son compte (Prime) ou facturée quelques AED par commande ? Piste : API officielle Amazon | En place, un point à vérifier |
| Pages sans date de livraison | Relecture lente une fois, puis considérées indisponibles | En place |
| Variantes sans ASIN (36 produits le 5 nov) | Restent masquées tant qu'elles ne sont pas reliées | À relier |
| Exécutions GitHub sautées ou en retard | Horloge heartbeat.yml (voir section 4) + tâche de secours 5 fois par jour | En place |
| Débit Shopify limité | 30 tentatives avec attente | En place |

## 8. Réglages (valeurs par défaut du code ; pour en changer une : variable d'environnement dans le workflow, donc une PR)
MAX_DAYS=2 · EVENING_FROM_HOUR=19 (heure de Dubaï) · EVENING_SLACK_DAYS=1 (0 = tolérance du soir désactivée) · STOCK_GUARD=0,35 · NO_DATE_KEEPS=0 (1 = l'ancienne règle « page sans date laissée telle quelle ») · RETRY_MAX=40 · LOW_STOCK_MAX=3 (0 = règle du stock presque fini désactivée) · LOW_STOCK_BACK=5 · PRICE_DROP_MAX=0,4 · PRICE_CONFIRM_HOURS=3 · INCLUDE_DELIVERY_FEE=1 (0 = frais de livraison non comptés) · HARD_STALE_HOURS=12 (0 = limite désactivée).

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
- 7 nov : des fiches créées par API avaient le suivi du stock désactivé (Old Spice, Crest, Colgate, Gum, Oral-B, Sensodyne…) : Shopify ignore alors « Épuisé » (DENY) et la variante reste commandable. Nouvel audit complet de tous les produits toutes les 30 min qui réactive le suivi (hors cartes cadeaux) et signale le reste ; les fils d'ajout doivent créer les variantes avec inventoryItem.tracked=true.
- 9 nov : alerte #58, un lecteur sur 16 (contrôle de 13h37 Djibouti) coupé par GitHub (« The hosted runner lost communication with the server ») : panne de la machine GitHub, pas du script. Rien à corriger : la vérification de couverture masque ce qui n'est pas relu en 6 h, et le contrôle suivant (16h46) a tout relu (0 variante non vérifiée) → alerte fermée. Règle : si un seul lecteur tombe pour cette raison et que le contrôle suivant est complet, on ferme l'alerte sans changer le code.
- 10 nov : commande #1040, e.l.f. Camo Brunette lue « livrée demain » (petit stock d'un vendeur expédié par Amazon), mais ce stock est parti et l'offre est passée à un vendeur qui livre la semaine suivante (même cas que #1014). Hoodo a dû racheter ailleurs (65 AED perdus). → une variante avec 3 unités ou moins sur Amazon.ae (« Only N left in stock ») n'est plus vendable ; au contrôle des commandes, un tel article est signalé (amazon-ko) pour que Hoodo vérifie le délai sur son compte et achète vite.
- 10 nov : audit complet de la synchro (PR #67). Lecture des pages refaite sur 23 vraies pages (amazon_page.py) : le prix d'un autre produit plus bas dans la page pouvait être lu, une offre « Rush » comptait comme livraison, une précommande comme du stock, une page d'une autre ville ou d'un autre article était acceptée. Décisions refaites (plan(), testée hors ligne) : voir sections 2 et 5. Le planning GitHub n'est pas une horloge (contrôles de 10 min espacés de 15 à 75 min, contrôle complet parti avec 3 h de retard ou pas du tout) → horloge heartbeat.yml. Règle de souplesse de Hoodo (vendeur et libellés ne masquent plus) et second fournisseur (supplier.fallback). Tests : test_amazon.py, test_heartbeat.py, lancés à chaque modification.
- 10 nov (soir) : premier passage de l'audit sur main = fausse alerte « 108 variantes en vente sans ASIN » : c'étaient les variantes MedX (SKU MEDX-) et la carte cadeau. L'audit reconnaît maintenant les autres fournisseurs (suppliers.py) et ignore les cartes cadeaux ; test ajouté (test_audit_sources).
- 10 nov : le contrôle des fiches a trouvé 10 variantes dont la page Amazon.ae n'est pas l'article vendu → retenues dans seller-hold.json ; le contrôle d'identité (ASIN affiché ≠ ASIN demandé) les arrête désormais automatiquement.
- 11 nov : commande #1048 (20 h 25 Djibouti), 6 NYX vendus et expédiés par Amazon.ae jugés « trop lents » (date gratuite « première commande » : samedi 14, 3 jours) puis masqués et bloqués 24 h, alors que Hoodo voit « aujourd'hui ou demain » et que la page disait aussi « Or fastest delivery Tomorrow ». Même schéma probable pour #1039 (9 nov, 21 h). Mesure sur les 8 derniers contrôles complets et sur 58 pages relues à 21 h 50 (Dubaï) : la date gratuite d'un visiteur sans compte glisse d'un jour chaque soir vers 20-21 h à Dubaï (10 nov : 1 469 variantes à 1 jour à 19 h, aucune à 21 h 45 ; 11 nov, jour de promotions : 2 jours toute la journée, puis 3 jours le soir pour environ 1 700 variantes sur 2 000), alors que la date « fastest » reste « demain ». 130 variantes ont fait le va-et-vient en vente / Épuisé en 24 h. Le garde-fou des 35 % aurait bloqué le contrôle complet du soir (fausse alerte), mais pas le contrôle des commandes, qui marquait chaque commande du soir « amazon-ko ». → la date qui compte est celle du compte de Hoodo (« fastest » pour tout ce qu'Amazon expédie lui-même : vendu par Amazon.ae ou « Fulfilled by Amazon ») ; tolérance d'un jour le soir pour ce qui est déjà en vente ; contrôle des commandes : même règle, seconde lecture avant « amazon-ko », blocage de 24 h réservé aux raisons de stock, alerte avec les dates lues. Les pages « en stock sans date » relues (8 sur 8) sont des offres d'import Amazon US / UK : masquage justifié, rien à changer.
- 11 nov : stock presque fini. La règle du 10 nov (3 unités ou moins) sort 150 à 230 variantes selon le contrôle, et un stock qui bouge entre 3 et 4 faisait entrer et sortir la variante à chaque contrôle. → une variante sortie ne revient qu'au-dessus de 5 unités. Le seuil de 3 est gardé : c'est lui qui aurait évité #1014 et #1040. À revoir avec des chiffres : chaque rapport de contrôle garde maintenant, pour chaque variante en Épuisé, le motif, le stock lu et les dates lues (liste « out »).
- 11 nov : « pourquoi autant de produits masqués ? » demandait une enquête à la main (410 brouillons comptés par le fil du stock). → le motif est noté sur chaque variante et compté par l'audit toutes les 30 min.

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

## 11. Troisième fournisseur : PadelShop.ae (padelshop.ae, Dubaï), ajouté le 10 nov 2026
Raquettes de padel adultes et balles, en complément d'Amazon.ae (Amazon reste prioritaire ; une raquette PadelShop.ae sert à combler un niveau ou un style que la sélection Amazon.ae ne couvre pas). Une variante PadelShop.ae se reconnaît à son SKU `PSAE-<handle de la fiche padelshop.ae>`. Le code est dans `stock-sync/padelshop.py` et `padelshop_sync.py`.
- Lecture : `https://padelshop.ae/products/<handle>.js`, JSON public (pas de navigateur, pas de CAPTCHA) : prix en AED (TVA comprise, en fils) et indicateur « disponible ». Le site n'affiche AUCUN chiffre de stock : « disponible » est le seul signal.
- Vendable : page lue ET disponible ET prix > 0. Page illisible : rien ne change (puis Épuisé après PADELSHOP_STALE_HOURS=3 h sans lecture, par `coverage.py padelshop`). Fiche supprimée (404) : Épuisé.
- Délai : préparation de 1 à 2 jours ouvrés chez PadelShop.ae puis livraison à Dubaï, comptée 2 jours (PADELSHOP_DAYS=2) ; avec l'acheminement vers Djibouti, étiquette de 4 à 5 jours comme le reste de la boutique.
- Rythme : `padelshop-sync.yml` toutes les 30 minutes (à :27 et :57), puis `coverage.py padelshop` et `park_soldout.py` (même mécanisme `epuise-auto` que pour Amazon.ae et MedX : brouillon + tag tant que non lu, publié automatiquement quand une lecture réussie dit « disponible »).
- Contrôle des commandes : une ligne PadelShop.ae est vérifiée sur sa page (doit être disponible), sans navigateur ; sinon la commande passe en amazon-ko avec le motif « plus disponible chez PadelShop.ae ».
- Achat : la commande se passe à la main sur padelshop.ae, livrée à l'adresse de Dubaï (adresse hors du dépôt public), puis acheminée vers Djibouti.
- Limite connue : sans chiffre de stock, un article presque épuisé reste « disponible » jusqu'à l'épuisement réel ; le contrôle de chaque commande réduit ce risque.
- 10 nov : premier ajout, 6 raquettes (Volt 700 Power et Balance, adidas Metalbone Team Light, Siux Tsunami 5.0, Bullpadel Icon 27 et Flow 27) et 1 tube de balles Heroes.

## 12. Registre des erreurs (on ajoute, on n'efface pas)
Deux colonnes, parce que les deux coûtent : une vente à tort coûte de l'argent et la confiance d'une cliente ; un masquage à tort coûte des ventes, sans bruit. Une règle qui ferme l'une ne doit pas ouvrir l'autre : avant de durcir, on compte ce que la règle masquera ; avant d'assouplir, on rejoue les ventes à tort ci-dessous (tests hors ligne).

| Date | Cas | Sens | Cause mesurée | Règle qui en sort |
|---|---|---|---|---|
| 29 oct | SKIN1004 commandé alors qu'indisponible | Vente à tort | Synchros en échec depuis 4 jours (débit Shopify) | 30 tentatives ; alerte dès qu'un échec persiste |
| 2 nov | Majestic Pure en ligne, « 8 nov » sur le compte de Hoodo | Vente à tort | Le robot ne voit pas son compte | Retenue à la main (`bloque`, seller-hold.json) |
| 5 nov | #1019, eos commandée alors qu'épuisée | Vente à tort | Mise en ligne sans lecture ; page sans date laissée en vente | Jamais en ligne sans lecture ; page sans date = Épuisé |
| 5 nov | Produits entièrement épuisés restés visibles | Vente à tort (affichage) | Seules les variantes étaient coupées | Produit masqué quand toutes ses variantes sont en Épuisé |
| 7 nov | Crest, Colgate… commandables alors qu'en Épuisé | Vente à tort | Suivi du stock désactivé à la création | Audit toutes les 30 min, suivi réactivé |
| 8 et 10 nov | #1014, #1040 (e.l.f. Camo Brunette, 65 AED perdus) | Vente à tort | Petit stock d'un vendeur expédié par Amazon ; une fois parti, l'offre passe à un vendeur lent | 3 unités ou moins = Épuisé ; pause de 24 h après une commande non commandable pour raison de stock |
| 9 nov | Alerte #58 pour un lecteur coupé par GitHub | Fausse alerte | Panne de la machine GitHub | Alerte fermée si le contrôle suivant est complet |
| 10 nov | Alerte « 108 variantes sans ASIN » | Fausse alerte | L'audit ignorait MedX, PadelShop.ae et la carte cadeau | L'audit reconnaît les autres fournisseurs |
| 10 nov | 10 variantes dont la page Amazon.ae montrait un autre article | Vente à tort (évitée) | Fiches fusionnées ou remplacées sur Amazon.ae | Seul l'ASIN affiché décide ; autre ASIN = Épuisé |
| 9 et 11 nov | #1039 (TheraBreath), #1048 (6 NYX) jugés « trop lents » le soir | Masquage à tort + fausse alerte | Date gratuite « première commande » d'un visiteur sans compte, qui glisse d'un jour le soir ; le compte de Hoodo obtient la date « fastest » | Date « fastest » pour ce qu'Amazon expédie ; tolérance du soir ; seconde lecture et pas de pause de 24 h pour une raison de date |
| chaque soir jusqu'au 11 nov | Jusqu'à une centaine de produits masqués le soir, revenus dans la nuit ; 130 variantes en va-et-vient en 24 h | Masquage à tort | Même cause, plus un stock oscillant autour de 3 | Mêmes règles, plus le retour au-dessus de 5 unités seulement |

