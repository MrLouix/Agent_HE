# Plan futur

> L'agent est aujourd'hui un **outil personnel, mono-utilisateur, exécuté en local** (voir [`specification.md`](./specification.md) et [`plan.md`](./plan.md)).
> Ce document regroupe :
> - **Partie A** — les évolutions fonctionnelles envisagées pour augmenter la valeur personnelle de l'outil, au-delà de la synthèse des sites ;
> - **Partie B** — les sujets écartés tant que l'outil reste personnel (coûts, RGPD, multi-utilisateurs…).

---

# Partie A — Évolutions fonctionnelles

Toutes ces fonctions respectent les règles de la spécification : doses tracées et calculées par le code, contrôles de sécurité prioritaires, données personnelles qui ne peuvent que **restreindre**. Ordre conseillé : **A1 → A2 → A3**, puis le reste.

## A1. Inventaire personnel (« ma droguerie »)

- Flacons possédés : HE, chémotype, boutique, lot, date d'achat et d'ouverture, volume initial et restant, date limite.
- **« Que puis-je faire maintenant ? »** : recettes filtrées et classées selon l'inventaire.
- **Achats ciblés** : « avec tes 8 HE, 23 recettes réalisables ; acheter X en débloque 9 de plus ».
- Alertes : HE entamée depuis trop longtemps (oxydation, notamment agrumes et HE riches en monoterpènes, plus irritantes une fois oxydées), date limite dépassée, flacon presque vide.
- Saisie facilitée : photo d'étiquette ou de facture transcrite par le LLM (extraction), avec confirmation.
- Lien avec le journal : décompte automatique du volume consommé à chaque utilisation.

## A2. Profils du foyer

- Questionnaire de sécurité enregistré **une fois par personne** ; âge calculé depuis la date de naissance, grossesse depuis ses dates.
- Sélecteur « pour qui ? » appliquant automatiquement les règles de sécurité.
- Alertes de changement de tranche d'âge ou de fin de grossesse (« Léa a 6 ans ce mois-ci : ces recettes deviennent possibles »).
- **Contrôle croisé pour une diffusion en pièce commune** : le mélange doit être compatible avec toutes les personnes présentes (y compris un animal, qui reste alors un critère d'exclusion).
- Lien avec le journal : le champ « personne concernée » devient une référence vers un profil ; exclusions personnelles par personne.

## A3. Atelier de formulation

- Composition libre d'un mélange avec vérification en direct : plafond par HE, plafond total, drapeaux (ex. phototoxicité), compatibilité avec la ou les personnes visées, exclusions personnelles.
- **Étalonnage de ton compte-gouttes** (nombre de gouttes mesuré pour 1 ml) pour des conversions exactes.
- Étiquette de flacon imprimable : composition, date de fabrication, précautions, personnes concernées.
- Mélange enregistrable dans le carnet et utilisable dans le journal.

## A4. Raisonnement sur la chimie

- `data/composition.yaml` : molécules majoritaires par HE et chémotype (linalol, 1,8-cinéole, carvacrol…), chaque valeur avec sa référence.
- **Substitution** : « je n'ai pas de ravintsara » ⇒ HE de l'inventaire au profil chimique proche ; considérée comme une **synthèse** (avertissement IA + mêmes contrôles).
- **Pédagogie** : « pourquoi cette HE ? » — famille chimique, propriétés attribuées, niveau de preuve.
- **Harmonie olfactive** : notes de tête, de cœur et de fond, pour équilibrer efficacité et agrément (en lien avec les préférences du journal).

## A5. Niveau de preuve et consensus

- Gradation des sources : essai clinique (PubMed) > monographie officielle > usage traditionnel > affirmation commerciale.
- Par besoin : carte du consensus — quelles HE sont citées, par combien de sources indépendantes, avec quel niveau de preuve.
- Désaccords mis en évidence (« 4 sources pour, dont 1 étude clinique ; 2 déconseillent le soir »).

## A6. Contrôle qualité de tes lots

- Enregistrement des bulletins d'analyse (chromatographie) fournis par les boutiques, rattachés aux flacons de l'inventaire.
- Vérifications : chémotype conforme, taux de molécules à risque (cétones, allergènes).
- Comparatif de lots et de boutiques **sur la composition**, pas seulement sur le prix.

## A7. Veille personnalisée

- Nouvelles mises en garde ANSM, ANSES, EMA concernant les HE de l'inventaire.
- Suivi des prix de tes HE dans les boutiques ; alerte au moment opportun de rachat.
- Nouvelles recettes web pour tes besoins récurrents (déduits du journal) ⇒ file de validation.

## A8. Routines et cures

- Programmes : cure avec fenêtres de pause, diffusion saisonnière, routine du soir.
- Rappels, décompte des jours d'usage (alimenté par le journal) pour faire respecter les pauses.

## A9. Carnet de recettes

- Recettes validées annotées, notées, avec tes variantes et leur historique.
- Lien direct vers les retours du journal ; export PDF du carnet.

## Nouvelles briques de données

| Brique | Fonctions |
|---|---|
| `inventaire` (flacons, lots, dates, volumes, bulletins d'analyse) | A1, A3, A4, A6, A7 |
| `foyer` (personnes + questionnaire durable) | A2, A3 |
| `composition.yaml` + notes olfactives | A4, A6 |
| Niveau de preuve par source | A5 |
| Tâches planifiées (veille, alertes, rappels) | A1, A2, A7, A8 |

---

# Partie B — Sujets écartés pour l'usage personnel

> Ils ne deviennent pertinents que si l'usage change (ouverture à d'autres utilisateurs, hébergement, volume d'usage important).

## B1. Maîtrise des coûts

- Cache des résultats de recherche et des réponses LLM (clé = requête normalisée), avec durée de validité.
- Budget par requête : nombre maximal d'appels de recherche et de jetons LLM.
- Choix de modèles selon l'étape (modèle léger pour l'analyse et l'extraction, plus puissant pour la synthèse).
- Tableau de suivi de la consommation des API (Mistral, Tavily).
- Choix de fournisseurs selon le coût (Tavily vs Brave Search, Mistral vs autres LLM).

## B2. Données personnelles et RGPD

- Les réponses au questionnaire (grossesse, épilepsie, traitements…) sont des **données de santé** (article 9 du RGPD) dès lors qu'elles concernent d'autres personnes que l'auteur de l'outil.
- À prévoir : minimisation (ne pas stocker le questionnaire en clair), pseudonymisation du journal, durée de conservation, droit d'accès et de suppression, information des utilisateurs.
- Vérifier les conditions de traitement des données par les fournisseurs d'API (localisation, réutilisation pour l'entraînement).

## B3. Mentions légales et réglementation

- Avertissement « ne remplace pas un avis médical » formalisé (conditions d'utilisation).
- Allégations santé : encadrement réglementaire dans l'UE des allégations sur les produits ; formulations prudentes (« bien-être », « confort ») dans les fiches.
- Transparence sur tout lien commercial éventuel avec les boutiques (affiliation, partenariat).
- Statut de l'outil vis-à-vis de la réglementation des dispositifs médicaux si les fonctionnalités évoluent vers du conseil personnalisé de santé.

## B4. Multi-utilisateurs et hébergement

- Authentification et comptes ; historique et favoris par utilisateur.
- Hébergement : Streamlit Community Cloud (simple) ou conteneur Docker (maîtrise des secrets et des journaux).
- Gestion des secrets côté serveur, limitation du débit par utilisateur.
- Interface plus aboutie (Next.js) si besoin d'une application publique.

## B5. Extensions de périmètre (avec sources dédiées uniquement)

- **Animaux** : uniquement avec des sources vétérinaires et une table de sécurité propre à chaque espèce.
- **Voie orale** : uniquement si une source officielle (ANSM, EMA) l'encadre explicitement, et avec un verrou renforcé ; reste hors périmètre par défaut.
