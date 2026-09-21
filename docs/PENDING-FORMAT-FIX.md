# Reprise d'une réponse terminée sans protocole — 0.4.1

ChatGPT pouvait répondre en texte libre, sans le cadre JSON demandé par
Continue. Le détecteur attendait alors indéfiniment l'identifiant de réponse.
Après annulation, la tentative suivante affichait une erreur 422 d'envoi
incertain, même si la réponse était terminée dans le navigateur.

Le détecteur reconnaît désormais une réponse terminée sans cadre lorsque le
message utilisateur complet correspond au message envoyé, que la réponse lui
succède et que les boutons de fin appartiennent à cette réponse. L'attente
illimitée reste applicable aux véritables générations en cours.

Une seule demande de correction du format est autorisée, dans la même
conversation. Cette demande ne renvoie ni la consigne originale ni les résultats
d'outils déjà traités. La limite est enregistrée sur disque : annuler ou
redémarrer le service ne permet pas de multiplier les tentatives de correction.
Une réponse corrigée déjà présente est récupérée sans nouvel envoi.

Les cas non corrélés, les conversations différentes, les réponses encore en
cours et les résultats toujours invalides après correction restent protégés
contre une répétition automatique.

Le 21 septembre 2026, le cas utilisateur a été vérifié dans le navigateur :
message envoyé correspondant exactement à l'empreinte enregistrée, réponse
terminée de 726 caractères en texte libre et sans identifiant de protocole.
Une unique demande de correction a produit une réponse JSON littérale valide
de 227 caractères, sans appel d'outil. La passerelle a ensuite vérifié que cette
réponse pouvait être récupérée par la prochaine tentative de Continue. La
consigne originale n'a pas été renvoyée et aucun outil local n'a été exécuté.

Les tests couvrent la détection avec historique virtualisé, les réponses longues,
la correspondance exacte du message, les actions appartenant à un ancien tour,
la reprise HTTP, le redémarrage après correction interrompue et l'interdiction
d'une seconde correction. Le correctif est commun aux parcours Continue et
Codex, qui conservent leur installation et leurs outils respectifs.
