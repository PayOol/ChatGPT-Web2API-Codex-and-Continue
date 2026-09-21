# ChatGPT Web2API — installation pour Codex ou Continue

Distribution privée **0.4.4** proposant deux cibles : **Codex**, avec ses outils et permissions natifs, ou **Continue dans VS Code**, avec ses correctifs et serveurs d’outils dédiés. Les deux utilisent la passerelle ChatGPT-Web2API. Le code amont et sa licence MIT sont conservés ; le projet d'origine est [Octo-Lex/ChatGPT-Web2API](https://github.com/Octo-Lex/ChatGPT-Web2API), base `497527dceabfa3f95961e23c291e618c5570f1ac`.

## Installer

1. Depuis [la version 0.4.4](https://github.com/PayOol/ChatGPT-Web2API-Continue/releases/tag/v0.4.4), télécharger **Web2API-Continue-Setup-0.4.4.exe**.
2. Lancer l’EXE et choisir **1 — Codex** ou **2 — Continue**. L’installation affiche chaque étape, les téléchargements et les journaux des sous-processus.
3. Pour **Codex**, l’installateur ajoute le modèle **ChatGPT Web2API** au catalogue. Codex garde ses outils natifs et leurs permissions. Un service OpenCodex existant est réutilisé après vérification de son identité ; si aucun état OpenCodex n’existe, une instance locale gérée est préparée dans le dossier de cette installation. Un état existant invalide ou un service arrêté ne sont pas remplacés automatiquement. L’application Codex est réutilisée ou installée par le Microsoft Store officiel.
4. Pour **Continue**, enregistrer ses fichiers et fermer VS Code avant l’installation. L’installateur réutilise le VS Code habituel (ou l’installe normalement), installe Continue et configure les outils décrits ci-dessous.
5. Se connecter à **son propre compte ChatGPT** dans le navigateur dédié. Dans Codex, rouvrir l’application si son catalogue était déjà chargé, puis sélectionner **ChatGPT Web2API** pour une nouvelle conversation. Dans Continue, choisir le modèle et le mode Agent.

**Dossiers séparés.** Le choix Codex utilise `%LOCALAPPDATA%\Programs\Web2API-Codex` ; le choix Continue utilise `%LOCALAPPDATA%\Programs\Web2API-Continue`. Une installation ne transforme pas le dossier de l’autre. Pour installer les deux cibles, lancer l’EXE une seconde fois et choisir l’autre dossier. Une entrée `chatgpt-web2api` déjà possédée par une autre installation OpenCodex provoque un conflit explicite ; elle n’est pas réaffectée automatiquement. L’ajout Codex à une passerelle Continue existante peut aussi réutiliser sa racine et son port, sans nouveau navigateur ni nouvelle connexion ChatGPT ; cette opération ne convertit pas sa cible de maintenance.

**Intégration Codex.** Aucun outil Codex, réglage de permission, fichier de l’application ou paquet global n’est remplacé. Le modèle transmet les demandes et résultats d’outils par l’adaptateur OpenCodex. Les autres fournisseurs et le modèle sélectionné restent en place. Dans le cas d’un OpenCodex géré neuf, `configure_codex.py` initialise son état sous `opencodex/`, désactive l’injection automatique et synchronise le catalogue. Il ajoute ensuite uniquement `openai_base_url` et `model_catalog_json` au TOML Codex, avec un journal de propriété ; des clés déjà présentes sont préservées et leur remplacement est refusé. La branche Codex n’installe ni les cinq serveurs MCP de Continue, ni un ensemble universel de connecteurs. Les mises à jour de Codex restent gérées par Codex ; la compatibilité protocolaire avec de futures versions doit être revalidée. [Détails et retrait de l’intégration](codex-integration.md).

Pendant une longue attente, les messages marqués **Passerelle ChatGPT Web2API** indiquent que la connexion est active. Ce sont des états de transport, pas des extraits de réflexion du modèle. La passerelle conserve l’attente illimitée et la prise en charge de l’annulation.

Windows x64 et une connexion Internet sont nécessaires. Les composants sont installés dans le dossier de la cible choisie, sans installation globale de Python ou Node. L’installation de Codex via le Store peut demander une interaction ou une autorisation Windows. Prévoir plusieurs Go libres, notamment pour les téléchargements et les sauvegardes. Ce lancement automatise la préparation technique ; les connexions personnelles, les éventuels CAPTCHA et les autorisations Windows restent interactifs. L'exécutable n'est pas signé avec un certificat commercial ; Windows peut donc afficher un avertissement de provenance.

Le dépôt et ses versions sont privés. Le propriétaire doit donner accès aux personnes autorisées, ou leur transmettre l'installateur. Une fois le fichier reçu, aucun identifiant GitHub n'est nécessaire pour installer : ses dépendances viennent de leurs sources publiques officielles.

Alternative avec le code source : extraire l'archive puis lancer `Install.cmd`. Cela exécute exactement la même procédure.

## Progression de l'installation

En version 0.4.4, l’installateur affiche des étapes numérotées et horodatées adaptées à la cible : **17 pour Codex**, **21 pour Continue**. Elles couvrent la préparation, les dépendances, le navigateur, l’intégration du client choisi, le diagnostic, les raccourcis et le lancement. Chaque étape réussie indique sa durée. Le pourcentage global compte les étapes terminées ; il ne prédit pas la durée totale.

Pour les archives téléchargées directement, l'installateur affiche la taille reçue, le débit moyen et, lorsque le serveur annonce une taille totale, le pourcentage et le temps restant estimé. Une taille inconnue est indiquée explicitement. La vérification SHA-256, l'extraction, la copie, la réutilisation du cache et les nouvelles tentatives sont visibles.

Les commandes Python, npm, Playwright et VS Code transmettent leurs sorties au fil de l'exécution. Une commande sans nouvelle sortie produit un message « EN COURS » toutes les cinq secondes ; ce message indique qu'elle est encore en attente, sans prétendre mesurer son avancement interne. Les téléchargements réalisés par ces outils conservent le détail qu'ils fournissent.

Le journal complet est écrit dans `logs/install.log` sous la racine choisie : `Web2API-Codex` ou `Web2API-Continue` par défaut. Une erreur indique l'étape concernée et le chemin du journal. Relancer l'installateur reprend en réutilisant les composants et archives déjà vérifiés.

## Ce qui est installé et configuré

| Cible | Client et outils | Configuration propre |
| --- | --- | --- |
| Codex | Application Codex, outils natifs et permissions existantes ; passerelle, runtime Codex, OpenCodex et Chromium locaux | Modèle ChatGPT Web2API ; état OpenCodex existant réutilisé ou instance gérée sous la racine Codex ; aucune configuration MCP Continue |
| Continue | VS Code habituel, Continue 2.0.0 corrigé et serveurs MCP décrits ci-dessous | Profil normal de VS Code et entrées Web2API dans la configuration Continue |

### Cible Continue uniquement : composants et outils

Les correctifs, serveurs, nombres d’outils et services du tableau suivant concernent **Continue**. Ils ne sont pas ajoutés à Codex par le choix Codex.

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
| Dépendances | Python 3.14.3, Node 24.14.0, Git portable, ripgrep, VS Code habituel, Chromium, bibliothèques Python et npm verrouillées |
| Maintenance | Lanceur, démarrage à l'ouverture de session, diagnostic, réparation avec sauvegardes, désinstallation conservant les données personnelles |

Les 67 outils MCP directs complètent les outils natifs de Continue. Le catalogue connecté de la machine initiale comptait 651 fonctions ; ce nombre dépend des applications, comptes et droits de chaque utilisateur. Il ne constitue pas une garantie de disponibilité ni d'authentification sur un autre compte.

## Connexions et utilisation de Continue

Dans les deux cibles, les demandes au modèle passent par le navigateur ChatGPT connecté. Les paragraphes suivants décrivent les outils et profils de **Continue uniquement**. Les comptes, cookies, jetons, profils, historiques et fichiers de travail du propriétaire ne sont jamais inclus dans la distribution.

`Connect-Codex.cmd`, dans le dossier d'installation, ouvre la connexion du runtime Codex. Si Codex est déjà connecté sur le PC, la passerelle réutilise sa configuration et son authentification locales. Les apps doivent être connectées au compte concerné. Le serveur Hostinger fourni utilise son propre parcours OAuth lorsque nécessaire ; une configuration Hostinger existante est conservée. Les fonctions de génération explicites de Codex consomment son quota ; la recherche et l'appel direct aux outils n'invoquent pas un second modèle.

L'accès automatique des outils est activé comme dans l'environnement d'origine. `%USERPROFILE%/.continue/full-access.local.json` permet de le désactiver (`enabled: false`). Les règles installées demandent de respecter les instructions de l'utilisateur, le dossier de travail et les autorisations des applications. Les commandes et le contrôle Windows ont les droits de l'utilisateur connecté.

La passerelle possède ses dossiers `browser-profile`, `media`, `state`, `logs` et `backups`. VS Code utilise son profil normal `%APPDATA%/Code`, ses extensions `%USERPROFILE%/.vscode/extensions` et Continue sa configuration `%USERPROFILE%/.continue/config.yaml`. Les réglages de l’éditeur, les autres extensions, les autres modèles et les serveurs d’outils non remplacés sont conservés. Les fichiers remplacés sont sauvegardés. Les ports libres sont choisis automatiquement au premier passage puis conservés ; les valeurs effectives figurent dans `installation.json`. L'API écoute sur `127.0.0.1`.

## Continue uniquement : profil normal de VS Code

La branche Continue de la version 0.4.4 conserve **le VS Code habituel et son profil normal**, comme depuis 0.3.4. Le raccourci Web2API démarre la passerelle puis ouvre cet éditeur, avec ses réglages et ses extensions. Un lancement de VS Code depuis son icône habituelle retrouve aussi le modèle : Continue charge son environnement à partir d’une liaison locale vérifiée, sans dépendre du raccourci.

Continue 2.0.0 reçoit automatiquement les correctifs, et **ChatGPT Web2API** est sélectionné pour chat, modification et application. Aucune installation manuelle de Continue ni connexion GitHub n’est nécessaire pour utiliser ce modèle local. Il faut connecter son compte ChatGPT dans le navigateur dédié.

Si VS Code est absent, l’installateur officiel pour l’utilisateur est téléchargé, vérifié par SHA-256 et exécuté automatiquement. S’il est déjà installé à son emplacement utilisateur ou système standard, il est réutilisé. Les préférences de mise à jour de VS Code ne sont pas modifiées ; l’exclusion de mise à jour automatique concerne uniquement Continue afin de préserver ses correctifs.

Lors d’une mise à jour depuis 0.3.3, l’ancien profil portable est archivé sous `backups/portable-profile-*`. Son historique reste conservé ; il n’écrase pas le profil normal ni ses conversations. La désinstallation retire les entrées Web2API non modifiées et restaure les fichiers d’extension non modifiés depuis leur installation. Les modifications personnelles ultérieures sont conservées. Le VS Code habituel n’est pas désinstallé.

## Réflexions longues de ChatGPT

La configuration de passerelle attend la réponse complète **sans limite de durée de génération par défaut**, y compris avec le modèle `auto`, avant le premier texte et pendant les pauses. Les anciens plafonds de 90 secondes, 10 minutes et 15 minutes sont supprimés dans cette configuration. Le correctif Continue désactive également le minuteur du SDK pour ce modèle local. Il conserve le signal d'annulation et désactive les répétitions automatiques du SDK pour éviter un second envoi.

Une annulation reçue du client annule l'observation et libère le verrou de la passerelle. ChatGPT peut continuer à générer dans son navigateur : une réponse déjà envoyée reste marquée comme incertaine et peut être récupérée lorsqu'elle est terminée, sans renvoi automatique. Les erreurs de connexion au navigateur, de session, de quota et de format restent des erreurs ; une durée de réflexion sans texte n'en est plus une.

Dans `config.json`, `request_timeout: 0` et les cinq paramètres `detector_*_timeout_seconds: 0` signifient « sans limite ». Une valeur positive réactive volontairement la limite correspondante en secondes. Le délai total éventuel couvre les deux phases d'attente sans repartir à zéro à l'apparition du message. Dans la configuration Continue installée, `requestOptions.timeout: 0` active l'attente sans minuteur du correctif local.

Pour mettre à jour une version précédente, lancer l’installateur **0.4.4** avec la même cible et le même dossier. Pour Continue, enregistrer ses fichiers et fermer toutes les fenêtres VS Code avant l’opération. Les configurations remplacées sont sauvegardées et le navigateur ChatGPT conserve son compte connecté.

## Maintenance et développement

Exécuter les commandes depuis **le dossier de la cible à entretenir**. `installation.json` conserve ce choix ; `Repair.cmd` ne transforme pas une cible en l’autre.

| Commande | Cible Codex | Cible Continue |
| --- | --- | --- |
| `Start.cmd` | Lance la passerelle de cette racine et ouvre Codex ; démarre l’OpenCodex géré si nécessaire | Lance la passerelle et ouvre le VS Code habituel |
| `Doctor.cmd` | Vérifie le manifeste, les fichiers et la présence de Codex Desktop ; contrôle la santé de la passerelle et l’identité OpenCodex hors mode `-Offline` | Vérifie les fichiers, correctifs, réglages et les cinq catalogues MCP |
| `Repair.cmd` | Reprend l’installation Codex dans la même racine et les entrées dont elle conserve la propriété | Réinstalle les composants et réapplique les correctifs ; fermer VS Code auparavant |
| `Uninstall.cmd` | Retire le fournisseur possédé ; en mode géré, retire les deux clés TOML inchangées puis arrête uniquement son OpenCodex vérifié | Retire les entrées et correctifs Continue inchangés ; retire aussi l’ajout Codex si un journal de propriété existe ; fermer VS Code auparavant |

`Stop.ps1` concerne la passerelle de ce dossier. La désinstallation retire les programmes et raccourcis gérés, conserve les données personnelles et sauvegardes, et laisse les applications Codex/VS Code et les services OpenCodex externes installés. Une modification utilisateur ou un retrait de catalogue encore en attente interrompt la suppression des programmes concernés.

Un diagnostic de présence, de catalogue ou de santé ne prouve pas l’exécution d’un outil ni une réponse ChatGPT. L’exclusion de mise à jour automatique concerne uniquement l’extension Continue corrigée ; les outils natifs et les mises à jour de l’application Codex ne sont pas reconfigurés.

Pour construire l'exécutable sous Windows : `python installer/build_release.py --output dist`. Le compilateur .NET Framework de Windows crée un lanceur avec l'archive source embarquée ; le lanceur vérifie son empreinte avant extraction. Les exécutables téléchargés sont vérifiés par SHA-256, les paquets Python par leurs verrous avec empreintes et npm par `npm ci`. Le fichier `installer/dependencies.json` décrit les versions fixées. Les sources de correctifs Continue sont dans `integration/continue`.

Options du lanceur : `--target codex` ou `--target continue`, `--root CHEMIN`, `--cache CHEMIN`, `--no-launch`, `--no-shortcuts` ; `--extract-only CHEMIN` vérifie et extrait sans installer. Le chemin d'extraction doit être inexistant. Une installation sans interaction exige `--target`. `--skip-desktop` est réservé au test Codex avec `--no-launch` et ne prétend pas installer l’application graphique.

Les preuves disponibles et leurs limites sont consignées séparément dans [docs/VALIDATION.md](VALIDATION.md). Chaque publication est associée à ses contrôles Windows dans GitHub Actions ; ceux-ci ne certifient pas toutes les éditions Windows ni tous les comptes. La dépendance au site ChatGPT implique qu'un changement de son interface peut nécessiter un nouveau correctif.

Le serveur Connected fourni à **Continue** ne reproduit pas les interfaces privées de l’application Codex : voix temps réel, certains panneaux, partage, ordonnanceur et génération privée d’images. Cette limite du connecteur Continue ne décrit pas les fonctions de l’application native utilisée par la cible Codex.

Documentation originale : [docs/UPSTREAM-README.md](UPSTREAM-README.md). Notices : [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
