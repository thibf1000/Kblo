# Kblo — Jira Blocks → Excalidraw

Kblo transforme un export CSV Jira en schéma Excalidraw (`.excalidraw`)
montrant les relations **blocks / is blocked by** entre tickets, avec
un layout hiérarchique (bloqueurs en haut, bloqués en bas).

## Installation

```bash
cd Kblo
pip install -r requirements.txt
```

Dépendances :
- `pandas` — lecture CSV
- `tkinterdnd2` — drag-and-drop natif pour Tkinter

## Lancement

```bash
python main.py
```

Au premier démarrage, un fichier `config.json` est créé. Ouvrez
**Préférences** et configurez votre domaine Jira (ex :
`https://company.atlassian.net`). Si vous oubliez le `https://`, il est
ajouté automatiquement.

## Utilisation

1. Glissez un CSV d'export Jira dans la zone centrale (ou cliquez pour
   parcourir).
2. La barre de progression affiche les étapes :
   validation → parsing → graphe → layout → génération.
3. Une boîte de dialogue vous invite à enregistrer le fichier
   `.excalidraw`.
4. Ouvrez le fichier sur [excalidraw.com](https://excalidraw.com)
   (menu **File → Open**). Chaque rectangle est cliquable et pointe
   vers le ticket Jira.

## Format du CSV attendu

Colonnes reconnues (EN ou FR) :

| Rôle            | Anglais                                       | Français                                                      |
| --------------- | --------------------------------------------- | ------------------------------------------------------------- |
| Clé             | `Issue Key`, `Key`                            | `Clé de ticket`                                               |
| Résumé          | `Summary`, `Title`                            | `Résumé`                                                      |
| Type (optionnel)| `Issue Type`, `Type`                          | `Type de ticket`                                              |
| Blocks (sortant)| `Outward issue link (Blocks)`, `Blocks`       | `Lien de ticket sortant (Blocks)`                             |
| Blocked by      | `Inward issue link (Blocks)`, `Is blocked by` | `Lien du ticket entrant (Blocks)`                             |

Les colonnes dupliquées (plusieurs liens pour un même ticket) sont
gérées — que pandas les renomme en `.1`, `.2`… ou que Jira les exporte
avec un suffixe `_N`.

Exemple minimal (FR, format Jira réel — voir
[examples/jira_export_sample.csv](examples/jira_export_sample.csv)) :

```csv
Résumé,Clé de ticket,Type de ticket,Lien du ticket entrant (Blocks),Lien de ticket sortant (Blocks)
Auth refactoring,PROJ-2,Story,,PROJ-1
Login bug,PROJ-1,Task,PROJ-2,PROJ-3
Database migration,PROJ-3,Task,PROJ-1,
```

## Rendu visuel

- **Tickets standard** (Story, Task, Bug…) : bordure noire.
- **Epics** : bordure bleue épaisse, pour se repérer d'un coup d'œil.
- **Flèches** : du bloqueur vers le bloqué (top → bottom).
- **Liens cliquables** : clic sur un rectangle → ouverture du ticket
  sur `{jira_domain}/browse/{KEY}`.

## Structure du projet

```
Kblo/
├── main.py                  # Interface Tkinter + orchestration
├── config_manager.py        # Gestion config.json
├── validators.py            # Validation CSV / domaine
├── csv_parser.py            # Parsing CSV Jira
├── graph_builder.py         # Graphe de dépendances
├── layout_engine.py         # Layout hiérarchique
├── excalidraw_generator.py  # Sérialisation .excalidraw (v2)
├── requirements.txt
└── config.json              # Créé au 1er démarrage
```

## Limites

- Recommandé jusqu'à **50 tickets** pour un rendu lisible (un
  avertissement s'affiche au-delà).
- Les cycles de dépendances sont détectés et signalés en warning, mais
  n'empêchent pas la génération.
- Seules les relations `blocks` / `is blocked by` sont exploitées.
