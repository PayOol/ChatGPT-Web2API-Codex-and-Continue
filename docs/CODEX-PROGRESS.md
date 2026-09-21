# Progression Codex et outils natifs — 0.4.4

## Corrections

La route `/codex/v1/responses` transmet des résumés d'état de la passerelle sous forme d'événements `response.reasoning_summary_text.delta`. L'ancien adaptateur Chat produisait du raisonnement brut, que Codex n'affichait pas comme un résumé de progression. Les états proviennent d'observations réelles : attente du navigateur, délai entre demandes, envoi déclenché, message reconnu, génération visible, réception et validation. Un rappel horodaté maintient la connexion toutes les 15 secondes pendant une attente silencieuse.

Ces états ne reproduisent pas les pensées internes du modèle. Les réponses et appels d'outils restent soumis à une validation complète avant transmission. Le client exécute les outils et fournit leurs résultats ; aucune action locale n'est présentée comme accomplie sans ce résultat.

La conversion préserve les outils natifs fonction/libre, leurs espaces de noms, schémas, identifiants d'appels et images. Les résultats de plusieurs blocs de texte sont conservés. Codex déclare aussi un outil de recherche Web hébergé par le fournisseur : ce service n'est pas implémenté par cette passerelle. Sa déclaration est explicitement signalée au modèle sans bloquer les outils du client. Un choix imposant cet outil hébergé ou un type inconnu est refusé avant tout envoi.

Les consignes distinguent les outils de premier niveau des méthodes de `tools` dans `exec`, et `ALL_TOOLS` de `tools.ALL_TOOLS`. Une erreur « not a function » ou une variable non initialisée ne justifie pas de conclure que Computer Use est absent. Le modèle doit consulter le catalogue et le guide du plugin effectivement installé. Cela améliore sa planification sans garantir chacune de ses décisions.

Enfin, ChatGPT peut afficher le message utilisateur avec des balises de code en ligne qui enlèvent des caractères à `textContent`. Pour une réponse terminée, la passerelle retrouve le texte source par l'identifiant exact du message dans la même conversation. La comparaison complète du message ou de son empreinte reste obligatoire avant récupération. Une seule correction du format est autorisée ; l'action originale n'est pas renvoyée.

Le contrôle réel a aussi reproduit un 422 après cette unique correction : ChatGPT avait ajouté un caractère au nonce d'une réponse finale JSON pourtant complète. Après vérification de la conversation, du message intégral, de la réponse littérale terminée et de la correction déjà tentée, la passerelle peut récupérer **uniquement le texte final sans appel d'outil**. Un choix d'outil obligatoire, tout appel d'outil, un message différent ou une génération active restent refusés. Cette récupération a été vérifiée sur la réponse réellement bloquée, sans nouvel envoi à ChatGPT ni action locale.

## Mise à jour

L'installateur migre uniquement son fournisseur ancien, inchangé et identifié par son journal, de `openai-chat` à `openai-responses`. L'opération passe par l'API de gestion OpenCodex et tolère une réponse de mise à jour perdue. Les paramètres modifiés par l'utilisateur, les changements de port et les conflits de propriété restent refusés. Le proxy existant et la configuration native de Codex ne sont pas réécrits.

## Validation

- Suite locale : 1005 tests réussis, 21 sous-tests et un test ignoré ; les vérifications ciblées complètent les derniers changements du flux.
- Tests du flux : progression reçue avant la fin de génération, identifiants et schémas d'outils préservés, images, réponse en erreur sans faux succès et annulation sans double envoi.
- Tests de récupération : source utilisateur résolue par identifiant exact, cache limité au même message, refus d'un autre message ou d'une réponse encore active.
- Tests de migration : coexistence, installation idempotente, reprise après réponse perdue, retrait sélectif et refus des modifications étrangères.
- Essai réel dans Codex avec `chatgpt-web2api/auto` : les étapes horodatées sont présentes dans les résumés natifs, et des appels `exec` et `node_repl` ont été exécutés avec des résultats réels.
- L'utilisateur a confirmé que les étapes sont visibles. Le contrôle guidé `node_repl` / `sky.list_apps()` a réellement détecté une fenêtre WhatsApp. Aucun clic, aucune saisie et aucun message n'ont été envoyés.
- Un essai initial avait encore conclu à tort à l'absence de Computer Use. Le contrôle réel a donc nécessité un guidage vers le catalogue et le guide Windows. La réussite du transport ne certifie pas une décision correcte du modèle pour toute demande.

Les installations neuves Windows Continue et Codex sont vérifiées séparément par le workflow rattaché au commit de publication. La connexion ChatGPT reste celle de l'utilisateur. Les longs délais sont testés par simulation ; ce contrôle ne revendique pas une génération réelle de plusieurs heures.
