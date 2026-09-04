# 🔎 Veille freelance / temps partiel — IA & Business

Agent de sourcing autonome. Il scanne plusieurs sources plusieurs fois par jour,
déduplique, filtre, score (règles + LLM), et t'envoie par email **uniquement** les
opportunités réellement pertinentes pour un profil **étudiant business avec bonne
maîtrise de l'IA appliquée** (pas ingénieur). Il apprend de tes retours.

**Coût : 0 €/mois.** Tourne sur GitHub Actions.

---

## 1. Ce qu'il fait

```
Sources ──▶ Collecte ──▶ Déduplication ──▶ Filtres déterministes ──▶ Pré-score
                                                                        │
                        Analyse LLM (Gemini) ◀── offres au-dessus du seuil
                                │
                     Score final 0-100 + priorité ──▶ SQLite (data/veille.db)
                                                          │
                       ┌──────────────────────────────────┼───────────────────┐
                   Email digest quotidien         Alerte 🔥 immédiate     Dashboard HTML
                       (priorité 1 + 2)            (priorité 1 hors digest)  (GitHub Pages)
                                                          │
                              Feedback 👍/👎 (issue GitHub) ──▶ ajustement des poids
```

- **Priorité 1 (🔥, score ≥ 85)** : alerte immédiate + digest.
- **Priorité 2 (🟢, 70-84)** : digest quotidien.
- **< 70** : conservé dans la base, jamais notifié.

## 2. Sources surveillées

| Source | Méthode de récupération | Clé | Fiabilité |
|---|---|---|---|
| **France Travail** (ex-Pôle Emploi) | API officielle « Offres d'emploi v2 » (OAuth2) | `FT_CLIENT_ID/SECRET` | élevée |
| **Adzuna** | API REST publique (agrégateur) | `ADZUNA_APP_ID/KEY` | élevée |
| **The Muse** | API publique `/api/public/jobs` | — | élevée |
| **Remotive** | API publique `/api/remote-jobs` | — | élevée |
| **Jobicy** | API publique v2 | — | moyenne |
| **Hacker News « Who is hiring? »** | API Algolia HN (thread mensuel) | — | élevée |
| **Welcome to the Jungle** | Index Algolia public | — | moyenne (peut casser sans préavis) |
| **LinkedIn** | Endpoint invité `jobs-guest` (pas d'API officielle) | — | **variable** (IP datacenter souvent limitée) |
| **Alertes email** | IMAP sur le label Gmail `Veille` | `GMAIL_USER/APP_PASSWORD` | élevée |

> **LinkedIn** : l'accès direct depuis GitHub Actions est bloqué par intermittence.
> Le filet de sécurité est l'ingestion des **alertes email LinkedIn** (voir §5). Configure-les.

Chaque source échoue de façon isolée : si une source tombe, le scan continue avec les autres.

## 3. Stratégie de recherche (funnel)

1. **Large** — pour chaque source, une requête par mot-clé de `config.yaml > search_queries`
   (3 catégories, FR + EN : *founder associate, bras droit fondateur, chief of staff intern,
   SDR, business developer, growth intern, formateur IA, consultant IA junior*…).
2. **Filtres déterministes** (`pipeline/filter_rules.py`) — gratuits, avant tout appel LLM :
   - **Exclusion dure** : titres techniques (*ML/Data/Software Engineer, MLOps, NLP…*),
     exigences rédhibitoires (*diplôme d'ingénieur, Master Data Science, 5+ ans de dev*).
   - **Détection** : catégorie A/B/C, type de contrat, remote/hybride/on-site, temps de
     travail, heures/semaine, signaux « temps plein rigide » vs « aménagement étudiant ».
3. **Analyse sémantique LLM** (`pipeline/llm_analyze.py`) — **seulement** les offres avec
   un pré-score ≥ 50 (`config.yaml > thresholds.llm.min_prescore`), **une seule fois par
   offre à vie**. Gemini 2.5 Flash, sortie JSON stricte. Fallback : score déterministe seul.
4. **Scoring** — voir §4.

## 4. Scoring (0-100, explicable)

Score = somme pondérée de 6 composantes (pondération dans `config.yaml > weights`) :

| Composante | Poids initial | Ce qu'elle mesure |
|---|---|---|
| Adéquation des missions | 25 | recouvrement avec les missions de la catégorie détectée + `profile_fit` LLM |
| Compatibilité étudiant | 25 | temps de travail, heures, contrat, pénalités « temps plein » |
| Intérêt IA / business | 20 | densité de termes IA appliquée + business |
| Accessibilité sans profil technique | 15 | absence d'exigences techniques + `technical_level_required` LLM |
| Localisation / remote | 10 | Paris/IdF, remote FR/EU, hybride |
| Potentiel CV / intérêt pro | 5 | type d'entreprise (startup, FinTech, conseil IA…) |

- L'analyse LLM ajoute un **ajustement borné à ±15**, jamais plus.
- Les **préférences explicites** (`config.yaml > hard_preferences`) s'appliquent en dernier
  et priment sur tout (plafond si temps plein, plafond si trop de cold calling, liste grise
  d'entreprises, etc.).
- Chaque composante produit une ligne d'explication visible dans le digest et le dashboard.

## 5. Installation & déploiement

### a. Créer le dépôt

```bash
# depuis ce dossier
git remote add origin https://github.com/<toi>/veille-freelance.git
git push -u origin build/veille-system      # ou merge sur main d'abord
```

Édite `config.yaml > github` : `owner`, `repo`, `owner_login` (ton pseudo GitHub).

### b. Obtenir les clés (toutes gratuites)

| Clé | Où | Temps |
|---|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | 2 min |
| `FT_CLIENT_ID` + `FT_CLIENT_SECRET` | https://francetravail.io → créer une app → API « Offres d'emploi v2 » | ~10 min |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | https://developer.adzuna.com | 3 min |
| `GMAIL_USER` | ton adresse Gmail | — |
| `GMAIL_APP_PASSWORD` | https://myaccount.google.com/apppasswords (2FA requise) | 2 min |

> **Quota Gemini — important.** Une clé AI Studio « simple » a un quota journalier
> très bas (~25-50 requêtes/jour sur `gemini-3.5-flash`). Le système le gère (disjoncteur
> → scoring déterministe), mais il n'analyse alors que ~15-20 offres/jour.
> **Pour lever la limite (gratuitement) :** dans Google AI Studio, crée la clé dans un
> **projet Google Cloud avec la facturation activée** (Console GCP → Billing → lier une
> carte). Le *free tier* Gemini reste gratuit (≈1500 req/jour sur flash-lite), aucun débit
> tant qu'on reste dans ces limites — c'est juste la condition pour débloquer le quota.
> Puis remplace le secret `GEMINI_API_KEY` par la nouvelle clé.

### c. Déclarer les secrets

Dépôt GitHub → **Settings → Secrets and variables → Actions → New repository secret**.
Ajoute les 7 clés ci-dessus. Le système fonctionne même s'il en manque (les sources
concernées se désactivent proprement).

### d. Activer GitHub Pages (dashboard)

**Settings → Pages → Source : Deploy from a branch → Branch : `main` / dossier `/docs`**.
Le dashboard sera sur `https://<toi>.github.io/veille-freelance/`.

### e. Configurer les alertes email (filet LinkedIn + Malt/WTTJ)

1. Sur LinkedIn : lance une recherche d'emploi (ex. *"founder associate" Paris*), clique
   **Créer une alerte** (fréquence quotidienne). Répète pour 4-5 recherches types
   (SDR remote, chief of staff, AI consultant…). Idem sur Malt / Welcome to the Jungle si tu veux.
2. Dans Gmail : **Paramètres → Filtres → Créer un filtre**
   - De : `jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR hello@malt.com`
   - Action : **Appliquer le libellé** → nouveau libellé `Veille` (+ « Ne jamais envoyer aux spams »).
3. C'est tout — le scan lit les non-lus du label `Veille`, en extrait les offres, les marque lus.

### f. Lancer

Les workflows tournent en cron automatiquement. Pour un test immédiat :
**Actions → scan → Run workflow**, puis **Actions → digest → Run workflow**.

## 6. Utilisation quotidienne

- **Email digest** (~08h) : tes nouvelles offres 🔥 et 🟢, avec le *pourquoi*, les points
  d'attention, et des liens de feedback.
- **Dashboard** : filtre par catégorie / score / remote / statut, recherche entreprise,
  détail du score, section stats d'apprentissage.
- **Feedback** : clique 👍 / ⭐ / 👎 / ❌ / 📨 dans l'email ou le dashboard → ça ouvre une
  issue GitHub pré-remplie, tu valides. Un workflow l'enregistre, ajuste les statuts et les
  poids, puis ferme l'issue. Ajoute une ligne `reason: too_sales` (ou `too_technical`,
  `hours`, `low_pay`, `not_enough_ai`…) dans le corps de l'issue pour préciser.

## 7. Configuration (`config.yaml`)

Tout est réglable sans toucher au code :
- `search_queries` — les mots-clés par catégorie.
- `sources.<nom>.enabled` — activer/désactiver une source.
- `weights` — la pondération du scoring.
- `thresholds` — seuils de priorité (85 / 70) et seuil de déclenchement du LLM (50).
- `exclude_title_patterns` / `exclude_description_patterns` — l'exclusion dure.
- `hard_preferences` — tes préférences explicites (prioritaires sur l'apprentissage) :
  ```yaml
  hard_preferences:
    no_cold_calling: true        # plafonne les offres à forte prospection téléphonique
    min_ai_ratio: 0.3            # part minimale de contenu IA
    cap_if_full_time: 45         # score max si temps plein sans aménagement
    exclude_companies: ["nom normalisé"]
    exclude_if: ["regex"]
  ```
- `digest.explore_ratio` — part du digest réservée à des offres exploratoires (anti-boucle).
- `cleanup.max_age_days` — archivage auto (45 j).

Après un changement : **Actions → scan → Run workflow** (ou `python main.py recompute` en local).

## 8. Commandes (exécution locale)

```bash
python -m venv .venv && .venv/Scripts/activate       # (Windows) ; source .venv/bin/activate ailleurs
pip install -r requirements.txt
cp .env.example .env        # et remplis les clés

python main.py init-db                 # crée data/veille.db
python main.py scan                    # un scan complet
python main.py scan --source themuse   # une seule source
python main.py digest                  # construit + envoie le digest
python main.py report                  # régénère docs/index.html
python main.py recompute               # re-score sans re-collecter
python main.py ingest-feedback --title "fb:<id>:up" --body "reason: not_enough_ai" --author "<toi>"
pytest -q                              # 80 tests
```

## 9. Fréquences (modifiables)

Édite le `cron:` dans `.github/workflows/*.yml` (UTC) :
- `scan.yml` : `0 5,10,16,19 * * *` → 4 scans/jour (~07h, 12h, 18h, 21h Paris).
- `digest.yml` : `0 6 * * *` → 1 digest/jour (~08h Paris).
- `feedback.yml` : à chaque ouverture d'issue `feedback`.

## 10. Coûts

| Composant | Coût | Alternative / note |
|---|---|---|
| GitHub Actions | 0 € | repo public : illimité ; privé : 2000 min/mois (on en utilise ~150) |
| GitHub Pages | 0 € | — |
| Gemini 2.5 Flash | 0 € | free tier large ; on fait 5-30 appels/jour. Fallback déterministe si quota atteint |
| France Travail / Adzuna / The Muse / Remotive / Jobicy / HN | 0 € | free tiers |
| Gmail SMTP + IMAP | 0 € | — |
| **Total** | **0 €/mois** | coût seulement en cas de dépassement des free tiers (improbable) |

## 11. Limites connues

- **LinkedIn direct** : fragile depuis GitHub Actions (échecs intermittents, markup
  susceptible de changer). Mitigation = alertes email. Non garanti à 100 %.
- **WTTJ** : dépend d'un index Algolia public non documenté — peut cesser de fonctionner
  du jour au lendemain (échec silencieux, le reste continue). La clé dans `config.yaml`
  est un **placeholder** : si WTTJ renvoie 403, récupère l'`X-Algolia-API-Key` réelle
  depuis les requêtes réseau de welcometothejungle.com et mets-la dans `config.yaml`.
- **Base SQLite dans le repo** : convient mono-utilisateur ; les commits fréquents
  gonflent l'historique git (faire un `git gc` de temps en temps).
- **Apprentissage V1** : heuristique simple (corrélation composante ↔ verdict), utile
  surtout après plusieurs dizaines de feedbacks. Pas de vrai modèle de ranking.
- **Rémunération** : souvent absente des annonces françaises.
- **Fraîcheur** : 4 scans/jour — une offre postée puis retirée entre deux scans peut être manquée.
- **Déduplication fuzzy** : seuil à 90 % de similarité de titre — risque marginal de faux
  positif/négatif sur des intitulés très proches ou très différents pour un même poste.

## 12. Roadmap (non implémenté)

- **V2** : détection automatique de tendances présentées comme suggestions à valider ;
  ajustement dynamique plus fin des poids ; exploration élargie de nouvelles catégories.
- **V3** : modèle de ranking entraîné sur l'historique de feedback (seulement si le volume
  de données le justifie).
- Autres : feedback 1-clic via Cloudflare Worker, scraping Malt/Google Jobs, notifications
  Telegram, runner LinkedIn local (IP résidentielle).

## 13. Structure du code

```
sources/       un module par source, chacun expose fetch(cfg) -> list[RawOffer]
pipeline/      dedup · filter_rules · score · llm_analyze · preferences · run (orchestrateur)
store/         db.py + schema.sql (SQLite, pas d'ORM)
notify/        email_digest · alert · mailer · formatting + templates/
report/        build_html.py + template.html (dashboard statique)
feedback/      ingest.py (issues GitHub -> base)
config.yaml    tout le comportement réglable
main.py        CLI
tests/         80 tests pytest (dont les 7 cas de validation du cahier des charges)
.github/workflows/  scan · digest · feedback
```
