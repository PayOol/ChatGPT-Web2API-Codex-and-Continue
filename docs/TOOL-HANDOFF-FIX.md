# Continuité des outils après un résultat — 0.4.2

Une session Continue avait exécuté des appels Computer, puis reçu une réponse
affirmant ne pas avoir accès au runtime externe de VS Code. La réponse respectait
le format JSON attendu : le validateur de protocole ne pouvait donc pas la
distinguer d'une réponse finale légitime.

Les continuations envoyaient le catalogue des outils et uniquement les nouveaux
messages. Le rappel du contrat d'exécution se trouvait avant ces données et la
demande utilisateur restait dans l'historique du navigateur. Continue pouvait
aussi insérer un message utilisateur vide lors d'une reprise.

Le pont rappelle maintenant, après les nouveaux résultats, que les appels sont
des demandes exécutées par le client connecté et que les résultats correspondants
sont déjà présents. La dernière demande utilisateur non vide est rappelée en JSON
si elle tient dans 6 000 caractères sérialisés. Les demandes plus longues restent
dans le contexte existant ; elles ne sont ni tronquées ni renvoyées intégralement.
Une nouvelle demande utilisateur remplace le rappel précédent.

Le plafond global du prompt compte ce rappel. Les résultats anciens, les actions
terminées et le contexte complet du projet ne sont pas renvoyés. Les règles
d'autorisation, les erreurs réelles et tool_choice=none restent respectés.
Le correctif ne transforme pas une réponse finale en action et ne lance pas de
réessai automatique sur la base de mots détectés dans une réponse.

Les tests couvrent les messages vides, la nouvelle demande qui remplace l'ancienne,
les grandes sorties, trois résultats successifs et la reprise de la bonne tâche
après une opération indépendante. Les tests de transport Codex et de coexistence
OpenCodex ont aussi été exécutés.

Un essai réel sur la passerelle installée a utilisé tool_choice=auto et le
convertisseur SSE extrait de l'extension Continue 2.0.0 installée. ChatGPT a demandé
trois lectures successives. Le programme de diagnostic a lu les fichiers réels
dans son seul dossier de test, puis retourné chaque résultat avec l'identifiant
de l'appel. Chaque fichier révélait seulement le nom du suivant ; le dernier
contenait une valeur aléatoire absente de la consigne. La réponse finale était
exacte. Cet essai valide le modèle, le pont et la conversion Continue ; il ne
constitue pas un essai d'envoi WhatsApp ni une certification de tous les outils.

Le correctif local a été sauvegardé puis déployé dans les sources de l'installation
et dans le paquet Python effectivement importé par son environnement. Les
empreintes et la signature de la fonction chargée ont été vérifiées après le
redémarrage du seul service Web2API. OpenCodex et les outils des clients n'ont pas
été modifiés.
