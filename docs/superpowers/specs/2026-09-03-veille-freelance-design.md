# Système autonome de veille d'offres freelance / temps partiel — Design

Date : 2026-09-03
Auteur : Harry Rouas (avec Claude)
Statut : validé pour implémentation

---

## 1. Objectif

Agent de sourcing autonome qui, sans intervention manuelle après déploiement :
collecte des offres freelance / temps partiel / ponctuelles / stages sur plusieurs
sources, déduplique, filtre par règles déterministes, score, analyse sémantiquement
via LLM les offres retenues, classe par priorité, garde un historique, notifie par
email uniquement les opportunités pertinentes, et expose un dashboard HTML.

Le système apprend progressivement des retours de l'utilisateur (V1 : simple et
interprétable).

**Priorité : pertinence > quantité, fiabilité > complexité, automatisation > manuel.**

## 2. Profil cible (paramètres de scoring)

- Étudiant M1 Master in Management (grande école de commerce), profil business/finance,
  **pas ingénieur / pas data scientist**.
- Bonne maîtrise des outils d'IA appliquée (ChatGPT, Claude, Gemini, Make, n8n, Zapier,
  Notion, Airtable).
- Expérience finance de marché (Makor).
- Disponibilité T1 : Lundi indispo (cours journée), Mardi + Vendredi indispo le matin,
  reste de la semaine très disponible.
- Localisation par ordre de préférence : Paris/IdF > Remote France > Remote Europe >
  Hybride avec présence ponctuelle Paris.

### Catégories recherchées

- **A — Bras droit fondateur / Ops / AI Ops** : founder associate, chief of staff intern,
  operations intern, AI project manager/coordinator, AI business analyst, startup
  generalist, entrepreneurial assistant. Missions : propositions commerciales, BD,
  pages web, prospection, analyse de marché, automatisation interne, workflows IA,
  cas d'usage IA, structuration projet, présentations. Profil généraliste, non technique.
- **B — SDR / Business Development / Growth** : SDR, BDR, business developer, sales/growth
  intern, outbound, sales ops, RevOps junior. Missions : cold calling, prise de RDV,
  prospection LinkedIn/email, qualification leads, CRM, séquences, automatisation
  prospection, personnalisation IA, enrichissement. Expérience commerciale non obligatoire.
- **C — Formation IA / Consulting IA junior / accompagnement client** : formateur IA,
  AI trainer, consultant IA junior, AI facilitator, AI enablement, AI adoption. Missions :
  animation formations, création supports, workshops, identification cas d'usage, cadrage
  besoins, accompagnement au changement, formation ChatGPT/Claude/Gemini/Copilot.
  Expertise technique avancée non requise. Bonus : connaissance finance/marchés.

### Entreprises à privilégier

Startups, scale-ups, PME innovantes, FinTech, cabinets de conseil, agences IA, sociétés
d'automatisation, sociétés de formation IA, B2B SaaS, IA appliquée au business. Capacité à
faire remonter de petites structures peu visibles.

### Exclusions strictes

- Intitulés techniques : ML Engineer, Data Scientist, Data Engineer, MLOps, AI Engineer,
  Software/Backend/Full Stack Engineer, Computer Vision, NLP Engineer, recherche
  fondamentale IA, développement d'algorithmes.
- Exigences : diplôme d'ingénieur, Master Data Science / ML, expérience significative en
  développement logiciel.
- Disponibilité : CDI temps plein, 35/39h obligatoires, présence quotidienne obligatoire,
  horaires incompatibles étudiant → **rejet ou forte pénalité**. Exception : mention
  explicite d'aménagement étudiant possible → conservé avec malus fort.

## 3. Décisions d'architecture

| Sujet | Choix | Raison |
|---|---|---|
| Hébergement | **GitHub Actions** (cron) | Gratuit, pas de serveur, historique versionné |
| Langage | **Python 3.11** | Écosystème sources/HTTP/parsing, simple à maintenir |
| Base de données | **SQLite** committée dans le repo (`data/veille.db`) | Zéro infra, portable, requêtable |
| Notifications | **Email via SMTP Gmail** (app password) | Déjà disponible, aucune dépendance |
| LLM | **Google Gemini 2.5 Flash** (free tier) | Gratuit au volume concerné, JSON mode, bon rapport qualité/prix |
| Dashboard | **HTML statique** généré → **GitHub Pages** | Rapide, gratuit, aucune dépendance runtime |
| Feedback (write-back) | **Issue GitHub pré-remplie** → workflow d'ingestion | Aucun backend, aucun secret exposé, 1 tap mobile |

**Coût mensuel estimé : 0 €.** Voir §12.

## 4. Sources

Chaque source = un module `sources/<nom>.py` exposant `fetch(config) -> list[RawOffer]`.
Échec d'une source = log + continue (jamais de crash global).

| Source | Méthode | Secret requis | Fiabilité | Notes |
|---|---|---|---|---|
| France Travail « Offres d'emploi v2 » | API REST OAuth2 client_credentials | `FT_CLIENT_ID`, `FT_CLIENT_SECRET` | Élevée | Cœur FR. Filtres : motsCles, commune/departement, typeContrat, dureeHebdo, etc. |
| Adzuna | API REST | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Élevée | Agrégateur, `country=fr`, salaire, `what`/`where`, `max_days_old` |
| The Muse | API REST publique | — | Élevée | `?category=...&location=...` ; startups, ops, remote |
| Remotive | API REST publique | — | Élevée | `?search=...` ; remote, catégories sales/business/marketing |
| Jobicy | API REST publique | — | Moyenne | remote ; `?count=...&geo=europe&industry=...` |
| Hacker News « Who is hiring? » | Algolia HN Search API | — | Élevée | Thread mensuel `Ask HN: Who is hiring? (mois année)` ; parse commentaires racine |
| Welcome to the Jungle | Index Algolia public | — | Moyenne (clés rotées) | Best-effort ; échec silencieux si indispo |
| **LinkedIn** | Endpoint invité `jobs-guest/jobs/api/seeMoreJobPostings/search` | — | Moyenne (IP datacenter souvent limitée) | Headers réalistes + rotation UA + backoff + retry ; pagination `start=0,25,50...` ; parse fragments HTML des cartes |
| **Ingestion email** | IMAP sur label Gmail `Veille` | `GMAIL_USER`, `GMAIL_APP_PASSWORD` | Élevée | Filet pour LinkedIn + Malt + Crème de la Crème + WTTJ : l'utilisateur crée des alertes email → filtre Gmail → label → parseur par expéditeur |

Non retenu : scraping direct Malt / Crème de la Crème / Indeed (hostile / auth) → couvert
par l'ingestion email. Google Jobs (nécessite API payante).

### Stratégie de recherche (funnel)

- **Niveau 1 — large** : pour chaque source, N requêtes à partir d'un jeu de mots-clés par
  catégorie (`config.yaml > search_queries`), en français et anglais. Ex A : "founder
  associate", "bras droit fondateur", "chief of staff intern", "operations intern", "AI
  operations", "chef de projet IA junior", "assistant business development IA". Ex B :
  "SDR", "business developer", "sales development representative", "growth intern",
  "outbound". Ex C : "formateur IA", "AI trainer", "consultant IA junior", "AI enablement".
- **Niveau 2 — filtres déterministes** : contrat, temps de travail, localisation/remote,
  séniorité, exclusions techniques, contraintes de dispo. Voir §6.
- **Niveau 3 — analyse sémantique LLM** : seulement les offres ayant passé N2 avec un
  pré-score ≥ seuil (`llm.min_prescore`, défaut 50). Voir §7.
- **Niveau 4 — scoring** : score 0-100 explicable. Voir §8.

## 5. Modèle de données (SQLite)

### `offers`
`id` (PK, hash de dédup) · `fingerprint` · `title` · `company` · `company_norm` ·
`category` (A/B/C/UNKNOWN) · `description` · `url` · `url_canonical` · `sources` (JSON
list : `[{source, url, external_id, seen_at}]`) · `location` · `remote` (remote/hybrid/
onsite/unknown) · `contract_type` · `work_time` (fulltime/parttime/freelance/internship/
unknown) · `work_time_hours` (nullable) · `salary_raw` · `salary_min` · `salary_max` ·
`skills` (JSON) · `published_at` · `discovered_at` · `last_checked_at` ·
`score` (int 0-100) · `score_breakdown` (JSON : {component: {points, max, reason}}) ·
`llm_analysis` (JSON, nullable) · `priority` (1/2/3) · `status` (new/seen/interesting/
applied/ignored/excluded) · `archived` (bool).

### `feedback`
`id` (PK) · `offer_id` (FK) · `verdict` (up/star/down/exclude/applied/obtained) ·
`reason` (enum nullable : too_sales / too_technical / too_time_consuming / not_enough_ai /
not_enough_business / low_pay / location / hours / weak_company / level_too_high /
level_too_low / other) · `note` (text nullable) · `created_at`.

### `pref_weights`
`id` (PK) · `snapshot_at` · `weights` (JSON) · `feedback_count` · `confidence` (low/med/high)
· `trigger` (auto/manual).

### `runs`
`id` · `started_at` · `finished_at` · `sources_ok` (JSON) · `sources_failed` (JSON) ·
`n_raw` · `n_new` · `n_scored` · `n_llm` · `n_priority1` · `n_priority2` · `notes`.

### `state`
clé/valeur (ex : `last_digest_at`, `hn_thread_id`).

## 6. Filtres déterministes (`pipeline/filter_rules.py`)

Ordre : normalisation → exclusion dure → détection catégorie → détection dispo/contrat →
pré-score.

- **Exclusion dure** (`status=excluded`, jamais notifié, gardé en base) :
  - titre matche `EXCLUDE_TITLE_PATTERNS` (regex : `\b(ml|machine learning|data|backend|
    fullstack|full[- ]stack|software|devops|mlops|nlp|computer vision)\s+(engineer|
    scientist)\b`, `\bai engineer\b`, `\bresearch scientist\b`, …) **et** le titre ne
    matche pas un pattern de catégorie A/B/C plus spécifique.
  - description exige `ingénieur`, `master data science`, `master machine learning`,
    `phd in`, `5+ years of software`, `strong coding` (patterns configurables).
- **Pénalités dispo** (ne rejettent pas seules, appliquées au scoring) :
  - `full[- ]time` / `temps plein` / `CDI` / `39h` / `35h` / `du lundi au vendredi` sans
    `part[- ]time` / `temps partiel` / `alternance` / `stage` / `aménagement` / `étudiant`
    / `freelance` / `mission` → forte pénalité compatibilité étudiant.
  - Mention explicite `aménagement étudiant` / `student-friendly hours` / `flexible for
    students` → pénalité réduite.
- **Détection catégorie** : dictionnaires de patterns pondérés par catégorie ; catégorie =
  argmax ; `UNKNOWN` si aucun score significatif → passe quand même au LLM si pré-score ok.
- **Détection remote / work_time / contract / hours** : regex sur titre+description
  (`télétravail`, `remote`, `hybride`, `2 jours/semaine`, `mi-temps`, `20h`, `stage`,
  `freelance`, `indépendant`, `CDD`, …). France Travail fournit `dureeTravailLibelle` et
  `typeContrat` directement.

## 7. Analyse LLM (`pipeline/llm_analyze.py`)

- **Quand** : offre a passé N2, `pre_score >= llm.min_prescore`, `llm_analysis IS NULL`.
  Jamais deux fois sur la même offre.
- **Modèle** : `gemini-2.5-flash` via `google-genai`, `response_mime_type=application/json`,
  `temperature=0.2`. Fallback : `gemini-2.5-flash-lite` puis, si échec total, score
  déterministe seul (`llm_analysis=null`, log dans `runs.notes`).
- **Prompt** (fichier `prompts/analyze_offer.md`) : contexte profil complet (§2) + texte de
  l'offre (titre, entreprise, description tronquée à ~4000 chars, localisation, contrat).
  Demande un JSON strict :
  ```json
  {
    "category": "A|B|C|none",
    "category_confidence": 0-1,
    "profile_fit": 0-100,
    "schedule_compatibility": 0-100,
    "technical_level_required": "none|light|moderate|heavy",
    "ai_business_interest": 0-100,
    "professional_interest": 0-100,
    "red_flags": ["..."],
    "student_arrangement_mentioned": true|false,
    "score_adjustment": -15..15,
    "reasoning": "2-3 phrases"
  }
  ```
- **Validation** : schéma (pydantic). JSON invalide → 1 retry → fallback.
- **Budget** : volume attendu 5-30 offres analysées/jour → très en-dessous du free tier
  Gemini (RPM/RPD). Cache : `llm_analysis` persisté, donc 1 appel par offre à vie.

## 8. Scoring (`pipeline/score.py`)

Score final = somme pondérée de 6 composantes (0-100), + ajustement LLM borné, clampé 0-100.
Poids par défaut dans `config.yaml > weights` (= cahier des charges) :

| Composante | Poids défaut | Signal déterministe | Ajustée par LLM |
|---|---|---|---|
| Adéquation des missions | 25 | recouvrement mots-clés missions catégorie détectée | `profile_fit` |
| Compatibilité étudiant | 25 | work_time, hours, contract, pénalités dispo | `schedule_compatibility` |
| Intérêt IA / business | 20 | densité termes IA appliquée + business | `ai_business_interest` |
| Accessibilité sans profil technique | 15 | absence d'exigences techniques, `technical_level_required` | oui |
| Localisation / remote | 10 | Paris/IdF, remote FR/EU, hybride | — |
| Potentiel CV / intérêt pro | 5 | type d'entreprise (startup/scale-up/FinTech/conseil IA) | `professional_interest` |

- Chaque composante retourne `{points, max, reason}` → `score_breakdown` (explicabilité §13).
- `score_adjustment` LLM ajouté après pondération, borné ±15.
- **Ajustement par préférences apprises** (§9) : les poids utilisés sont ceux de la dernière
  ligne `pref_weights`, pas forcément les défauts.
- **Préférences explicites** (`config.yaml > hard_preferences`) appliquées en dernier :
  malus/bonus fixes ou plafond de score (ex : `max_cold_calling_ratio` dépassé → score
  plafonné à 40 ; `exclude_if` liste de patterns → `status=excluded`).
- **Priorité** : `>=85` → 1 (🔥) ; `70-84` → 2 (🟢) ; `<70` → 3 (⚪, base seulement).

## 9. Apprentissage (V1)

- **Feedback explicite** : verdicts + raisons stockés (`feedback`). Verdict → effet immédiat
  sur `status` (down→ignored, exclude→excluded + ajoute la boîte à une liste grise,
  applied→applied, etc.).
- **Ajustement des poids** (`pipeline/preferences.py`, lancé en fin de `scan.yml` quand
  `feedback_count` a changé) :
  - `< 10` feedbacks → poids = défauts (`confidence=low`).
  - `10-40` → nudge : pour chaque composante, corréler sa valeur avec le verdict (up/star
    = +1, down/exclude = -1) sur les offres feedbackées ; déplacer le poids de ±2 pts max,
    renormaliser à 100 (`confidence=med`).
  - `> 40` → même logique, ±5 pts max (`confidence=high`).
  - Chaque changement → nouvelle ligne `pref_weights` (historique + réversible).
- **Raisons de rejet** → pénalités douces : ex ≥3 rejets `too_sales` → augmente le malus
  sur densité cold-calling. Table de mapping raison→signal dans `config.yaml`.
- **Préférences explicites** (`config.yaml`, édité à la main) : toujours prioritaires,
  effet immédiat, non écrasées par l'apprentissage. Ex :
  `hard_preferences: { no_cold_calling: true, min_ai_ratio: 0.3, company_size_max: 50 }`.
- **Exploration anti-boucle** : le digest réserve 10-20 % de ses places (`digest.explore_ratio`)
  à des offres `category=UNKNOWN` ou hors des préférences apprises mais score brut ≥ 60.
- **Explication** (§13, §22.5) : le digest et le dashboard affichent `score_breakdown` +
  « correspond à X offres que tu as appréciées » (match sur company_norm / catégorie /
  remote / work_time avec les offres `verdict in (up,star,applied,obtained)`).
- **V2/V3** (non construits, documentés dans README) : détection automatique de tendances
  présentées comme suggestions ; ajustement dynamique plus fin ; modèle de ranking entraîné.

## 10. Déduplication (`pipeline/dedup.py`)

1. `url_canonical` = URL sans query/fragment de tracking, host normalisé. Match exact → même offre.
2. Sinon `fingerprint = sha1(company_norm + "|" + title_norm + "|" + city_norm)` où `_norm`
   = minuscule, sans accents, sans ponctuation, sans suffixes légaux (SAS, SARL, Inc…),
   stopwords retirés. Match → même offre.
3. Sinon fuzzy : même `company_norm` **et** `rapidfuzz.token_sort_ratio(title_norm) >= 90`
   **et** villes compatibles → même offre.
4. Fusion : on garde la 1re vue comme canonique, on **append** la nouvelle source dans
   `sources[]`, on complète les champs vides (salaire, description plus longue…),
   `last_checked_at` mis à jour. `discovered_at` inchangé.
5. `id` de l'offre = `fingerprint` (stable). Une offre déjà en base n'est jamais « nouvelle ».

## 11. Notifications — Email (`notify/email_digest.py`, `notify/alert.py`)

- **Digest quotidien** (`digest.yml`, 08:00 Europe/Paris) : HTML, format §13. Sections
  🔥 PRIORITÉ 1 puis 🟢 PRIORITÉ 2, triées par score desc, + section « 🧭 Exploration »
  (§9). Inclut les offres `priority in (1,2)` `status=new` découvertes depuis
  `state.last_digest_at`. Met à jour `last_digest_at`. Rien si aucune offre (ou email
  court « RAS + lien dashboard »).
- **Alerte immédiate** (`scan.yml`, après chaque scan) : si ≥1 offre 🔥 `status=new`
  découverte dans ce run **et** hors fenêtre digest → email court « 🔥 N nouvelle(s)
  opportunité(s) prioritaire(s) » + mini-cartes + lien dashboard. Marque ces offres pour
  ne pas les re-alerter.
- Envoi : `smtplib` SSL, `GMAIL_USER` / `GMAIL_APP_PASSWORD`, `to = GMAIL_USER`.
- `<70` : jamais d'email.

## 12. Format du digest (§13 du cahier des charges)

```
🔥 TOP OPPORTUNITÉS

1. AI Operations Intern — Startup X
   Score : 94/100
   📍 Paris / Remote   🕐 Temps partiel   💰 800–1 200 €/mois   🏢 Startup IA B2B

   Pourquoi c'est intéressant
   • Forte composante IA appliquée
   • Business development + automatisation
   • Compatible avec les études (mi-temps, remote)

   Missions
   • …  • …  • …

   ⚠️ Point d'attention
   • Présence à Paris 1 jour/semaine

   👉 Voir l'offre  ·  👍 ⭐ 👎 ❌  (liens issue GitHub)
```

Généré depuis `score_breakdown` + `llm_analysis.reasoning` + `red_flags`.

## 13. Dashboard HTML (`report/build_html.py`)

- Sortie : `docs/index.html` (+ `docs/data.json`), publié via GitHub Pages (`docs/`).
- Une seule page, vanilla JS, pas de build. Charge `data.json` (toutes les offres non
  archivées + stats).
- Filtres : catégorie (A/B/C/UNKNOWN), score (slider), remote/hybride/onsite,
  Paris/IdF, statut. Recherche plein texte (entreprise/titre). Tri (score, date).
- Carte offre : tous les champs + `score_breakdown` déplié + `llm_analysis` + badges
  sources. Boutons feedback = liens
  `https://github.com/<owner>/<repo>/issues/new?labels=feedback&title=fb:<id>:<verdict>&body=<template raison>`.
- Section « 📊 Stats » (§22.9) : offres analysées, retenues, taux de feedback,
  candidatures, catégories les + / - appréciées, entreprises appréciées, raisons de rejet,
  évolution des poids (`pref_weights`).
- `status` (seen/interesting) modifiable aussi via lien issue.

## 14. Feedback write-back (`feedback/ingest.py` + `.github/workflows/feedback.yml`)

- Déclencheur : `issues: [opened]` avec label `feedback`.
- Parse `title` (`fb:<offer_id>:<verdict>`) et `body` (raison éventuelle, format `reason: xxx`).
- Insère dans `feedback`, applique l'effet immédiat sur `offers.status`, recalcule les
  poids si besoin, commente l'issue (« ✅ enregistré : <verdict> »), la ferme, commit la base.
- Sécurité : n'agit que si l'auteur de l'issue == `github.repository_owner`.

## 15. Orchestration & planification

`main.py <command>` :
- `scan` : collecte toutes sources → dedup → upsert `offers` → filtres → pré-score →
  LLM (offres éligibles) → score final → priorité → alerte 🔥 → recalcul poids →
  build dashboard → archivage (offres > `cleanup.max_age_days` défaut 45, non touchées,
  `status in (new,seen)`) → commit.
- `digest` : construit + envoie le digest quotidien → commit (`last_digest_at`).
- `ingest-feedback --issue <n>` : traite une issue.
- `ingest-email` : lit le label IMAP `Veille`, parse, injecte comme source → dedup.
  (appelé dans `scan`.)
- `init-db`, `report` (build dashboard seul), `recompute` (rescore sans re-collecte).

`.github/workflows/` :
- `scan.yml` : cron `0 5,10,16,19 * * *` UTC (≈ 07/12/18/21 Paris) + `workflow_dispatch`.
  `concurrency: veille` (pas de chevauchement). Commit `data/veille.db` + `docs/`.
- `digest.yml` : cron `0 6 * * *` UTC (08 Paris) + `workflow_dispatch`.
- `feedback.yml` : `on: issues: [opened]`.
- Toutes : Python 3.11, cache pip, secrets injectés depuis `Settings > Secrets`.
- Fréquences modifiables en éditant le `cron:` (documenté dans README).

## 16. Configuration (`config.yaml`)

Tout le comportement ajustable sans toucher au code :
`search_queries` (par catégorie, FR+EN) · `sources` (activer/désactiver, params) ·
`weights` (pondération scoring) · `thresholds` (priority1=85, priority2=70,
llm.min_prescore=50) · `exclude_title_patterns` · `exclude_description_patterns` ·
`penalty_patterns` · `hard_preferences` · `reason_signal_map` · `cleanup.max_age_days` ·
`digest.explore_ratio` · `digest.max_items` · `locations` (communes/départements IdF,
mots-clés remote).

## 17. Secrets (GitHub Actions `Settings > Secrets and variables > Actions`)

| Secret | Source | Obligatoire |
|---|---|---|
| `GEMINI_API_KEY` | aistudio.google.com/apikey | oui (sinon fallback déterministe) |
| `FT_CLIENT_ID`, `FT_CLIENT_SECRET` | francetravail.io (app « Offres d'emploi v2 ») | oui pour France Travail |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | developer.adzuna.com | oui pour Adzuna |
| `GMAIL_USER` | harryrouas@gmail.com | oui (email + IMAP) |
| `GMAIL_APP_PASSWORD` | Google Account > Sécurité > mots de passe d'application | oui |
| `GH_PAT` (optionnel) | fine-grained PAT `contents:write` `issues:write` | seulement si `GITHUB_TOKEN` par défaut insuffisant pour commit |

Aucun secret dans le code ni le repo. `.env.example` fourni pour l'exécution locale.

## 18. Tests (`tests/`, pytest) — écrits avant le code (§21)

| # | Cas | Attendu |
|---|---|---|
| 1 | Offre « Machine Learning Engineer » | `status=excluded`, jamais notifiée |
| 2 | « SDR freelance remote » | catégorie B, remote=remote, work_time=freelance, score élevé |
| 3 | « Founder Associate » startup, forte compo IA, mi-temps | catégorie A, score ≥ 80 |
| 4 | « Consultant IA junior » non technique, formation | catégorie C, `technical_level_required` bas, score correct |
| 5 | « CDI 39h/semaine du lundi au vendredi » | compatibilité étudiant ~0, priorité 3 ou excluded |
| 6 | Même offre depuis LinkedIn + Adzuna | 1 seule ligne `offers`, 2 entrées `sources[]` |
| 7 | Offre déjà en base, re-vue au scan suivant | pas « nouvelle », `n_new` ne l'inclut pas, pas re-notifiée |

+ tests unitaires : normalisation dedup, parsing de chaque source (fixtures JSON/HTML
enregistrées), validation schéma LLM (mock), calcul de score sur cas connus, ajustement
des poids (confiance), parsing titre d'issue feedback.

## 19. Structure du dépôt

```
veille/
  sources/            france_travail.py adzuna.py themuse.py remotive.py jobicy.py
                      hn_whoishiring.py wttj.py linkedin.py email_inbox.py  base.py
  pipeline/           dedup.py filter_rules.py score.py llm_analyze.py preferences.py
  store/              db.py  schema.sql
  notify/             email_digest.py alert.py  templates/
  report/             build_html.py  template.html
  feedback/           ingest.py
  prompts/            analyze_offer.md
config.yaml
main.py
requirements.txt
.env.example
data/                 veille.db  (committée)
docs/                 index.html data.json  (GitHub Pages)
tests/                fixtures/  test_*.py
.github/workflows/    scan.yml digest.yml feedback.yml
README.md             (guide utilisation + déploiement + coûts + limites)
```

Dépendances (`requirements.txt`) : `httpx`, `pyyaml`, `python-dateutil`, `rapidfuzz`,
`selectolax` (parse HTML LinkedIn), `pydantic`, `google-genai`, `jinja2`, `pytest`.
Volontairement minimal — pas de framework, pas d'ORM.

## 20. POC (après build)

Lancer `main.py scan` en réel, présenter 5-10 offres réellement disponibles très alignées
avec le profil : titre, entreprise, catégorie, localisation, format, rémunération si dispo,
score, raison du classement, URL, date. Si < 5 offres vraiment pertinentes → le dire, ne
pas remplir artificiellement.

## 21. Coûts & alternatives

| Composant | Coût | Alternative gratuite / note |
|---|---|---|
| GitHub Actions | 0 € (repo public : illimité ; privé : 2000 min/mois, largement suffisant) | — |
| GitHub Pages | 0 € | — |
| Gemini 2.5 Flash | 0 € (free tier : ~15 RPM / 1000+ RPD ; on fait 5-30 appels/j) | Fallback déterministe si quota/API KO ; OpenAI GPT-4o-mini payant en option |
| France Travail API | 0 € | — |
| Adzuna API | 0 € (free tier ~250-1000 req/j) | — |
| The Muse / Remotive / Jobicy / HN | 0 € | — |
| Gmail SMTP/IMAP | 0 € | — |
| **Total** | **0 €/mois** | Coût seulement si dépassement des free tiers (peu probable au volume perso) |

## 22. Limites connues

- **LinkedIn** : endpoint invité fragile depuis IP GitHub Actions (échecs intermittents,
  markup susceptible de changer). Mitigation : backoff/retry + ingestion des alertes email
  LinkedIn. Non garanti 100 %.
- **WTTJ** : dépend d'un index Algolia public non documenté ; peut casser sans préavis
  (échec silencieux, pas de blocage du reste).
- **SQLite dans le repo** : convient à un usage mono-utilisateur ; commits fréquents de la
  base gonflent l'historique git (mitigation : `git gc` périodique, ou historique squashé).
- **Apprentissage V1** : heuristique simple, pas de vrai modèle ; utile surtout après
  plusieurs dizaines de feedbacks.
- **Fraîcheur** : 4 scans/jour ; une offre très éphémère postée puis retirée entre 2 scans
  peut être manquée.
- **Rémunération** : souvent absente des annonces FR ; `salary_*` fréquemment nul.
- **Déduplication fuzzy** : seuil à 90 % — risque marginal de faux positif (2 postes
  distincts même intitulé/même boîte) ou faux négatif (intitulés très différents).

## 23. Hors périmètre V1 (à ajouter si le besoin se confirme)

Cloudflare Worker feedback 1-clic · scraping Malt/Indeed/Google Jobs · runner LinkedIn
local hybride · détection auto de tendances (§22.6 du CDC) · modèle de ranking entraîné
(§22 V3 du CDC) · notifications Telegram · multi-utilisateur.
