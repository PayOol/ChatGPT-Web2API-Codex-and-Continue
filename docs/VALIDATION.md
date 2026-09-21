# Validation de la distribution 0.3.4

## Profil normal — 21 septembre 2026

À la demande de l’utilisateur, 0.3.4 utilise le VS Code installé normalement et ses dossiers utilisateur habituels. Les correctifs et le modèle sont appliqués dans la configuration Continue normale. Les réglages VS Code sont laissés intacts ; les données de l’ancien profil portable sont archivées.

Sur le PC utilisateur, le test exécuté dans le véritable éditeur a confirmé `profileMode: normal`, le modèle chargé et sélectionné pour chat/edit/apply, la bonne URL API et le chargement sans environnement du lanceur. La fenêtre normale « PrismCard — Visual Studio Code » a également été observée avec « ChatGPT Web2API » visible dans Continue. Le diagnostic des cinq serveurs MCP a réussi.

Les régressions couvrent les chemins autorisés du profil normal, la préservation des réglages avec commentaires, la réparation, la conservation de modèles personnels ajoutés après installation, la restauration des fichiers d’extension, l’archivage de l’ancien profil et la résolution de l’environnement par liaison explicite.

Le workflow sur Windows neuf installe ou réutilise le VS Code normal, installe Continue dans `.vscode/extensions`, puis lance le véritable éditeur sans paramètre de profil. Il exige le mode normal, l’absence de dossier portable près de l’éditeur, le modèle disponible et sa sélection dans les trois rôles. Les résultats distants et l’EXE effectivement installé sont conservés dans les artefacts du workflow.

Les sections suivantes documentent les versions antérieures. Leurs chemins portables sont remplacés par les chemins normaux en 0.3.4.

## Profil portable et modèle Continue — 21 septembre 2026

Le journal du PC utilisateur a montré qu’un retour OAuth relançait l’exécutable géré sans ses arguments de profil ni les variables du lanceur. Cette fenêtre utilisait alors le profil VS Code habituel : l’extension installée par le programme et son modèle n’y étaient pas disponibles. Le correctif utilise les répertoires portables natifs de VS Code et un résolveur de configuration lié au manifeste de l’installation.

La réparation du PC a conservé les données personnelles. Un lancement direct sans variable `CONTINUE_GLOBAL_DIR` a activé Continue dans le profil portable. L’utilisateur a confirmé dans l’interface : « Oui, le modèle apparaît ». Les cinq serveurs MCP ont de nouveau démarré et exposé leurs 67 outils. Cette vérification n’envoie aucune nouvelle requête au compte ChatGPT.

Les régressions vérifient la migration des anciens profils, l’idempotence, la préservation des profils lors de la désinstallation/réinstallation, le refus de fusionner deux profils existants, le chargement des variables et outils sans le lanceur et le refus d’appliquer le résolveur à une extension extérieure.

Le workflow d’installation lance désormais le véritable éditeur avec l’API de test des extensions VS Code, sans variables ni arguments du profil géré. Il exige l’activation de Continue, le chargement du modèle `ChatGPT Web2API` depuis son véritable gestionnaire de configuration, la bonne URL locale et le bon profil. Il ne simule pas un parcours OAuth avec un compte : il couvre son défaut déclencheur, le lancement sans environnement du raccourci. Son rapport est conservé dans `editor-runtime.json`.


## Progression de l'installateur — 21 septembre 2026

La version 0.3.2 ajoute 21 étapes numérotées, la progression des archives téléchargées, les détails d'extraction et de copie, les sorties des sous-processus et un message périodique pendant leur silence. Toutes ces lignes sont conservées dans le journal d'installation. Les fonctions réseau et processus sont exécutées réellement par Windows PowerShell 5.1 dans les tests, contre des fixtures locales.

Onze scénarios couvrent les réponses HTTP avec taille connue ou inconnue, le gzip du Marketplace, les redirections, une erreur 503 suivie d'une nouvelle tentative, les en-têtes retardés, la réutilisation du cache vérifié, le rejet d'une mauvaise empreinte, une archive qui tente de sortir de son dossier, les arguments contenant espaces/guillemets, les sorties stdout/stderr simultanées, le silence d'un processus, son code d'erreur, le lanceur batch et la syntaxe des scripts.

L'exécutable a été compilé et son extraction a été exécutée : contrôle SHA-256 et progression jusqu'à 100 %. La suite d'installation manuelle GitHub Actions utilise désormais cet EXE sur un runner Windows neuf et vérifie la présence des 21 étapes dans le journal avant d'inspecter les cinq catalogues MCP. Le journal est conservé comme artefact du workflow. Les résultats distants sont consultables dans l'onglet Actions du dépôt privé.

Le pourcentage global mesure le nombre d'étapes terminées. Les débits et estimations ne concernent que les téléchargements mesurables ; une commande externe silencieuse ne fournit pas de pourcentage interne. Les tests locaux de progression ne lancent ni VS Code ni une session ChatGPT et ne touchent pas l'installation en cours de l'utilisateur.

## Correctif des réflexions longues — 21 septembre 2026

- Régressions avec horloge simulée : réponse après huit heures, six heures avant l'apparition du marqueur, attente silencieuse avant le premier contenu et pause après un contenu partiel. Le nombre de messages DOM reste constant, comme dans une conversation virtualisée.
- Délais positifs explicites toujours respectés, avec une seule échéance pour les deux phases. Une échéance dépassée ne renvoie plus une réponse partielle comme si elle était terminée.
- Erreur de quota immédiate et erreur persistante d'observation du navigateur toujours détectées.
- Test HTTP de l'API : attente sans échéance, validation avant transmission, annulation du client, libération de l'attente et refus d'un renvoi identique incertain.
- Test Node du code réellement inséré dans le constructeur de l'adaptateur Continue : une réponse HTTP après 80 ms survit à un ancien budget SDK de 1 ms ; annulation avant les en-têtes et pendant le corps ; autres fournisseurs conservés ; aucune répétition automatique.
- Mise à jour effective de l'installation gérée 0.3.0 vers 0.3.1, avec sauvegardes, contrôle Doctor et démarrage des cinq catalogues MCP. Les bundles installés passent encore les 264 contrôles d'accès sur 86 outils et les 31 contrôles de compaction.
- Passerelle habituelle mise à jour et redémarrée hors requête active. `/health` confirme `request_timeout_seconds: 0` et la connexion au navigateur.
- Requête réelle au compte ChatGPT : réponse structurée `ATTENTE_OK`, HTTP 200, terminaison SSE reçue, aucun appel d'outil, durée 16,82 secondes. Les attentes de plusieurs heures sont validées par simulation ; cette requête réelle ne constitue pas un essai de plusieurs heures.

Les tests de fixtures historiques qui créaient le serveur sans son constructeur ont été complétés avec le compteur des requêtes actives. Deux simulations de réponse ont aussi été corrigées pour fournir un véritable signal de fin côté backend : elles reposaient auparavant sur un retour silencieux à expiration.

## Socle de validation 0.3.0

La distribution a été construite et vérifiée sous Windows x64 le 21 septembre 2026, à partir du commit amont `497527dceabfa3f95961e23c291e618c5570f1ac` et de l'environnement local amélioré. Les 32 modules Python de l'installation de référence ont été comparés : 18 identiques, 8 modifiés et 6 ajoutés, auxquels s'ajoute ici le registre d'images partagé rendu portable.

## Vérifications de l'installation

- Installation complète dans un dossier neuf avec un espace dans son nom : Python géré, deux environnements Python, Node, Git, ripgrep, éditeur VS Code, Continue 2.0.0, navigateur, cinq serveurs MCP, Codex et Hostinger.
- Ports 8081 et 9223 choisis automatiquement sur la machine de test parce que l'installation habituelle occupe déjà 8080 et 9222.
- Réparation exécutée avec le script, puis avec l'exécutable compilé. Correctifs idempotents et ports conservés.
- Vérification du manifeste, des fichiers, de la configuration, des empreintes des correctifs, des indicateurs d'accès et de compaction, de l'exclusion des mises à jour automatiques.
- Démarrage réel des cinq serveurs MCP : Local 17, Browser 25, Computer 15, Vision 1, Connected 9. Total : 67 outils MCP, complétant 19 outils natifs Continue.
- Lecture réelle de l'espace de travail ; navigation sur une page de contrôle locale ; capture de navigateur convertie en référence d'image dans le registre partagé.
- Avec le compte Codex existant : catalogue de 651 fonctions, sans requête à un modèle ni action distante.
- Avec un répertoire Codex vide : catalogue Hostinger de 401 fonctions et 39 méthodes Codex. Ce résultat vérifie l'installation et la découverte des schémas ; il ne prouve pas l'authentification ni le succès des opérations d'un fournisseur.
- Démarrage de la passerelle et de son navigateur dédié, arrêt des processus possédés, second lancement sans doublon. Le profil neuf indique correctement qu'une connexion ChatGPT est requise.
- Désinstallation sur un dossier témoin : programmes retirés, données personnelles conservées.
- Exécutable .NET compilé, empreinte de l'archive embarquée vérifiée et extraction exécutée.

## Tests logiciels

Les suites historiques et les régressions de l'intégration sont conservées. Les simulations anciennes ont été adaptées aux clics CDP, à la lecture des alertes localisées, à l'isolation des conversations et à la récupération du texte corrélé côté serveur. Les protections contre les renvois incertains restent actives.

Résultat local de la suite complète : **799 tests réussis**, 4 sous-tests réussis, 31 scénarios E2E exclus explicitement. Après la dernière correction du comptage des échecs d'envoi, les 31 tests concernés ont été rejoués avec succès.

Les tests de distribution couvrent l'application idempotente des correctifs, le refus d'une version incompatible avant toute écriture, les sauvegardes, la préservation des modèles ajoutés par l'utilisateur, les ports occupés et le refus de modifier une extension extérieure.

Les bundles Continue réellement installés passent **264 vérifications d'accès automatique portant sur 86 outils** et **31 vérifications de compaction**. Les réponses du modèle sont simulées pour ces tests de compaction ; il ne s'agit pas d'une preuve de résumé réellement produit par ChatGPT.

Ruff passe sur le code source et les tests. Gitleaks ne détecte aucun secret dans les fichiers de distribution et dans les 106 commits de l'historique amont inspecté.

## Limites de la preuve

La connexion ChatGPT du destinataire, ses connexions Codex/apps/Hostinger et les autorisations de son système ne peuvent pas être exportées depuis la machine de référence. Aucun profil, jeton ou historique personnel n'est inclus.

Les 31 scénarios E2E qui envoient de vraies requêtes à un compte ChatGPT sont exclus de la suite automatique par défaut. Les gestes Computer sont contrôlés au niveau du catalogue et des adaptateurs ; chaque interaction dans chaque application Windows n'a pas été rejouée. Aucune opération distante payante ou destructive n'a été utilisée pour valider cette distribution.

Le workflow GitHub `Windows distribution` exécute les tests, le contrôle de secrets et la compilation. Son option manuelle `install` effectue aussi l'installation complète sur un runner Windows neuf. Les résultats distants sont consultables dans l'onglet Actions du dépôt privé.

L'[exécution d'installation sur Windows neuf](https://github.com/PayOol/ChatGPT-Web2API-Continue/actions/runs/35619928199) a réussi : tous les composants ont été téléchargés et configurés, puis les cinq catalogues MCP ont été vérifiés. Le contrôle distant des secrets a également réussi.
