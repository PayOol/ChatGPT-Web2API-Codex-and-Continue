# ChatGPT Web2API + Continue — installation Windows en un lancement

Distribution privée regroupant ChatGPT-Web2API, les correctifs de notre intégration Continue et les outils locaux, navigateur, Windows, vision et services connectés. Le code amont et sa licence MIT sont conservés ; le projet d'origine est [Octo-Lex/ChatGPT-Web2API](https://github.com/Octo-Lex/ChatGPT-Web2API), base `497527dceabfa3f95961e23c291e618c5570f1ac`.

## Installer

1. Depuis [la dernière version](https://github.com/PayOol/ChatGPT-Web2API-Continue/releases/latest), télécharger **Web2API-Continue-Setup-0.3.0.exe**.
2. Lancer ce fichier. Il télécharge les dépendances, installe l'éditeur et l'extension, applique tous les correctifs, écrit la configuration, crée les raccourcis et démarre l'environnement.
3. À la première ouverture, se connecter à **son propre compte ChatGPT** dans le navigateur dédié, puis ouvrir son dossier de travail dans VS Code et choisir le mode Agent de Continue.

Windows x64 et une connexion Internet sont nécessaires. L'installation se fait dans `%LOCALAPPDATA%\Programs\Web2API-Continue`, sans installation globale de Python ou Node et sans droits administrateur. Prévoir plusieurs Go libres, notamment pour les téléchargements et les sauvegardes. Ce lancement automatise la préparation technique ; les connexions personnelles, les éventuels CAPTCHA et les autorisations Windows restent interactifs. L'exécutable n'est pas signé avec un certificat commercial ; Windows peut donc afficher un avertissement de provenance.

Le dépôt et ses versions sont privés. Le propriétaire doit donner accès aux personnes autorisées, ou leur transmettre l'installateur. Une fois le fichier reçu, aucun identifiant GitHub n'est nécessaire pour installer : ses dépendances viennent de leurs sources publiques officielles.

Alternative avec le code source : extraire l'archive puis lancer `Install.cmd`. Cela exécute exactement la même procédure.

## Ce qui est installé et configuré

| Élément | Contenu |
|---|---|
| Passerelle | Tous les modules de la version locale améliorée, API compatible OpenAI, streaming, messages structurés, appels d'outils, récupération de réponses, suivi de conversation et limites de contexte |
| Continue 2.0.0 | Correctifs du moteur et de l'interface, accès automatique, compaction automatique à 75 %, conservation des 8 messages récents, protection contre les reprises périmées, titres automatiques désactivés |
| Local | 17 outils : commandes et processus suivis, fichiers et patchs, Git/worktrees, plan, notes demandées, heure et métadonnées d'image |
| Browser | 25 outils Playwright, navigateur isolé, captures transmises à la passerelle |
| Computer | 15 outils Windows-MCP : applications, arbre d'interface, captures, clics, clavier, fenêtres, presse-papiers et autres interactions |
| Vision | Lecture d'images, registre local partagé et transmission des pixels à ChatGPT |
| Connected | 9 outils de découverte, schémas, appels, patch natif, suivi PTY/événements, connexions et quotas via le vrai serveur Codex |
| Services | Codex 0.154.0 et Hostinger MCP 1.63.2 ; catalogue des applications selon les connexions du compte ; 39 méthodes Codex décrites dans le catalogue embarqué |
| Dépendances | Python 3.14.3, Node 24.14.0, Git portable, ripgrep, VS Code portable, Chromium, bibliothèques Python et npm verrouillées |
| Maintenance | Lanceur, démarrage à l'ouverture de session, diagnostic, réparation avec sauvegardes, désinstallation conservant les données personnelles |

Les 67 outils MCP directs complètent les outils natifs de Continue. Le catalogue connecté de la machine initiale comptait 651 fonctions ; ce nombre dépend des applications, comptes et droits de chaque utilisateur. Il ne constitue pas une garantie de disponibilité ni d'authentification sur un autre compte.

## Connexions et utilisation

La conversation Agent passe par le navigateur ChatGPT connecté. Les comptes, cookies, jetons, profils, historiques et fichiers de travail du propriétaire ne sont jamais inclus dans la distribution.

`Connect-Codex.cmd`, dans le dossier d'installation, ouvre la connexion du runtime Codex. Si Codex est déjà connecté sur le PC, la passerelle réutilise sa configuration et son authentification locales. Les apps doivent être connectées au compte concerné. Le serveur Hostinger fourni utilise son propre parcours OAuth lorsque nécessaire ; une configuration Hostinger existante est conservée. Les fonctions de génération explicites de Codex consomment son quota ; la recherche et l'appel direct aux outils n'invoquent pas un second modèle.

L'accès automatique des outils est activé comme dans l'environnement d'origine. `continue/full-access.local.json` permet de le désactiver (`enabled: false`). Les règles installées demandent de respecter les instructions de l'utilisateur, le dossier de travail et les autorisations des applications. Les commandes et le contrôle Windows ont les droits de l'utilisateur connecté.

Chaque installation possède ses dossiers `continue`, `vscode-data`, `extensions`, `browser-profile`, `media`, `state`, `logs` et `backups`. Le VS Code habituel et sa configuration ne sont pas modifiés. Les ports libres sont choisis automatiquement au premier passage puis conservés ; les valeurs effectives figurent dans `installation.json`. L'API écoute sur `127.0.0.1`.

## Maintenance et développement

- `Start.cmd` ouvre l'environnement ; `Stop.ps1` arrête uniquement la passerelle correspondant à ce dossier.
- `Doctor.cmd` contrôle les fichiers, correctifs, réglages et les cinq catalogues MCP. Une présence au catalogue n'est pas une preuve de réussite d'une action distante.
- `Repair.cmd` réinstalle les composants et réapplique la configuration. Fermer le VS Code de cette installation avant réparation. Les fichiers modifiés remplacés sont sauvegardés sous `backups`.
- `Uninstall.cmd` retire les composants et raccourcis, après fermeture de l'éditeur, tout en conservant les profils, historiques, configurations, médias, journaux et sauvegardes.
- Les mises à jour automatiques de cette copie de VS Code et de Continue sont désactivées : une nouvelle version de la distribution doit valider et adapter les correctifs.

Pour construire l'exécutable sous Windows : `python installer/build_release.py --output dist`. Le compilateur .NET Framework de Windows crée un lanceur avec l'archive source embarquée ; le lanceur vérifie son empreinte avant extraction. Les exécutables téléchargés sont vérifiés par SHA-256, les paquets Python par leurs verrous avec empreintes et npm par `npm ci`. Le fichier `installer/dependencies.json` décrit les versions fixées. Les sources de correctifs Continue sont dans `integration/continue`.

Options du lanceur : `--root CHEMIN`, `--cache CHEMIN`, `--no-launch`, `--no-shortcuts` ; `--extract-only CHEMIN` vérifie et extrait sans installer. Le chemin d'extraction doit être inexistant.

La validation détaillée de cette version est documentée dans [docs/VALIDATION.md](docs/VALIDATION.md). L'installation sur le PC de développement dans un dossier neuf ne remplace pas une validation sur toutes les éditions Windows et tous les comptes. La dépendance au site ChatGPT implique qu'un changement de son interface peut nécessiter un nouveau correctif.

L'outil ne reproduit pas les interfaces privées de l'application Codex : voix temps réel, certains panneaux, partage, ordonnanceur et génération privée d'images. Il regroupe les fonctionnalités de l'intégration effectivement développée.

Documentation originale : [docs/UPSTREAM-README.md](docs/UPSTREAM-README.md). Notices : [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
