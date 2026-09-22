# Validation de la distribution 0.4.9

## Persistance Codex et découverte des outils — 22 septembre 2026

La panne reproduite après redémarrage de Codex avait une cause distincte d’OpenCodex : le proxy restait en écoute sur `127.0.0.1:10100`, mais la passerelle Web2API sur `127.0.0.1:8081` s’était arrêtée. OpenCodex renvoyait donc `502 Provider unreachable`. La cible Codex installe maintenant une tâche Windows par utilisateur, liée par manifeste et journal de propriété à une seule racine. Son superviseur reste indépendant de l’application Codex et relance la passerelle après la disparition de son processus.

Preuves obtenues sur l’installation réelle :

- La tâche possédée est restée `Running` pendant l’arrêt forcé contrôlé de la passerelle, effectué avec zéro requête active.
- Le port 8081 est passé du PID 55588 au PID 59504 en **7,96 secondes**. Le nouveau processus appartenait à la même racine ; CDP et le pilote étaient reconnectés, sans erreur.
- Après cette relance, un POST sans outil à l’URL exacte utilisée par Codex, `http://127.0.0.1:10100/v1/responses`, a terminé avec le texte exact `OK` en **14,86 secondes**. `/health` indiquait ensuite `healthy`, une requête servie, zéro requête active et aucune dernière erreur.
- Un contrôle natif Codex en lecture seule a découvert le chemin différé `exec` → `mcp__node_repl__js` dans `ALL_TOOLS`, initialisé Computer Use selon son guide et listé la fenêtre WhatsApp active. Aucun clic, texte, message ni autre interaction d’interface n’a été effectué.
- La suite locale hors E2E a réussi : **1 126 tests**, **21 sous-tests**, un test ignoré et 32 scénarios E2E explicitement exclus. Ruff passe sur `src` et `tests`.

La preuve de relance couvre une terminaison réelle du processus et le trajet réseau complet jusqu’à ChatGPT Web. Elle ne garantit pas qu’aucune future mise à jour de Windows, Codex, OpenCodex ou du site ChatGPT ne modifiera leurs contrats. La tâche refuse d’adopter ou de supprimer une entrée dont le nom, l’action, le dossier ou le journal de propriété ne correspondent plus.

# Validation de la distribution 0.4.4

## Progression et outils Codex — 21 septembre 2026

Le transport Responses émet les résumés d'état pendant l'attente et conserve la validation des appels avant exécution. Le parcours réel Codex a reçu ces résumés et exécuté des appels natifs. La récupération d'une réponse terminée a également révélé et corrigé une différence entre le texte utilisateur rendu et sa source. Les contrôles, la migration du fournisseur et les limites de la planification du modèle sont détaillés dans [CODEX-PROGRESS.md](CODEX-PROGRESS.md). Les installations Windows complètes sont rattachées au commit de publication dans GitHub Actions.

# Validation de la distribution 0.4.3

## Vérification de l'environnement avant réponse — 21 septembre 2026

La consigne de planification demande une observation pertinente avant de répondre sur un accès ou un état local. Un essai réel, avec la question UEFN de l'utilisateur et les 86 fonctions observées dans Continue, a effectué `connected_servers`, puis `connected_search_tools`, puis produit une conclusion limitée au catalogue consulté. Le changement, les conditions exactes de cet essai et ses limites sont détaillés dans [ACCESS-VERIFICATION.md](ACCESS-VERIFICATION.md). Les contrôles Windows complets et les deux parcours d'installation sont rattachés au commit de la release dans GitHub Actions.

# Validation de la distribution 0.4.1

## Réponses terminées hors protocole — 21 septembre 2026

Le correctif reconnaît une réponse terminée dont le format attendu manque et permet une seule correction du format, y compris après une annulation. La preuve sur la conversation bloquée et les cas couverts figurent dans [PENDING-FORMAT-FIX.md](PENDING-FORMAT-FIX.md). Les résultats des suites et des installations Windows sont fournis par le workflow associé au commit de cette version.

# Validation de la distribution 0.4.0

## Codex et choix de l'installation — 21 septembre 2026

Le lanceur propose Codex ou Continue. Le parcours Continue garde le profil VS Code normal. Le parcours Codex utilise un dossier distinct, un navigateur propre et le catalogue OpenCodex ; il ne remplace aucun outil, exécutable, plugin ou réglage d'autorisation de Codex. Un proxy OpenCodex déjà configuré est réutilisé sans redémarrage ; à défaut, la distribution gère sa propre instance et ajoute seulement les deux clés de routage nécessaires, avec un journal pour leur retrait sélectif.

Preuves obtenues sur le poste de développement :

- Le véritable serveur natif Codex `0.155.0-alpha.9.2` a retourné `chatgpt-web2api/auto`, affiché `ChatGPT Web2API`, dans `model/list` : 106 modèles au total, et les 105 entrées initiales conservées lors de l'inscription. Le modèle par défaut reste inchangé.
- Le contrôle de l'inscription a vérifié les octets du TOML avant/après, les fournisseurs existants, leurs combinaisons et alias. La création passe par les routes de gestion de fournisseur et de modèle, sans l'injecteur de configuration complète d'OpenCodex.
- Un véritable tour Codex, utilisant le compte ChatGPT connecté, a demandé la lecture d'un fichier de test dont le contenu aléatoire n'était pas dans la demande. Codex a exécuté `Get-Content -Raw preuve.txt` avec son outil natif, puis ChatGPT a renvoyé exactement la valeur obtenue. Cette preuve inclut la demande d'outil, son exécution avec code zéro et le retour de résultat au modèle.
- Le premier essai avait répondu sans outil. La correction porte sur l'explication du format de transport : les outils natifs libres reçoivent leur code dans `arguments.input`. Leur catalogue et leurs implémentations ne sont pas modifiés.
- Une convergence OpenCodex marquée dégradée par d'autres fournisseurs est acceptée seulement après vérification effective de notre entrée. Les codes d'avertissement restent visibles ; ils ne sont pas une certification des autres fournisseurs.

Le transport conserve les schémas, appels et résultats d'outils. Les tests couvrent leur validation avant émission, les erreurs tardives et l'annulation sans renvoi. Des messages de maintien de connexion, explicitement identifiés comme provenant de la passerelle, traversent l'adaptateur OpenCodex pendant les attentes silencieuses. Les attentes de plusieurs heures restent validées par simulation, pas par une session réelle de plusieurs heures.

Le workflow Windows comporte deux installations distinctes exécutées depuis l'EXE : Continue avec chargement dans le vrai éditeur et Codex avec un profil isolé, lecture du catalogue par le vrai serveur natif et désinscription sélective. La branche Codex du workflow utilise explicitement `--skip-desktop --no-launch` : elle ne certifie donc pas l'installation Microsoft Store ni un parcours visuel du sélecteur de modèles. L'authentification ChatGPT nécessite le compte de l'utilisateur et n'est pas embarquée.

La suite locale complète a réussi : **935 tests**, **16 sous-tests**, un test ignoré faute de permission Windows de création de liens symboliques. Les contrôles ciblés complètent les corrections de première installation effectuées ensuite. Une installation neuve isolée a terminé ses 17 étapes, puis le serveur Codex fourni a chargé le modèle parmi ses six entrées. Les preuves distantes définitives sont les artefacts du workflow associés à la version publiée.

Les sections suivantes conservent les preuves des versions précédentes.

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
