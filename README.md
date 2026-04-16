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

Colonnes minimales :
- **Issue Key** (ou `Key`)
- **Summary** (ou `Title`)
- Au moins une colonne contenant les mots `Blocks`, `Blocked By` ou
  `Linked Issues`.

Exemple minimal :

```csv
Issue Key,Summary,Linked Issues
PROJ-1,Login bug,PROJ-2 blocks this
PROJ-2,Auth refactoring,
PROJ-3,Database migration,PROJ-1 blocks this
```

Kblo reconnaît aussi les colonnes dédiées typiques de Jira :
`Outward issue link (Blocks)`, `Inward issue link (Blocks)`, etc. — et
leurs doublons.

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
