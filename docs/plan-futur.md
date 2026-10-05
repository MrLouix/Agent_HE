# Plan futur — sujets écartés pour l'usage personnel

> L'agent est aujourd'hui un **outil personnel, mono-utilisateur, exécuté en local** (voir [`specification.md`](./specification.md)).
> Les sujets ci-dessous ont été volontairement retirés de la spécification et du [`plan.md`](./plan.md).
> Ils ne deviennent pertinents que si l'usage change (ouverture à d'autres utilisateurs, hébergement, volume d'usage important).

---

## 1. Maîtrise des coûts

- Cache des résultats de recherche et des réponses LLM (clé = requête normalisée), avec durée de validité.
- Budget par requête : nombre maximal d'appels de recherche et de jetons LLM.
- Choix de modèles selon l'étape (modèle léger pour l'analyse et l'extraction, plus puissant pour la synthèse).
- Tableau de suivi de la consommation des API (Mistral, Tavily).
- Choix de fournisseurs selon le coût (Tavily vs Brave Search, Mistral vs autres LLM).

## 2. Données personnelles et RGPD

- Les réponses au questionnaire (grossesse, épilepsie, traitements…) sont des **données de santé** (article 9 du RGPD) dès lors qu'elles concernent d'autres personnes que l'auteur de l'outil.
- À prévoir : minimisation (ne pas stocker le questionnaire en clair), pseudonymisation du journal, durée de conservation, droit d'accès et de suppression, information des utilisateurs.
- Vérifier les conditions de traitement des données par les fournisseurs d'API (localisation, réutilisation pour l'entraînement).

## 3. Mentions légales et réglementation

- Avertissement « ne remplace pas un avis médical » formalisé (conditions d'utilisation).
- Allégations santé : encadrement réglementaire dans l'UE des allégations sur les produits ; formulations prudentes (« bien-être », « confort ») dans les fiches.
- Transparence sur tout lien commercial éventuel avec les boutiques (affiliation, partenariat).
- Statut de l'outil vis-à-vis de la réglementation des dispositifs médicaux si les fonctionnalités évoluent vers du conseil personnalisé de santé.

## 4. Multi-utilisateurs et hébergement

- Authentification et comptes ; historique et favoris par utilisateur.
- Hébergement : Streamlit Community Cloud (simple) ou conteneur Docker (maîtrise des secrets et des journaux).
- Gestion des secrets côté serveur, limitation du débit par utilisateur.
- Interface plus aboutie (Next.js) si besoin d'une application publique.

## 5. Extensions de périmètre (avec sources dédiées uniquement)

- **Animaux** : uniquement avec des sources vétérinaires et une table de sécurité propre à chaque espèce.
- **Voie orale** : uniquement si une source officielle (ANSM, EMA) l'encadre explicitement, et avec un verrou renforcé ; reste hors périmètre par défaut.
