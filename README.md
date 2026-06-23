# Veille RSS filtrée par mots-clés

Agrège plusieurs flux RSS, ne garde que les articles contenant certains
mots-clés (grève, manifestation, PSE, licenciements, PIP…), produit **un flux
RSS unique** (`feed.xml`) et **notifie les nouveaux articles sur Discord**.

Les 4 sites de départ ont tous un flux RSS natif (vérifié) — aucun scraping
n'est nécessaire. Pour ajouter plus tard un site *sans* flux, voir la fin.

## Installation (WSL / Linux)

```bash
cd ~/claude/info_suivi
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Premier lancement

```bash
# Initialise le flux sans spammer Discord avec tout l'historique :
./.venv/bin/python veille.py --no-notify
```

Cela crée :
- `feed.xml` — le flux agrégé filtré (à ouvrir dans ton lecteur RSS) ;
- `seen.json` — la mémoire des articles déjà vus (anti-doublon).

## Notifications Discord

Le webhook est stocké dans `.env` (ignoré par git), au format :

```
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/...."
```

Pour le créer/modifier : **Paramètres du salon → Intégrations → Webhooks**, copie
l'URL et colle-la dans `.env`. Le script `run.sh` charge ce fichier
automatiquement.

> Au tout premier run, aucune notif n'est envoyée (anti-flood) : seul le flux
> est initialisé. Les runs suivants ne notifient que les **nouveaux** articles.

## Automatisation (déjà en place)

Une tâche cron lance la veille **toutes les 30 minutes** via `run.sh`
(qui charge `.env` puis exécute `veille.py`) :

```cron
*/30 * * * * run.sh >> veille.log 2>&1
```

- Voir / éditer : `crontab -l` / `crontab -e`
- Logs : `tail -f veille.log`
- Lancer manuellement : `./run.sh`

> Sous WSL, cron ne tourne que quand WSL est ouvert. Pour du 24/7 sans PC
> allumé, voir la section GitHub Actions ci-dessous.

## Option 24/7 : GitHub Actions + flux RSS public

Le workflow `.github/workflows/veille.yml` exécute la veille toutes les 30 min
dans le cloud (gratuit), puis **commite `feed.xml` dans le dépôt** : tu obtiens
une **URL de flux stable** à coller dans ton appli RSS.

### Mise en place (une fois)

```bash
cd ~/claude/info_suivi
git init -b main
git add .
git commit -m "Veille RSS initiale"
gh repo create info_suivi --public --source=. --push   # ou via le site github.com
```

> **Public ou privé ?** Pour que ton appli RSS puisse lire le flux **sans
> authentification**, le dépôt doit être **public** (un flux `raw...` de dépôt
> privé exige un token ; GitHub Pages sur dépôt privé exige un compte payant).
> Un dépôt public n'expose rien de sensible ici : `.env` (le webhook) reste
> ignoré par git ; seuls le code, les mots-clés et les articles d'actu publique
> (`feed.xml`, `seen.json`) sont visibles.

Puis, dans le dépôt GitHub :

1. **Settings → Secrets and variables → Actions → New repository secret**
   - Nom : `DISCORD_WEBHOOK_URL`
   - Valeur : l'URL de ton webhook (le même que dans `.env`).
2. **Actions** → autorise l'exécution si demandé → ouvre « Veille RSS » →
   **Run workflow** pour un premier lancement immédiat (sinon attends le cron).

> `.env`, `seen.json` et `feed.xml` ne sont pas poussés (ils sont dans
> `.gitignore`). Le secret vit dans GitHub ; le workflow régénère `feed.xml`
> et `seen.json` et les commite lui-même (`git add -f`).

### L'URL de ton flux RSS

Une fois le workflow passé au moins une fois (commit de `feed.xml`) :

- **Simple, sans config** (à coller dans la plupart des lecteurs/apps) :
  `https://raw.githubusercontent.com/<TON_USER>/info_suivi/main/feed.xml`
- **Propre, via GitHub Pages** (Settings → Pages → *Deploy from a branch* →
  `main` / `root`) :
  `https://<TON_USER>.github.io/info_suivi/feed.xml`

> ⚠️ Si tu actives GitHub Actions, **désactive le cron local** (`crontab -e`,
> supprime la ligne `run.sh`) pour ne pas recevoir les notifications Discord
> en double.
>
> ⚠️ GitHub désactive les workflows planifiés après 60 jours sans activité sur
> le dépôt, et peut décaler le déclenchement de quelques minutes en heure de
> pointe.

## Lire le flux

Ouvre `feed.xml` dans ton lecteur (Thunderbird, Feedly via fichier local, etc.).
Une fois publié en ligne (serveur perso ou GitHub Pages), tu pointeras ton
lecteur sur son URL `https://…/feed.xml`.

## Personnaliser

Tout est dans `config.yaml` :

- **Ajouter une source** : ajoute un bloc `- name: … / url: …` sous `sources`.
- **Mots-clés** : édite la liste `keywords`.
  - Un mot en **MAJUSCULES** (`PSE`, `PIP`, `RCC`) → correspondance **exacte**
    du mot (évite les faux positifs comme « pip » dans « pipeline »).
  - Un mot normal (`grève`, `licenciement`) → correspondance sur la **racine**
    (matche « grèves », « licenciements », « licencié·es »…).
  - Accents et casse sont toujours ignorés.

## Plus tard : un site SANS flux RSS

Le script lit du RSS. Pour un site qui n'en a pas, deux options :

1. **RSS-Bridge** (outil open-source) génère un flux RSS pour beaucoup de sites
   connus, voire un site arbitraire via sélecteurs CSS. On ajoute ensuite son
   URL dans `sources` — le reste (filtrage, agrégation, Discord) ne change pas.
2. Ajouter au script une petite fonction de scraping (requests + BeautifulSoup)
   pour ce site précis, qui renvoie la même structure d'article que `fetch_source`.

Dis-le-moi quand le besoin se présente, on branchera ça.
