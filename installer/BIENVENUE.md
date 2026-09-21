# ChatGPT Web2API + Continue

L'environnement est installé. Le navigateur ChatGPT et cet éditeur utilisent les dossiers de cette installation.

1. Connectez votre compte ChatGPT dans le navigateur qui vient de s'ouvrir. Cette connexion personnelle ne peut pas être distribuée dans un installateur.
2. Ouvrez votre dossier de travail avec **Fichier > Ouvrir un dossier**, puis l'icône Continue dans la barre latérale.
3. Choisissez **ChatGPT Web2API** et le mode **Agent**. Les cinq serveurs d'outils se connectent automatiquement.

La configuration inclut les correctifs de streaming, les appels d'outils, les images, le suivi de conversation, la récupération après erreur, la compaction automatique et l'exécution automatique des outils autorisés. Les outils peuvent écrire des fichiers et piloter votre ordinateur : vos demandes définissent le travail à réaliser.

**Comptes connectés.** Les outils Local, Browser, Computer et Vision sont installés. Pour les apps connectées, ouvrez `Connect-Codex.cmd` dans le dossier d'installation et connectez votre compte Codex si nécessaire. Les connexions existantes de votre compte restent gérées par Codex. Une application ou un fournisseur peut demander sa propre connexion ; le nombre de services disponibles dépend de votre compte. L'accès aux méthodes de génération Codex utilise votre quota Codex.

**Diagnostic.** `Doctor.cmd` vérifie les composants et les catalogues d'outils. Il distingue la présence des outils des connexions personnelles. `Repair.cmd` reconstruit la configuration et les correctifs après fermeture de cet éditeur. Les modifications des fichiers de configuration remplacés sont sauvegardées sous `backups`.

**Lancement.** Le raccourci Bureau ouvre cet environnement. La passerelle démarre aussi à l'ouverture de session Windows. Le port API, choisi automatiquement, figure dans `installation.json` et `continue/config.yaml`.

**Désinstallation.** `Uninstall.cmd` retire les programmes et raccourcis. Il conserve les configurations, sessions et profils personnels dans le dossier d'installation.

Les mises à jour automatiques de cette copie de VS Code et de Continue sont désactivées pour conserver les correctifs compatibles. Utilisez une nouvelle version de cet installateur pour une mise à jour contrôlée.
