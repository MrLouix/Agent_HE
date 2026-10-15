# Corpus de recettes validées

Un fichier JSON par recette, au format `RecetteCorpus` (`src/agent_he/kb/corpus.py`) :
la recette (spécification §6), les besoins couverts et la trace de la relecture.

Une recette n'entre ici qu'après relecture humaine, soit par saisie directe, soit en
validant une candidate de la file de validation (`agent-he corpus valider <id>`).
Aucune recette n'est générée par un LLM.
