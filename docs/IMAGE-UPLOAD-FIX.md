# Correction des images successives — 21 septembre 2026

L'erreur `Image upload requires an idle composer with no existing attachments`
venait d'un contrôle du `FileList` du champ `input#upload-files`. ChatGPT peut
conserver cette sélection native après l'envoi, alors que les vignettes ont
disparu et que la zone de saisie est disponible.

La passerelle vérifie désormais les vignettes, les pièces jointes, la progression
d'un transfert et la génération en cours. Sur une zone de saisie disponible,
elle remet à zéro uniquement la sélection native avant le nouvel ajout. Cela
permet également de renvoyer le même fichier. La vérification est répétée dans
la même évaluation que la remise à zéro, puis les images doivent être chargées
et le bouton d'envoi disponible avant de soumettre le message.

Un échec de préparation des images survenu avant `click_send` est identifié
séparément : il n'empêche plus une nouvelle tentative explicite avec une fausse
alerte d'envoi incertain. Les échecs pendant ou après le clic conservent la
protection contre les doubles envois. Une limitation du compte conserve son
signal et son délai de reprise.

## Vérifications effectuées

- 32 tests ciblés réussis et 12 sous-tests : transport d'images, préparation du
  sélecteur, pièces jointes existantes, transfert en cours, changements de la
  zone de saisie, délai de chargement, reprise HTTP et prévention des doublons.
- Analyse Ruff réussie sur les modules et tests modifiés.
- Test réel dans une conversation ChatGPT isolée : trois envois du même PNG
  bleu, trois réponses `Blue`. Avant le troisième envoi : `files=1`, `images=0`,
  `generating=false`, ce qui reproduit précisément la condition de l'erreur.
  Le test complet a réussi en 96,95 secondes.
- Correctif appliqué à la copie source et au paquet Python de l'installation
  locale. Service redémarré et connexion au navigateur vérifiée. Profil VS Code
  normal conservé.
- La seule requête locale bloquée par cet incident a été libérée après
  vérification de son texte encore présent dans le brouillon, de son empreinte
  et de l'absence de son identifiant dans les messages envoyés. Aucune requête
  utilisateur n'a été renvoyée pendant cette réparation.

Le test réel `tests/test_e2e_image_upload.py` est volontairement exclu de la CI
ordinaire. Il nécessite `W2A_E2E_RUN=1` et un navigateur ChatGPT connecté ; il
crée sa propre conversation et n'utilise qu'une image synthétique de test.
