"""
layout_engine.py
================

Calcul du layout hiérarchique des tickets dans un canevas 2D.

Principes :
* Le niveau (axe Y) d'un ticket est la longueur du plus long chemin
  depuis un ``root`` (ticket sans upstream). Les bloqueurs purs sont en
  haut, les plus bloqués en bas.
* Les orphelins (aucune relation) sont regroupés sur une ligne
  supplémentaire au bas du diagramme.
* Sur chaque niveau, les tickets sont répartis horizontalement de
  manière régulière et centrés.
* La largeur d'une boîte dépend de la longueur de son ``summary`` (180
  à 300 px) ; la hauteur est fixée à 120 px.
"""

from __future__ import annotations

from dataclasses import dataclass

from graph_builder import DepGraph


# Constantes de layout.
BOX_HEIGHT: int = 120
BOX_MIN_WIDTH: int = 180
BOX_MAX_WIDTH: int = 300
H_SPACING: int = 70   # espace horizontal entre boîtes (après leur largeur)
V_SPACING: int = 80   # espace vertical entre niveaux (après BOX_HEIGHT)
X_MARGIN: int = 80
Y_MARGIN: int = 80


@dataclass
class Box:
    """Rectangle positionné pour un ticket."""

    key: str
    x: float
    y: float
    width: float
    height: float


def _compute_box_width(summary: str) -> int:
    """Largeur proportionnelle à la taille du résumé, bornée."""
    # Approximation : ~8 px/caractère en police 16 monospace.
    est = 40 + len(summary) * 8
    return max(BOX_MIN_WIDTH, min(BOX_MAX_WIDTH, est))


def _assign_levels(graph: DepGraph) -> dict[str, int]:
    """Calcule le niveau de chaque ticket (longest path depuis les roots).

    Les cycles sont tolérés : on fait une propagation itérative bornée
    par le nombre de noeuds pour éviter une boucle infinie.
    """
    levels: dict[str, int] = {k: 0 for k in graph.nodes}
    n = len(graph.nodes)

    changed = True
    iterations = 0
    # Borne : en absence de cycle, n-1 itérations suffisent.
    while changed and iterations <= n:
        changed = False
        iterations += 1
        for node in graph.nodes:
            parents = graph.upstream.get(node, set())
            if not parents:
                continue
            candidate = max(levels[p] for p in parents) + 1
            if candidate > levels[node]:
                levels[node] = candidate
                changed = True

    return levels


def compute_layout(graph: DepGraph) -> dict[str, Box]:
    """Produit les coordonnées de chaque ticket.

    Args:
        graph: Graphe de dépendances construit par :mod:`graph_builder`.

    Returns:
        Dictionnaire ``{key: Box}`` avec la position absolue de chaque
        rectangle.
    """
    if not graph.nodes:
        return {}

    levels = _assign_levels(graph)

    # Regroupement par niveau, orphelins mis à part.
    orphans = set(graph.orphans())
    by_level: dict[int, list[str]] = {}
    for key, lvl in levels.items():
        if key in orphans:
            continue
        by_level.setdefault(lvl, []).append(key)

    # Niveau dédié aux orphelins : juste en dessous du dernier niveau.
    orphan_level: int | None = None
    if orphans:
        orphan_level = (max(by_level.keys()) + 1) if by_level else 0
        by_level[orphan_level] = sorted(orphans)

    # Tri déterministe des tickets dans un niveau : par ordre alpha des
    # clés, ce qui rend la sortie reproductible.
    for lvl in by_level:
        by_level[lvl].sort()

    # Pré-calcul des largeurs par niveau pour centrer.
    widths: dict[str, int] = {
        k: _compute_box_width(graph.nodes[k].summary) for k in graph.nodes
    }

    # Largeur totale du diagramme = largeur du niveau le plus chargé.
    level_widths: dict[int, int] = {}
    for lvl, keys in by_level.items():
        total = sum(widths[k] for k in keys) + H_SPACING * max(0, len(keys) - 1)
        level_widths[lvl] = total
    max_level_width = max(level_widths.values())

    boxes: dict[str, Box] = {}
    for lvl, keys in by_level.items():
        total = level_widths[lvl]
        # Centrage horizontal dans la largeur max.
        start_x = X_MARGIN + (max_level_width - total) / 2.0
        y = Y_MARGIN + lvl * (BOX_HEIGHT + V_SPACING)

        x_cursor = start_x
        for key in keys:
            w = widths[key]
            boxes[key] = Box(
                key=key,
                x=x_cursor,
                y=y,
                width=float(w),
                height=float(BOX_HEIGHT),
            )
            x_cursor += w + H_SPACING

    return boxes
