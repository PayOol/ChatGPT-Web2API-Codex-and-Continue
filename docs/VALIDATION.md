# Validation de la distribution 0.3.0

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

Les tests de distribution couvrent l'application idempotente des correctifs, le refus d'une version incompatible avant toute écriture, les sauvegardes, la préservation des modèles ajoutés par l'utilisateur, les ports occupés et le refus de modifier une extension extérieure.

Les bundles Continue réellement installés passent **264 vérifications d'accès automatique portant sur 86 outils** et **31 vérifications de compaction**. Les réponses du modèle sont simulées pour ces tests de compaction ; il ne s'agit pas d'une preuve de résumé réellement produit par ChatGPT.

Ruff passe sur le code source et les tests. Gitleaks ne détecte aucun secret dans les fichiers de distribution et dans les 106 commits de l'historique amont inspecté.

## Limites de la preuve

La connexion ChatGPT du destinataire, ses connexions Codex/apps/Hostinger et les autorisations de son système ne peuvent pas être exportées depuis la machine de référence. Aucun profil, jeton ou historique personnel n'est inclus.

Les 31 scénarios E2E qui envoient de vraies requêtes à un compte ChatGPT sont exclus de la suite automatique par défaut. Les gestes Computer sont contrôlés au niveau du catalogue et des adaptateurs ; chaque interaction dans chaque application Windows n'a pas été rejouée. Aucune opération distante payante ou destructive n'a été utilisée pour valider cette distribution.

Le workflow GitHub `Windows distribution` exécute les tests, le contrôle de secrets et la compilation. Son option manuelle `install` effectue aussi l'installation complète sur un runner Windows neuf. Les résultats distants sont consultables dans l'onglet Actions du dépôt privé.
