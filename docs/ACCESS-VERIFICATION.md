# Vérification avant réponse — 0.4.3

## Problème observé

À la question « As tu acces au MCP de l'UEFN sur mon pc ? », Continue avait répondu sans appel d'outil qu'il n'avait pas d'accès direct au PC et ne voyait pas de MCP UEFN. Le prompt réellement transmis contenait pourtant 86 fonctions, dont `connected_servers`, `connected_search_tools`, `connected_describe_tool`, `local_workspace_info` et `local_exec_command`. Les journaux indiquaient une réponse finale sans appel d'outil.

Le catalogue était donc transmis. Avec `tool_choice: auto`, le modèle avait choisi de conclure sans observation. L'absence d'un outil spécialisé dans le catalogue immédiat ne suffit pas à établir son absence de la machine.

## Changement

La consigne de planification placée après le catalogue et l'historique demande désormais un diagnostic pertinent en lecture seule avant une réponse sur l'accès ou l'état de l'environnement. Elle accepte les résultats actuels déjà disponibles et respecte une demande sans inspection. Les routes de découverte sont rappelées seulement si le client les a effectivement fournies.

Le modèle doit distinguer un programme installé, une configuration présente, une fonction exposée, une connexion authentifiée et une opération réellement réussie. Il doit indiquer le périmètre de la vérification et reconnaître les contrôles non concluants. Il ne doit pas installer un serveur ou modifier des permissions simplement pour vérifier un accès.

Le protocole, les schémas, les permissions et le choix d'outils du client restent identiques. `auto` accepte toujours une réponse finale et `none` interdit toujours les appels. Les explications générales et traductions n'exigent pas de faux appel de vérification. Aucune réponse n'est réécrite après coup et aucune nouvelle tentative sémantique n'est déclenchée automatiquement.

## Essai réel du 21 septembre 2026

Une conversation de test distincte a repris la question exacte et le catalogue de 86 fonctions observé dans Continue, avec `tool_choice: auto`. Son historique contenait une consigne minimale d'agent de programmation : il ne s'agissait pas d'une reproduction identique de tout l'historique original, devenu partiellement virtualisé dans l'interface.

Séquence observée avec le compte ChatGPT connecté :

1. ChatGPT demande `connected_servers`. Le vrai serveur MCP installé fournit son catalogue.
2. ChatGPT demande `connected_search_tools` pour rechercher UEFN/Fortnite/Unreal. Le même serveur renvoie ses résultats.
3. ChatGPT répond en indiquant ne pas avoir trouvé de MCP UEFN dans ce catalogue, et précise que cela ne prouve pas qu'UEFN soit absent du PC.

Le banc d'essai n'autorisait que les trois fonctions de découverte du connecteur. Il n'a effectué aucune écriture distante, action sur le bureau ou génération via Codex. Il n'a pas inspecté toutes les configurations MCP locales ni établi le fonctionnement d'un MCP UEFN. La passerelle de connexions n'est pas un inventaire exhaustif des logiciels ou serveurs du PC.

Cette observation prouve que la nouvelle consigne a déclenché de vrais contrôles avant la réponse sur cet essai. Elle ne garantit pas que toutes les décisions futures du modèle seront correctes. Le rapport détaillé local est `outputs/access-verification-runtime.json` ; il est conservé hors de l'archive distribuée.

## Installation et validation

Le module source et le module Python effectivement chargé par la passerelle installée ont été remplacés après sauvegarde et vérification de leur base 0.4.2. Le service a été redémarré entre deux requêtes, sans fermer l'éditeur ni le navigateur dédié. Le profil VS Code normal est conservé.

Les suites du protocole Agent, des sessions, des reprises, du transport Codex et des longues générations ont réussi : 85 tests. Les résultats complets et les installations Windows depuis l'EXE sont associés au commit de la release dans GitHub Actions. L'installation Codex automatisée conserve sa limite documentée : elle n'exerce pas le parcours Microsoft Store.
