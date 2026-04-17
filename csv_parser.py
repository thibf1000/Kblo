"""
csv_parser.py
=============

Lecture et interprétation d'un export CSV Jira.

Les exports Jira sont volontairement souples : selon l'instance, les
relations "blocks" / "is blocked by" peuvent apparaître :

* Sous forme d'une colonne ``Linked Issues`` contenant du texte libre
  comme ``"PROJ-2 blocks this"`` ou ``"is blocked by PROJ-3"``.
* Sous forme de colonnes dédiées type ``Outward issue link (Blocks)``
  ou ``Inward issue link (Blocks)`` avec la clé du ticket lié en valeur
  (souvent plusieurs colonnes du même nom se côtoient).

Ce module absorbe ces variations et renvoie une liste de
:class:`Ticket` prête à être traitée par :mod:`graph_builder`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from validators import KbloValidationError


logger = logging.getLogger(__name__)


# Pattern des clés Jira (ex: PROJ-123, AB12-4567).
_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

# Pattern pour extraire les relations au format texte libre.
# Ex : "PROJ-2 blocks this", "is blocked by PROJ-3".
_REL_RE = re.compile(
    r"(?:(?P<left>[A-Z][A-Z0-9]+-\d+)\s+)?"
    r"(?P<verb>blocks|is\s+blocked\s+by|blocked\s+by)"
    r"(?:\s+(?P<right>[A-Z][A-Z0-9]+-\d+|this))?",
    re.IGNORECASE,
)


@dataclass
class Ticket:
    """Un ticket Jira et ses relations de blocage."""

    key: str
    summary: str
    issue_type: str = ""                                 # ex: "Epic", "Story", "Task"
    blocks: list[str] = field(default_factory=list)      # clés bloquées par ce ticket
    blocked_by: list[str] = field(default_factory=list)  # clés qui bloquent ce ticket

    @property
    def is_epic(self) -> bool:
        """True si le ticket est de type Epic (insensible à la casse)."""
        return self.issue_type.strip().lower() == "epic"


@dataclass
class ParseReport:
    """Retour du parser incluant les warnings à afficher."""

    tickets: list[Ticket]
    warnings: list[str]


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    """Trouve la première colonne dont le nom normalisé matche une des options.

    Args:
        columns: Liste réelle des colonnes (casse/espaces quelconques).
        candidates: Liste de noms cibles en minuscules déjà normalisés.

    Returns:
        Le nom exact de la colonne dans le DataFrame, ou None.
    """
    norm = {c: c.strip().lower() for c in columns}
    for col, low in norm.items():
        if low in candidates:
            return col
    return None


def _find_link_columns(columns: list[str]) -> list[str]:
    """Renvoie toutes les colonnes susceptibles de contenir des liens blocks/blocked.

    Capture à la fois les formats anglais (``Outward issue link (Blocks)``,
    ``Blocks``, ``Is blocked by``…) et français (``Lien du ticket entrant
    (Blocks)``, ``Lien de ticket sortant (Blocks)``…) et leurs doublons
    renommés par pandas (``.1``, ``.2``, ``_2``…).

    Les autres types de liens (``Cloners``, ``Parent-Child``, ``Relates``…)
    sont volontairement ignorés : Kblo ne modélise que les blocages.
    """
    hits: list[str] = []
    for c in columns:
        low = c.strip().lower()
        if "block" in low:  # capture toute variante EN/FR contenant "Block(s)"
            hits.append(c)
        elif low in ("linked issues", "linked issue"):
            hits.append(c)
    return hits


def _classify_link_column(col_name: str) -> str | None:
    """Détermine si une colonne représente des "blocks" ou "blocked by".

    Support EN et FR :
    - ``Inward`` / ``entrant`` / ``is blocked by`` → ``blocked_by``
    - ``Outward`` / ``sortant`` / ``blocks`` → ``blocks``

    Returns:
        ``"blocks"``, ``"blocked_by"`` ou ``None`` si on ne peut pas trancher
        (colonne générique type ``Linked Issues`` qu'il faudra parser ligne
        à ligne).
    """
    low = col_name.lower()

    # Direction "entrante" → ce ticket est bloqué PAR la clé de la cellule.
    if (
        "blocked by" in low
        or "blocked-by" in low
        or "entrant" in low
        or "inward" in low
    ):
        return "blocked_by"

    # Direction "sortante" → ce ticket bloque la clé de la cellule.
    if "sortant" in low or "outward" in low or "blocks" in low:
        return "blocks"

    return None


def _extract_from_free_text(
    value: str,
    warnings: list[str],
    row_key: str,
) -> tuple[list[str], list[str]]:
    """Parse un texte libre style "PROJ-2 blocks this".

    Returns:
        Tuple ``(blocks, blocked_by)`` : clés bloquées / clés bloquantes.
    """
    blocks: list[str] = []
    blocked_by: list[str] = []

    for match in _REL_RE.finditer(value):
        verb = re.sub(r"\s+", " ", match.group("verb").lower())
        left = match.group("left")
        right = match.group("right")

        # On veut la clé "distante" (pas "this").
        distant = None
        if left and left.upper() != "THIS":
            distant = left
        elif right and right.upper() != "THIS":
            distant = right

        if not distant:
            warnings.append(
                f"Ligne {row_key}: relation '{match.group(0)}' ignorée "
                "(clé distante introuvable)."
            )
            continue

        distant = distant.upper()
        if verb == "blocks":
            # "<distant> blocks this" → distant bloque row_key.
            if left and left.upper() != "THIS" and (not right or right.lower() == "this"):
                blocked_by.append(distant)
            else:
                # "this blocks <distant>" → row_key bloque distant.
                blocks.append(distant)
        else:  # "is blocked by" / "blocked by"
            if left and left.upper() != "THIS" and (not right or right.lower() == "this"):
                # "<distant> is blocked by this" → row_key bloque distant.
                blocks.append(distant)
            else:
                blocked_by.append(distant)

    return blocks, blocked_by


def parse_jira_csv(path: Path, encoding: str = "utf-8") -> ParseReport:
    """Parse un CSV Jira et renvoie la liste des tickets + warnings.

    Args:
        path: Chemin du fichier CSV déjà validé.
        encoding: Encodage détecté par :func:`validators.validate_csv_file`.

    Returns:
        :class:`ParseReport` avec tickets et warnings non bloquants.

    Raises:
        KbloValidationError: Le CSV n'a pas les colonnes obligatoires
            (clé, résumé et au moins une colonne de liens).
    """
    try:
        df = pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError as exc:
        raise KbloValidationError("Le fichier CSV est vide.") from exc
    except pd.errors.ParserError as exc:
        raise KbloValidationError(
            f"Le fichier n'est pas un CSV valide : {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise KbloValidationError(
            "Erreur d'encoding (UTF-8 attendu)."
        ) from exc

    if df.empty:
        raise KbloValidationError("Le fichier CSV ne contient aucune ligne de données.")

    columns = list(df.columns)
    # Clé de ticket : EN ou FR.
    key_col = _find_column(columns, ["issue key", "key", "clé de ticket", "cle de ticket"])
    # Résumé : EN ou FR.
    summary_col = _find_column(columns, ["summary", "title", "résumé", "resume"])
    # Type de ticket : EN ou FR (facultatif, utilisé pour colorer les Epics).
    type_col = _find_column(columns, ["issue type", "type", "type de ticket"])
    link_cols = _find_link_columns(columns)

    missing: list[str] = []
    if not key_col:
        missing.append("Clé de ticket / Issue Key")
    if not summary_col:
        missing.append("Résumé / Summary")

    if missing:
        raise KbloValidationError(
            "Colonnes obligatoires manquantes: " + ", ".join(missing)
        )

    if not link_cols:
        raise KbloValidationError(
            "Aucune colonne de liens (Blocks / Linked Issues) trouvée."
        )

    warnings: list[str] = []
    tickets: list[Ticket] = []
    seen_keys: set[str] = set()

    for idx, row in df.iterrows():
        raw_key = str(row[key_col]).strip()
        if not raw_key:
            warnings.append(f"Ligne {idx + 2}: clé manquante, ignorée.")
            continue

        # Extraction robuste de la clé si elle est collée à d'autres tokens.
        match = _KEY_RE.search(raw_key)
        key = match.group(1) if match else raw_key
        key = key.upper()

        if key in seen_keys:
            warnings.append(f"Clé {key} en doublon, ligne {idx + 2} ignorée.")
            continue
        seen_keys.add(key)

        summary = str(row[summary_col]).strip()
        issue_type = str(row[type_col]).strip() if type_col else ""

        blocks: list[str] = []
        blocked_by: list[str] = []

        for col in link_cols:
            cell = str(row[col]).strip()
            if not cell:
                continue

            kind = _classify_link_column(col)
            if kind == "blocks":
                blocks.extend(k.upper() for k in _KEY_RE.findall(cell))
            elif kind == "blocked_by":
                blocked_by.extend(k.upper() for k in _KEY_RE.findall(cell))
            else:
                # Colonne générique : on parse le texte libre.
                b, bb = _extract_from_free_text(cell, warnings, key)
                blocks.extend(b)
                blocked_by.extend(bb)

        # Déduplication locale tout en préservant l'ordre.
        blocks = list(dict.fromkeys(blocks))
        blocked_by = list(dict.fromkeys(blocked_by))

        tickets.append(
            Ticket(
                key=key,
                summary=summary,
                issue_type=issue_type,
                blocks=blocks,
                blocked_by=blocked_by,
            )
        )

    if not tickets:
        raise KbloValidationError(
            "Aucun ticket exploitable n'a pu être extrait du CSV."
        )

    return ParseReport(tickets=tickets, warnings=warnings)
