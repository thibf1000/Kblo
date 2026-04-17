"""
excalidraw_generator.py
=======================

Sérialisation du diagramme au format ``.excalidraw`` officiel
(compatible `excalidraw.com`_).

Chaque ticket produit :

* un élément ``rectangle`` (avec ``link`` pointant vers Jira) ;
* un élément ``text`` lié au rectangle via ``containerId``.

Chaque relation de blocage produit une ``arrow`` avec ``startBinding``
et ``endBinding`` rattachés aux rectangles concernés. La flèche part du
**bloqueur** et pointe vers le **bloqué**.

.. _excalidraw.com: https://excalidraw.com
"""

from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path

from csv_parser import Ticket
from graph_builder import DepGraph
from layout_engine import Box


# Palette Excalidraw officielle — on s'aligne sur leurs valeurs pour rester
# cohérent si l'utilisateur édite ensuite le diagramme.
STROKE_DEFAULT = "#1e1e1e"  # noir « Excalidraw »
STROKE_EPIC = "#1971c2"     # bleu « Excalidraw »


def stroke_color_for(ticket: Ticket) -> str:
    """Couleur de bordure du rectangle selon le type de ticket.

    Les Epics sont bleus pour se détacher visuellement ; les autres
    types (Story, Task, Bug, Enabler…) restent noirs.
    """
    return STROKE_EPIC if ticket.is_epic else STROKE_DEFAULT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    """Identifiant court unique pour un élément Excalidraw."""
    return uuid.uuid4().hex[:16]


def _seed() -> int:
    """Valeur pseudo-aléatoire attendue par Excalidraw (seed / nonce)."""
    return random.randint(1, 2**31 - 1)


def _now_ms() -> int:
    """Timestamp ms, utilisé pour le champ ``updated``."""
    return int(time.time() * 1000)


def _base_element(
    elem_type: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    stroke_color: str = STROKE_DEFAULT,
    background_color: str = "#ffffff",
    link: str | None = None,
) -> dict:
    """Squelette commun à tous les éléments Excalidraw v2."""
    return {
        "id": _new_id(),
        "type": elem_type,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": stroke_color,
        "backgroundColor": background_color,
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _seed(),
        "version": 1,
        "versionNonce": _seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": _now_ms(),
        "link": link,
        "locked": False,
    }


def _truncate(summary: str, max_len: int = 40) -> str:
    """Raccourcit un résumé pour qu'il rentre proprement dans la boîte."""
    s = summary.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Éléments
# ---------------------------------------------------------------------------

def _make_rectangle(box: Box, link: str, stroke_color: str, epic: bool = False) -> dict:
    """Rectangle cliquable pour un ticket.

    Args:
        box: Position et taille calculées par le layout engine.
        link: URL Jira à associer (clic sur le rectangle).
        stroke_color: Couleur de bordure (dépend du type de ticket).
        epic: Si True, utilise un trait épais pour accentuer les Epics.
    """
    rect = _base_element(
        "rectangle",
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
        stroke_color=stroke_color,
        link=link,
    )
    if epic:
        rect["strokeWidth"] = 2
    return rect


def _make_text(box: Box, container_id: str, content: str) -> dict:
    """Texte centré (font monospace) lié au rectangle."""
    elem = _base_element(
        "text",
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
    )
    elem.update(
        {
            "text": content,
            "fontSize": 16,
            "fontFamily": 3,  # 3 = Cascadia (monospace) dans Excalidraw.
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": 18,
            "containerId": container_id,
            "originalText": content,
            "lineHeight": 1.25,
            "autoResize": True,
        }
    )
    return elem


def _make_arrow(
    start_rect: dict,
    end_rect: dict,
) -> dict:
    """Flèche orientée ``start_rect -> end_rect`` avec bindings."""
    # Bords d'attache : bas du rectangle source, haut du rectangle cible.
    sx = start_rect["x"] + start_rect["width"] / 2
    sy = start_rect["y"] + start_rect["height"]
    ex = end_rect["x"] + end_rect["width"] / 2
    ey = end_rect["y"]

    dx = ex - sx
    dy = ey - sy

    arrow = _base_element(
        "arrow",
        x=sx,
        y=sy,
        width=abs(dx),
        height=abs(dy),
    )
    arrow.update(
        {
            "points": [[0, 0], [dx, dy]],
            "lastCommittedPoint": None,
            "startBinding": {
                "elementId": start_rect["id"],
                "focus": 0,
                "gap": 4,
            },
            "endBinding": {
                "elementId": end_rect["id"],
                "focus": 0,
                "gap": 4,
            },
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "elbowed": False,
        }
    )

    # Les rectangles doivent référencer la flèche dans boundElements
    # pour que les bindings fonctionnent à l'ouverture dans Excalidraw.
    for rect in (start_rect, end_rect):
        rect["boundElements"] = rect.get("boundElements") or []
        rect["boundElements"].append({"id": arrow["id"], "type": "arrow"})

    return arrow


# ---------------------------------------------------------------------------
# Entrée publique
# ---------------------------------------------------------------------------

def generate_excalidraw(
    graph: DepGraph,
    layout: dict[str, Box],
    jira_domain: str,
) -> dict:
    """Construit le document Excalidraw complet.

    Args:
        graph: Graphe de dépendances.
        layout: Coordonnées calculées par :mod:`layout_engine`.
        jira_domain: Domaine Jira normalisé (``https://...``).

    Returns:
        Dictionnaire JSON-sérialisable conforme au schéma Excalidraw v2.
    """
    elements: list[dict] = []
    rect_by_key: dict[str, dict] = {}

    # Rectangles + textes.
    for key, box in layout.items():
        ticket = graph.nodes[key]
        link = f"{jira_domain}/browse/{key}"
        stroke = stroke_color_for(ticket)
        rect = _make_rectangle(box, link=link, stroke_color=stroke, epic=ticket.is_epic)
        elements.append(rect)
        rect_by_key[key] = rect

        content = f"{key}\n{_truncate(ticket.summary)}"
        text = _make_text(box, container_id=rect["id"], content=content)
        # Le rectangle référence le text via boundElements.
        rect["boundElements"].append({"id": text["id"], "type": "text"})
        elements.append(text)

    # Flèches : de bloqueur vers bloqué.
    for blocker, blocked in graph.edges:
        if blocker not in rect_by_key or blocked not in rect_by_key:
            continue
        arrow = _make_arrow(rect_by_key[blocker], rect_by_key[blocked])
        elements.append(arrow)

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": "#ffffff",
        },
        "files": {},
    }


def write_excalidraw(document: dict, target: Path) -> None:
    """Écrit le document Excalidraw sur disque (UTF-8, indenté)."""
    with target.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=False)
