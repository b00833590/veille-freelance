# Veille Freelance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Système autonome qui collecte des offres freelance/temps partiel/stage sur 8 sources, déduplique, filtre, score (règles + Gemini), notifie par email et expose un dashboard HTML, le tout sur GitHub Actions à coût nul.

**Architecture:** Pipeline Python linéaire (`main.py scan|digest|ingest-feedback`). Sources → dedup → filtres déterministes → pré-score → LLM sur offres éligibles → score final → SQLite (`data/veille.db`, committée). Email via SMTP Gmail. Dashboard HTML statique dans `docs/` (GitHub Pages). Feedback via issues GitHub pré-remplies.

**Tech Stack:** Python 3.11, httpx, pyyaml, python-dateutil, rapidfuzz, selectolax, pydantic, google-genai, jinja2, pytest. Pas de framework, pas d'ORM.

## Global Constraints

- Python 3.11. `requirements.txt` limité aux libs listées ci-dessus, pas d'ajout sans raison.
- Aucun secret dans le code ou le repo. Config lue depuis env vars ; `.env.example` documente les clés.
- Toute source qui échoue = log + continue. Jamais de crash global du `scan`.
- Un appel LLM par offre maximum, à vie (`llm_analysis` persisté).
- `id` d'une offre = `fingerprint` stable. Une offre déjà en base n'est jamais "nouvelle".
- Pondérations, seuils, mots-clés, patterns : tous dans `config.yaml`, jamais en dur.
- Priorités : score ≥ 85 → 1 ; 70–84 → 2 ; < 70 → 3 (pas de notif).
- TDD : test d'abord, commit fréquent après chaque tâche verte.
- Tous les commits terminent par les lignes Co-Authored-By / Claude-Session fournies.

---

### Task 1: Squelette projet + config + schéma DB

**Files:**
- Create: `requirements.txt`, `config.yaml`, `.env.example`, `main.py` (stub argparse)
- Create: `store/schema.sql`, `store/db.py`
- Create: `store/__init__.py`, `sources/__init__.py`, `pipeline/__init__.py`, `notify/__init__.py`, `report/__init__.py`, `feedback/__init__.py`
- Test: `tests/test_db.py`, `tests/conftest.py`

**Interfaces produced:**
- `store.db.connect(path: str) -> sqlite3.Connection` (row_factory = Row, foreign_keys ON)
- `store.db.init_db(conn)` — exécute `schema.sql` (idempotent, `CREATE TABLE IF NOT EXISTS`)
- `store.db.upsert_offer(conn, offer: dict) -> tuple[str, bool]` — retourne `(offer_id, is_new)`
- `store.db.get_offer(conn, offer_id) -> dict | None`
- `store.db.record_run(conn, stats: dict) -> int`
- `store.db.get_state(conn, key, default=None) -> str | None` / `set_state(conn, key, value)`
- Tables : `offers`, `feedback`, `pref_weights`, `runs`, `state` (colonnes = §5 du design)

**Steps:**
- [ ] Écrire `tests/test_db.py` : `test_init_db_creates_tables`, `test_upsert_offer_new_then_existing` (2e upsert même fingerprint → `is_new=False`, pas de doublon), `test_state_roundtrip`.
- [ ] Lancer pytest → FAIL (modules absents).
- [ ] Écrire `store/schema.sql` (5 tables, design §5), `store/db.py`, `config.yaml` (toutes clés §16 avec valeurs par défaut du CDC), `requirements.txt`, `.env.example`, `main.py` stub, tous les `__init__.py`, `tests/conftest.py` (fixture `conn` en DB mémoire).
- [ ] Lancer pytest → PASS.
- [ ] Commit `chore: squelette projet, config, schéma SQLite`.

---

### Task 2: Normalisation + déduplication

**Files:**
- Create: `pipeline/dedup.py`
- Test: `tests/test_dedup.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `normalize_company(name: str) -> str` (minuscule, sans accents, sans SAS/SARL/Inc/Ltd/GmbH, sans ponctuation, espaces réduits)
  - `normalize_title(title: str) -> str`
  - `canonical_url(url: str) -> str` (retire query de tracking `utm_*`, `ref`, `gh_*`, fragment ; host en minuscule ; garde le path)
  - `fingerprint(company: str, title: str, city: str) -> str` (sha1 hex des formes normalisées jointes par `|`)
  - `find_duplicate(conn, offer: dict) -> str | None` — étapes : match `url_canonical` exact → match `fingerprint` → fuzzy (`company_norm` égal ET `rapidfuzz.fuzz.token_sort_ratio(title_norm) >= 90`). Retourne l'`id` existant ou None.
  - `merge_sources(existing: dict, new: dict) -> dict` — append dans `sources[]` (dédupliqué par `source`), complète champs vides, `last_checked_at` = maintenant, `discovered_at` inchangé.

**Steps:**
- [ ] Écrire `tests/test_dedup.py` : normalisation ("Startup X SAS" == "startup x"), `fingerprint` stable, `canonical_url` retire `?utm_source=...`, test 6 du CDC (LinkedIn + Adzuna même offre → `find_duplicate` retrouve), fuzzy 90 % ("SDR Freelance" vs "SDR Freelance (H/F)" → match), faux négatif attendu ("SDR" vs "Growth Lead" même boîte → pas de match), `merge_sources` accumule 2 sources.
- [ ] pytest → FAIL.
- [ ] Implémenter `pipeline/dedup.py`.
- [ ] pytest → PASS.
- [ ] Commit `feat: normalisation et déduplication des offres`.

---

### Task 3: Filtres déterministes + détection catégorie/contrat/remote

**Files:**
- Create: `pipeline/filter_rules.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `config.yaml` (`exclude_title_patterns`, `exclude_description_patterns`, `penalty_patterns`, catégorie patterns, `locations`).
- Produces:
  - `classify(offer: dict, cfg: dict) -> dict` retournant un dict fusionné dans l'offre :
    `{category: "A"|"B"|"C"|"UNKNOWN", excluded: bool, exclude_reason: str|None,
      remote: "remote"|"hybrid"|"onsite"|"unknown", work_time: "fulltime"|"parttime"|"freelance"|"internship"|"unknown",
      work_time_hours: int|None, contract_type: str|None, penalty_flags: list[str],
      student_arrangement: bool}`
  - `is_excluded(offer, cfg) -> tuple[bool, str|None]` — titre matche `exclude_title_patterns` ET ne matche aucun pattern catégorie plus spécifique ; OU description matche `exclude_description_patterns`.
  - `detect_category(text, cfg) -> tuple[str, float]` — score par dict de patterns pondérés, argmax, UNKNOWN si < seuil.

**Steps:**
- [ ] Écrire `tests/test_filter_rules.py` couvrant tests CDC 1–5 :
  - "Machine Learning Engineer" + desc générique → `excluded=True`.
  - "AI Operations Intern - build workflows, no coding required" → `excluded=False`, `category="A"`.
  - "Sales Development Representative — freelance, 100% remote" → `category="B"`, `remote="remote"`, `work_time="freelance"`.
  - "Consultant IA junior — animation d'ateliers, aucun prérequis technique" → `category="C"`.
  - "CDD 39h/semaine, présence du lundi au vendredi" → `penalty_flags` contient `full_time_hours`, `student_arrangement=False`.
  - "Founder Associate (mi-temps possible pour étudiant)" → `student_arrangement=True`.
- [ ] pytest → FAIL.
- [ ] Implémenter `pipeline/filter_rules.py` + compléter les patterns dans `config.yaml`.
- [ ] pytest → PASS.
- [ ] Commit `feat: filtres déterministes et détection catégorie/contrat/remote`.

---

### Task 4: Scoring déterministe + priorité

**Files:**
- Create: `pipeline/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: sortie de `classify()`, `config.yaml` (`weights`, `thresholds`, `hard_preferences`, `reason_signal_map`), `pref_weights` (dernière ligne, via `store.db`).
- Produces:
  - `prescore(offer: dict, cfg: dict) -> tuple[int, dict]` — score déterministe seul (6 composantes design §8), retourne `(score_0_100, breakdown)` où `breakdown = {component: {points, max, reason}}`.
  - `final_score(offer: dict, cfg: dict, weights: dict, llm: dict|None) -> dict` — applique poids courants, ajoute `llm["score_adjustment"]` borné ±15, applique `hard_preferences` (plafonds/malus), clamp 0–100. Retourne `{score, priority, score_breakdown}`.
  - `priority_of(score, cfg) -> int` (1/2/3).

**Steps:**
- [ ] Écrire `tests/test_score.py` :
  - Founder Associate IA mi-temps remote → `prescore >= 70`, `final_score.priority in (1,2)`.
  - CDD 39h lundi-vendredi → composante "compatibilité étudiant" ≈ 0, `priority == 3`.
  - `hard_preferences.no_cold_calling=True` + offre "80% cold calling" → score plafonné (≤ 40).
  - `llm score_adjustment=+30` → effet réel plafonné à +15.
  - `breakdown` : somme des `points` pondérés == `score` (avant ajustement LLM).
- [ ] pytest → FAIL.
- [ ] Implémenter `pipeline/score.py`.
- [ ] pytest → PASS.
- [ ] Commit `feat: scoring déterministe explicable et calcul de priorité`.

---

### Task 5: Analyse LLM (Gemini) + fallback

**Files:**
- Create: `pipeline/llm_analyze.py`, `prompts/analyze_offer.md`
- Test: `tests/test_llm_analyze.py`

**Interfaces:**
- Consumes: `offer` (post-filtre), `GEMINI_API_KEY` (env).
- Produces:
  - `LLMAnalysis` (pydantic) : champs design §7.
  - `analyze(offer: dict, api_key: str|None) -> dict | None` — si `api_key` absent → None. Appelle `gemini-2.5-flash` (JSON mode), valide via pydantic ; sur erreur → retry `gemini-2.5-flash-lite` → sur échec total → None. Ne log jamais la clé.
  - `should_analyze(offer: dict, cfg: dict) -> bool` — `not excluded` et `prescore >= cfg["thresholds"]["llm"]["min_prescore"]` et `offer.get("llm_analysis") is None`.

**Steps:**
- [ ] Écrire `tests/test_llm_analyze.py` (mock `google.genai`) : réponse JSON valide → dict validé ; JSON cassé → retry puis None ; `api_key=None` → None sans appel réseau ; `should_analyze` respecte seuil et non-répétition.
- [ ] pytest → FAIL.
- [ ] Écrire `prompts/analyze_offer.md` (contexte profil §2 + placeholders offre + schéma JSON strict) et `pipeline/llm_analyze.py`.
- [ ] pytest → PASS.
- [ ] Commit `feat: analyse sémantique Gemini avec fallback déterministe`.

---

### Task 6: Sources à API keyless (base + The Muse + Remotive + Jobicy + HN)

**Files:**
- Create: `sources/base.py`, `sources/themuse.py`, `sources/remotive.py`, `sources/jobicy.py`, `sources/hn_whoishiring.py`
- Test: `tests/test_sources_keyless.py`, `tests/fixtures/*.json`

**Interfaces:**
- Produces:
  - `sources.base.RawOffer` = TypedDict/dataclass : `title, company, description, url, location, published_at, source, external_id, salary_raw, contract_type, work_time`.
  - `sources.base.http_get(url, **kw) -> httpx.Response` — timeout 20s, 3 retries backoff, UA réaliste rotatif.
  - Chaque module : `fetch(cfg: dict) -> list[RawOffer]` — lit ses queries dans `cfg["search_queries"]`, mappe la réponse, n'échoue jamais (retourne `[]` + log).
  - `sources.hn_whoishiring.fetch` : trouve le dernier thread via Algolia HN `search_by_date?tags=story&query="Ask HN: Who is hiring"`, récupère les commentaires racine, filtre par mots-clés.

**Steps:**
- [ ] Enregistrer des fixtures réelles (1 réponse JSON par source, tronquée) sous `tests/fixtures/`.
- [ ] Écrire `tests/test_sources_keyless.py` : chaque `fetch` sur fixture (monkeypatch `http_get`) → liste de `RawOffer` bien mappée ; réponse HTTP 500 → `[]` sans exception.
- [ ] pytest → FAIL.
- [ ] Implémenter `sources/base.py` puis les 4 modules.
- [ ] pytest → PASS.
- [ ] Commit `feat: sources keyless (The Muse, Remotive, Jobicy, HN Who's hiring)`.

---

### Task 7: Sources à clé (France Travail + Adzuna)

**Files:**
- Create: `sources/france_travail.py`, `sources/adzuna.py`
- Test: `tests/test_sources_keyed.py`, fixtures

**Interfaces:**
- Consumes: `sources.base`, env `FT_CLIENT_ID/FT_CLIENT_SECRET`, `ADZUNA_APP_ID/ADZUNA_APP_KEY`.
- Produces:
  - `france_travail.fetch(cfg)` — OAuth2 client_credentials (scope `api_offresdemploiv2 o2dsoffre`), token caché en mémoire, `GET /partenaire/offresdemploi/v2/offres/search` avec `motsCles`, `departement` (75,77,78,91,92,93,94,95), `typeContrat`, `range`. Mappe `dureeTravailLibelle`→work_time.
  - `adzuna.fetch(cfg)` — `GET /v1/api/jobs/fr/search/{page}` avec `what`, `where=Paris`, `max_days_old=30`, `results_per_page=50`. Aussi une passe `what_or` remote.
  - Clé absente → `fetch` retourne `[]` + log "source désactivée (clé manquante)".

**Steps:**
- [ ] Fixtures : réponse token FT + réponse search FT + réponse Adzuna.
- [ ] Écrire `tests/test_sources_keyed.py` : mapping correct, pagination, absence de clé → `[]`, erreur token → `[]`.
- [ ] pytest → FAIL.
- [ ] Implémenter les 2 modules.
- [ ] pytest → PASS.
- [ ] Commit `feat: sources France Travail et Adzuna`.

---

### Task 8: LinkedIn (endpoint invité) + WTTJ (Algolia) — best effort

**Files:**
- Create: `sources/linkedin.py`, `sources/wttj.py`
- Test: `tests/test_sources_besteffort.py`, fixtures (fragment HTML LinkedIn, réponse Algolia WTTJ)

**Interfaces:**
- Produces:
  - `linkedin.fetch(cfg)` — pour chaque query : `GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=&location=France&f_TPR=r604800&start=` avec pagination `start` 0..75, parse `selectolax` (`.base-card`), extrait titre/boîte/lieu/url/date. Backoff sur 429/999, `[]` après 2 échecs.
  - `wttj.fetch(cfg)` — POST vers l'endpoint Algolia WTTJ public (app id + api key dans `config.yaml > sources.wttj`), `hitsPerPage=50`, filtre `offices.country_code:FR`. Mappe hits. Toute erreur (clé rotée, 403) → `[]` + log.

**Steps:**
- [ ] Écrire `tests/test_sources_besteffort.py` : parse fragment HTML LinkedIn → RawOffers ; HTTP 999 → `[]` ; parse hits WTTJ → RawOffers ; 403 → `[]`.
- [ ] pytest → FAIL.
- [ ] Implémenter les 2 modules.
- [ ] pytest → PASS.
- [ ] Commit `feat: sources LinkedIn (guest) et WTTJ (best effort)`.

---

### Task 9: Ingestion des alertes email (IMAP)

**Files:**
- Create: `sources/email_inbox.py`
- Test: `tests/test_email_inbox.py`, fixtures (`.eml` LinkedIn alert, `.eml` Malt alert)

**Interfaces:**
- Consumes: env `GMAIL_USER/GMAIL_APP_PASSWORD`.
- Produces:
  - `email_inbox.fetch(cfg) -> list[RawOffer]` — IMAP `imap.gmail.com`, dossier `cfg["sources"]["email_inbox"]["label"]` (défaut `Veille`), messages non lus, dispatch parseur par expéditeur (`jobs-noreply@linkedin.com`, `jobalerts-noreply@linkedin.com`, `hello@malt.com`, etc.), extrait les liens d'offres + titres. Marque les messages lus. Clé absente → `[]`.
  - Parseurs dédiés : `_parse_linkedin(msg)`, `_parse_generic(msg)` (fallback : tous les liens qui ressemblent à une offre).

**Steps:**
- [ ] Écrire `tests/test_email_inbox.py` (monkeypatch `imaplib`) : `.eml` LinkedIn → N RawOffers avec URL `/jobs/view/...` ; expéditeur inconnu → parseur générique ; pas de creds → `[]`.
- [ ] pytest → FAIL.
- [ ] Implémenter `sources/email_inbox.py`.
- [ ] pytest → PASS.
- [ ] Commit `feat: ingestion des alertes emploi par email (IMAP)`.

---

### Task 10: Préférences apprises (ajustement des poids)

**Files:**
- Create: `pipeline/preferences.py`
- Test: `tests/test_preferences.py`

**Interfaces:**
- Consumes: `feedback`, `offers` (via `store.db`), `config.yaml` (`weights` défaut, `reason_signal_map`, `hard_preferences`).
- Produces:
  - `current_weights(conn, cfg) -> dict` — dernière ligne `pref_weights` sinon `cfg["weights"]`.
  - `recompute_weights(conn, cfg) -> dict | None` — compte les feedbacks ; `<10` → défauts ; `10-40` → nudge ±2 ; `>40` → nudge ±5 ; corrèle valeur de chaque composante (depuis `score_breakdown`) au verdict ; renormalise à 100 ; écrit une ligne `pref_weights` si changement ; retourne les nouveaux poids.
  - `explain_match(conn, offer) -> list[str]` — puces "correspond à X offres appréciées" (match company_norm / catégorie / remote / work_time avec offres `verdict in (up,star,applied,obtained)`).

**Steps:**
- [ ] Écrire `tests/test_preferences.py` : 5 feedbacks → poids inchangés ; 20 feedbacks tous "up" sur offres remote → poids localisation augmente de ≤ 2, somme == 100 ; `explain_match` retrouve une boîte déjà appréciée.
- [ ] pytest → FAIL.
- [ ] Implémenter `pipeline/preferences.py`.
- [ ] pytest → PASS.
- [ ] Commit `feat: ajustement lent des poids de scoring selon le feedback`.

---

### Task 11: Orchestrateur `scan` + archivage

**Files:**
- Modify: `main.py`
- Create: `pipeline/run.py`
- Test: `tests/test_run_scan.py`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces:
  - `pipeline.run.scan(conn, cfg, *, source_names=None) -> dict` (stats) — séquence design §15 : collecte (toutes `sources.*.fetch`, en gérant les exceptions), dedup+upsert, `classify`, `prescore`, `analyze` (si `should_analyze`), `final_score` avec `current_weights`, `record_run`, `recompute_weights`, archivage (`archived=1` si `discovered_at` > `cleanup.max_age_days` et `status in (new,seen)`).
  - `SOURCES` : registre `{name: fetch_callable}` dans `sources/__init__.py`.

**Steps:**
- [ ] Écrire `tests/test_run_scan.py` : registre de 2 fausses sources (une qui lève → scan continue), offre dupliquée entre les 2 → 1 ligne ; test CDC 7 (2e scan sans nouvelle offre → `stats["n_new"] == 0`) ; offre ancienne → `archived=1`.
- [ ] pytest → FAIL.
- [ ] Implémenter `pipeline/run.py`, brancher `main.py scan`.
- [ ] pytest → PASS.
- [ ] Commit `feat: orchestrateur de scan et archivage`.

---

### Task 12: Email — digest + alerte

**Files:**
- Create: `notify/email_digest.py`, `notify/alert.py`, `notify/templates/digest.html.j2`
- Modify: `main.py` (`digest`)
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `offers`, `state` (`last_digest_at`), env `GMAIL_USER/GMAIL_APP_PASSWORD`, `config.yaml` (`digest.max_items`, `digest.explore_ratio`).
- Produces:
  - `email_digest.build(conn, cfg) -> tuple[str subject, str html]` — offres `priority in (1,2)`, `status=new`, non archivées, `discovered_at > last_digest_at` ; tri score desc ; section exploration (`explore_ratio` de places pour `category=UNKNOWN` ou hors prefs, score brut ≥ 60) ; format design §12.
  - `email_digest.send(conn, cfg)` — build + `smtplib.SMTP_SSL` + set `last_digest_at`. Pas d'offres → mail court "RAS".
  - `alert.maybe_send(conn, cfg, new_offer_ids: list[str])` — s'il y a des `priority==1` parmi `new_offer_ids` jamais alertées → email court + marque `state alerted:<id>`.
  - `_send_mail(cfg, subject, html)` partagé.

**Steps:**
- [ ] Écrire `tests/test_notify.py` (monkeypatch smtplib) : digest contient une offre 85+, exclut une offre 65, respecte `max_items`, met à jour `last_digest_at` ; `alert.maybe_send` n'alerte pas deux fois la même offre ; pas de creds → skip propre.
- [ ] pytest → FAIL.
- [ ] Implémenter les 3 fichiers + template.
- [ ] pytest → PASS.
- [ ] Commit `feat: digest quotidien et alertes email prioritaires`.

---

### Task 13: Dashboard HTML statique

**Files:**
- Create: `report/build_html.py`, `report/template.html`
- Modify: `main.py` (`report`), `pipeline/run.py` (appel en fin de scan)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `offers` non archivées, `feedback`, `pref_weights`, `config.yaml` (`github.owner`, `github.repo` pour les liens issue).
- Produces:
  - `build_html.build(conn, cfg, out_dir="docs") -> None` — écrit `docs/data.json` (offres + stats §22.9) et `docs/index.html` (template + JS inline de filtrage/tri/recherche).
  - Liens feedback : `https://github.com/{owner}/{repo}/issues/new?labels=feedback&title=fb:{id}:{verdict}&body=reason:%20`.
  - `_stats(conn) -> dict` : analysées, retenues, taux feedback, candidatures, cat top/flop, boîtes appréciées, raisons de rejet, historique poids.

**Steps:**
- [ ] Écrire `tests/test_report.py` : `build` crée les 2 fichiers ; `data.json` contient N offres et le bloc `stats` ; les liens issue contiennent le bon `owner/repo` et `fb:<id>:up`.
- [ ] pytest → FAIL.
- [ ] Implémenter `report/build_html.py` + `report/template.html` (une page, vanilla JS, filtres catégorie/score/remote/statut + recherche + tri + section stats).
- [ ] pytest → PASS ; ouvrir `docs/index.html` localement pour vérif visuelle.
- [ ] Commit `feat: dashboard HTML statique avec filtres et stats`.

---

### Task 14: Ingestion feedback (issues GitHub)

**Files:**
- Create: `feedback/ingest.py`
- Modify: `main.py` (`ingest-feedback --issue N --title "..." --body "..." --author "..."`)
- Test: `tests/test_feedback_ingest.py`

**Interfaces:**
- Consumes: `store.db`, `pipeline.preferences.recompute_weights`.
- Produces:
  - `ingest.parse_title(title: str) -> tuple[str offer_id, str verdict] | None` — format `fb:<id>:<verdict>`, verdict ∈ {up,star,down,exclude,applied,obtained}.
  - `ingest.parse_reason(body: str) -> str | None` — ligne `reason: <enum>`.
  - `ingest.apply(conn, cfg, *, offer_id, verdict, reason, author) -> str` — insère `feedback`, applique effet sur `offers.status` (down→ignored, exclude→excluded + liste grise boîte, applied→applied, obtained→obtained/interesting, up→interesting, star→interesting), `recompute_weights`, retourne un message de confirmation. Ignore si `author != cfg["github"]["owner_login"]`.

**Steps:**
- [ ] Écrire `tests/test_feedback_ingest.py` : `parse_title("fb:abc123:down")` OK ; titre invalide → None ; `apply` insère + passe l'offre en `ignored` ; auteur non-owner → rejeté, pas d'écriture ; `exclude` ajoute la boîte à la liste grise.
- [ ] pytest → FAIL.
- [ ] Implémenter `feedback/ingest.py` + commande CLI.
- [ ] pytest → PASS.
- [ ] Commit `feat: ingestion du feedback depuis les issues GitHub`.

---

### Task 15: Workflows GitHub Actions + README

**Files:**
- Create: `.github/workflows/scan.yml`, `digest.yml`, `feedback.yml`
- Create: `README.md`
- Test: manuel (`workflow_dispatch` après push) + `python -c` smoke local

**Interfaces:**
- `scan.yml` : `on: schedule: - cron: "0 5,10,16,19 * * *"` + `workflow_dispatch` ; `concurrency: group: veille` ; job : checkout, setup-python 3.11, `pip install -r requirements.txt`, `python main.py scan`, commit `data/veille.db docs/` si diff (`git config user`, `[skip ci]`), push. Secrets → env.
- `digest.yml` : `cron: "0 6 * * *"` + dispatch ; `python main.py digest` ; commit state.
- `feedback.yml` : `on: issues: types: [opened]` ; `if: contains(github.event.issue.labels.*.name, 'feedback')` ; passe `--issue`, `--title`, `--body`, `--author` depuis `github.event.issue.*` ; commit DB ; commente + ferme l'issue via `gh`.
- `README.md` : §23 des livrables du CDC — architecture, sources + méthodes, stratégie de recherche, scoring, guide d'utilisation (lancer/modifier/maintenir), guide de déploiement (créer repo, activer Pages sur `docs/`, ajouter les 8 secrets, créer les alertes LinkedIn + filtre Gmail→label `Veille`), coûts, limites connues, roadmap V2/V3.

**Steps:**
- [ ] Écrire les 3 YAML + `README.md`.
- [ ] Smoke local : `python main.py init-db && python main.py scan --source themuse` (sans clés → doit tourner, remonter quelques offres, écrire la DB et `docs/`).
- [ ] Commit `ci: workflows scan/digest/feedback + documentation`.

---

### Task 16: POC réel + passe de validation des 7 tests

**Files:**
- Create: `docs/POC.md`
- Modify: correctifs éventuels suite aux tests

**Steps:**
- [ ] `pytest` complet → tout vert (les 7 cas CDC + unitaires).
- [ ] Exécuter `python main.py scan` en réel avec les clés disponibles (au minimum sources keyless + LinkedIn + Gemini si clé fournie).
- [ ] Extraire de la DB les meilleures offres, rédiger `docs/POC.md` : 5–10 offres réelles (titre, entreprise, catégorie, localisation, format, rémunération si dispo, score, raison du classement, URL, date). Si < 5 pertinentes → l'expliquer, donner le nombre réel.
- [ ] Corriger tout problème observé (filtrage trop large, faux exclus, scoring aberrant).
- [ ] Commit `test: POC réel et validation des 7 cas`.

---

## Self-Review

**Spec coverage :** sources §4 → T6-T9 ; dedup §10 → T2 ; filtres §6 → T3 ; scoring §8 → T4 ; LLM §7 → T5 ; apprentissage §9 → T10 + T14 ; DB §5 → T1 ; notifications §11-12 → T12 ; dashboard §13 → T13 ; feedback write-back §14 → T14 ; orchestration/cron §15 → T11 + T15 ; tests §18 → répartis (1→T3, 2→T3, 3→T3/T4, 4→T3, 5→T3/T4, 6→T2/T11, 7→T11) ; POC §20 → T16 ; coûts/limites/guides §21-22 + livrables → README T15. Couvert.

**Placeholders :** aucun "TBD/TODO" ; chaque tâche a interfaces + cas de test nommés. Le code complet ligne-à-ligne n'est pas recopié (le design §5-§15 le spécifie déjà en détail) — exécution en session avec le design comme référence.

**Type consistency :** `fingerprint()` / `find_duplicate()` / `merge_sources()` (T2) réutilisés en T11 ; `classify()` sortie (T3) consommée par `prescore()` (T4) et `should_analyze()` (T5) ; `current_weights()`/`recompute_weights()` (T10) appelées en T11 et T14 ; `RawOffer` (T6) produit par toutes les sources T6-T9 ; `_send_mail` partagé T12. Cohérent.
