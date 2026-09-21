# Compatibilité des outils Codex — 0.4.5

La passerelle transmet les demandes d'outils au client Codex. Codex garde leur exécution, leurs permissions, leurs connexions et leurs résultats. Cette couche de transport ne remplace pas les services externes et ne transforme pas un outil installé en outil authentifié et opérationnel.

## Défauts corrigés par cet audit

Une image `input_image` dans un résultat natif était correctement convertie en `image_url`, puis refusée par la normalisation, qui n'acceptait que les images utilisateur. Les tests précédents du convertisseur seul ne couvraient pas cette seconde étape. La version 0.4.5 couvre le parcours HTTP complet : appel, résultat comportant des pixels, pièce jointe transmise au navigateur et continuation suivante sans renvoi de l'image historique. L'image reste associée au rôle outil et à un appel antérieur, sans devenir une instruction utilisateur.

Les descriptions des espaces de noms sont conservées et les descriptions facultatives nulles sont acceptées. Les restrictions `allowed_tools` sont appliquées au catalogue du tour courant ; les résultats d'outils déjà exécutés restent dans l'historique. Un choix imposant un type ou un nom incompatible est refusé avant envoi au navigateur.

Les consignes comprennent des exemples explicites pour découvrir les outils via le global `ALL_TOOLS` et transmettre les pixels via `image(result.image_url)` ou `image(block)`. Sérialiser une URL de données dans `text(JSON.stringify(...))` ne livre pas une image au modèle. Ces exemples corrigent deux usages erronés effectivement observés, sans altérer automatiquement le code demandé par le modèle.

Le test visuel a également révélé une attente persistante après une réponse déjà terminée : la projection backend omettait le texte des messages utilisateur `multimodal_text`. Elle conserve désormais leurs parties textuelles, ce qui permet de comparer l'intégralité du message d'origine et d'engager la réparation de format. Les données d'images et les contenus non textuels de l'assistant restent exclus. Un test exécute le vrai JavaScript de projection puis la reconnaissance du message par son identifiant.

## Matrice

| Parcours | Couverture |
| --- | --- |
| Outils `function` | Schémas JSON, arguments, noms, identifiants et résultats conservés ; validation avant émission |
| Outils `custom` / `exec` | Source libre, grammaire déclarée, Unicode, guillemets, variables et retours à la ligne conservés ; validation finale par le client |
| Espaces de noms | Nom, description et type de l'outil conservés |
| Appels parallèles | Résultats rattachés à leur identifiant, y compris ordre de retour inversé ; erreurs conservées |
| Images des outils | Pixels PNG/JPEG/WEBP/GIF en URL de données, appel antérieur exigé, livraison incrémentale |
| Sélection | `auto`, `none`, `required`, outil imposé et sous-ensemble `allowed_tools` |
| MCP, plugins, Computer Use, navigateur, fichiers, terminal | Transport via les fonctions ou l'outil `exec` réellement exposés par le client ; disponibilité et exécution propres au client |
| Recherche Web hébergée par le fournisseur | Non implémentée par cette passerelle ; utiliser un outil de recherche/navigateur exposé par le client lorsque disponible |
| Autres outils hébergés, types inconnus, audio/fichiers binaires natifs | Refus explicite ; aucune revendication de compatibilité intégrale avec toutes les API OpenAI |

Les images conservent les limites du registre : quatre nouvelles images au maximum par requête, 12 Mo par image, 25 mégapixels, aucun téléchargement implicite d'URL distante. Une pièce jointe utilisateur encore présente dans le navigateur provoque une erreur explicite, sans écrasement du brouillon.

## Preuves et limites

L'audit du moteur Codex installé le 21 septembre 2026 a inventorié 674 points d'entrée imbriqués. Leur présence callable et la conservation de chacun de leurs noms dans un appel natif `exec` ont été contrôlées. Cet inventaire n'exécute aucune des 674 opérations et ne certifie ni leurs comptes externes ni les actions sensibles. Il n'est pas une liste figée embarquée dans le produit : le catalogue du client reste l'autorité.

La matrice automatique fait passer les résultats dans la véritable route HTTP de la passerelle avec un navigateur simulé. Elle complète les essais réels et ne s'y substitue pas. Les outils à effet externe ne sont pas exécutés pour les besoins de l'audit. Une autorisation, un mode particulier ou une connexion demandés par le client restent nécessaires.

Un contrôle guidé dans l'application Codex a réellement exécuté une commande PowerShell, la liste des projets de l'application, un calcul dans `node_repl` (19 × 23 = 437) et la transmission d'une image synthétique. ChatGPT a reconnu le rectangle rouge et le cercle bleu dont la description ne figurait pas dans la demande. La première transcription du code alphanumérique contenait un caractère supplémentaire : la livraison des pixels ne garantit pas l'exactitude de l'interprétation visuelle. Le catalogue propre à cette tâche contenait 672 entrées, ce qui confirme que l'inventaire dépend du contexte et des outils exposés.

La suite locale complète a réussi avec 1052 tests, 21 sous-tests et un test ignoré ; 84 tests ciblés ont ensuite couvert les exemples d'appel ajoutés. Le workflow associé au commit publié revalide la suite et les deux installations Windows depuis l'EXE.

Les contrats de sélection et de namespace sont décrits dans la [documentation officielle Function calling](https://developers.openai.com/api/docs/guides/function-calling). La passerelle n'est pas une implémentation exhaustive du service Responses hébergé.
