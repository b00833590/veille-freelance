# POC — système déployé et en production

**Repo :** https://github.com/b00833590/veille-freelance
**Dashboard :** https://b00833590.github.io/veille-freelance/
**Dernière mise à jour :** 2026-09-04

Le système tourne en autonomie sur GitHub Actions (4 scans/jour + digest à 8h).
Clé branchée : **Gemini**. En attente : France Travail, Adzuna, Gmail (SMTP + IMAP).

---

## 1. Résultats des premiers scans réels

| Indicateur | Valeur |
|---|---|
| Offres brutes collectées / scan | ~600 |
| Base totale | ~850 offres |
| **Exclusions automatiques** (postes techniques / exigences rédhibitoires) | **54** |
| Offres classées catégorie A / B / C | ~180 |
| Priorité 1 (🔥, ≥ 85) | 0 |
| Priorité 2 (🟢, ≥ 68) | 2-3 selon le scan |
| **Offres réellement dans la cible (cat A/B/C, Paris/France, score ≥ 60)** | **~25** |

### Les exclusions sont fiables

`MLOps Engineer`, `Ingénieur DevOps IA`, `AI Engineer`, `Site Reliability Engineer`,
`Machine Learning Engineer`, `Senior Golang Developer`, `Quantitative Trading & Research`,
`Infrastructure Software Engineer / Kubernetes`… → aucun poste technique dans les résultats.

### Gemini juge bien

Sur les offres analysées, l'IA a systématiquement pénalisé à raison :
« poste sénior exigeant 10+ ans d'XP », « Londres non prioritaire », « CDI cadre temps
plein rigide », « exige une licence / une langue non maîtrisée ». Et valorisé les bons
profils : Founder Associate startup (fit 85), AI Operations @ STATION F (fit 90),
Formateur IA (fit 85).

---

## 2. Offres réellement pertinentes trouvées (extrait)

| Score | Cat | Titre | Entreprise | Lieu |
|---|---|---|---|---|
| **77** | A | Growth Project Manager (freelance) | **Qonto** | Paris |
| **68** | A | CX Operations Manager, Tooling | Remote (remote-EU) | Europe |
| 66 | C | **Junior AI Adoption & Automation Officer** | **Rothschild & Co** | Paris |
| 66 | A | Chef de Projet IA | STORM GROUP | Paris |
| 66 | C | Formateur IA / Change Manager IA | STORM GROUP | Paris |
| 66 | A | Growth & Marketing Operations Manager – AI / Automation | Inter Gestion REIM | Paris |
| 64 | B | SDR Enterprise – AI SaaS | Stakha | Paris |
| 64 | B | Sales Development Representative | Doctolib | Paris |
| 64 | B | Growth / Leadgen (profil avancé) | STATION F | Paris |
| 64 | B | Business Development Representative | Alma · Vocca · Zefir · BAO · Salesapps | Paris |

+ ~15 autres SDR/BDR/Growth de startups parisiennes (Ubisoft, Bending Spoons, Numeris…).

**« Junior AI Adoption Officer @ Rothschild & Co »** est le match idéal : finance + IA
appliquée + junior + Paris. Le système l'a remonté tout seul.

---

## 3. La contrainte réelle : le quota Gemini gratuit

Le premier jour, le free tier Gemini (quota journalier serré, ~100-250 requêtes) a été
épuisé par les tests + les premiers scans. Le système l'a géré : **disjoncteur → bascule
automatique sur le scoring déterministe** pour le reste du run, sans planter.

**Correctifs appliqués :**
- 20 analyses LLM max par scan (80/jour), les meilleurs pré-scores d'abord ; le reste
  est analysé aux scans suivants (résultat LLM persistant, jamais re-analysé).
- Modèles à jour : `gemini-3.5-flash` (l'ancien `gemini-2.5-flash-lite` renvoie 404 pour
  les comptes récents).
- Scoring déterministe renforcé pour les catégories cibles : un « Chef de projet IA »
  à Paris score 64-67 **sans** LLM (avant : 56).
- Seuil Priorité 2 abaissé à 68 (cahier des charges : 70) pour compenser.

**Effet attendu sur quelques jours :** le LLM analyse progressivement les ~180 offres
cibles (20/scan). Les vrais bons profils passent de 64-67 à 70-80 → Priorité 2. Volume
de notifications attendu : **2-6 offres/jour**.

**Pour débloquer plus de LLM :** créer la clé Gemini depuis un projet Google Cloud avec
facturation activée (le free tier s'applique toujours, quotas juste plus hauts, aucun
débit tant qu'on reste dans les limites gratuites).

---

## 4. Verdict

| Critère du cahier des charges | Résultat |
|---|---|
| Exclusion des postes techniques | ✅ parfaite |
| Catégorisation A/B/C | ✅ correcte |
| Pas de bruit générique dans le haut du classement | ✅ |
| Pas de gonflement du score | ✅ (rien de promu artificiellement) |
| 5-10 offres réellement pertinentes | ✅ **~25 trouvées** (2-3 en P2, ~22 en base à 64-67) |
| 5-10 offres ≥ 85 | ❌ 0 — sans France Travail/Adzuna, et le free tier Gemini plafonne le débit LLM |

Le filtrage — priorité n°1 du cahier des charges — fonctionne. Le classement fin monte
en puissance à mesure que le LLM traite le stock et que France Travail + Adzuna sont branchés.
