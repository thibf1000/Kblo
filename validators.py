"""
validators.py
=============

Validations partagées pour Kblo : CSV fourni par l'utilisateur et
domaine Jira. Toutes les erreurs sont levées sous forme de
``KbloValidationError`` avec un message en français prêt à afficher.
"""

from __future__ import annotations

import re
from pathlib import Path


class KbloValidationError(Exception):
    """Erreur de validation avec message utilisateur en français."""


# Regex tolérante pour un domaine HTTP(S) simple.
_DOMAIN_RE = re.compile(
    r"^https?://[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+"
    r"(:\d+)?(/.*)?$"
)


def validate_csv_file(path: Path) -> str:
    """Valide qu'un fichier CSV est utilisable.

    Vérifie l'existence, l'extension, la taille et l'encodage. Renvoie
    l'encodage détecté (``"utf-8"`` ou ``"latin-1"``) afin que le parser
    puisse réutiliser la même valeur.

    Args:
        path: Chemin du fichier à vérifier.

    Returns:
        Encodage à utiliser pour la lecture ultérieure.

    Raises:
        KbloValidationError: Fichier inexistant, vide, mauvaise
            extension ou encodage illisible.
    """
    if not path.exists() or not path.is_file():
        raise KbloValidationError(f"Le fichier est introuvable : {path}")

    if path.suffix.lower() != ".csv":
        raise KbloValidationError(
            "Le fichier sélectionné n'est pas un .csv."
        )

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise KbloValidationError(
            f"Impossible de lire le fichier : {exc}"
        ) from exc

    if size == 0:
        raise KbloValidationError("Le fichier CSV est vide.")

    # On essaye UTF-8 puis latin-1 en fallback.
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=encoding) as fh:
                # Lecture d'un échantillon suffisant pour détecter les
                # erreurs d'encodage sans charger tout le fichier.
                fh.read(8192)
            return encoding
        except UnicodeDecodeError:
            continue

    raise KbloValidationError(
        "Erreur d'encoding : impossible de lire le fichier "
        "(UTF-8 ou Latin-1 attendu)."
    )


def validate_jira_domain(domain: str) -> bool:
    """Indique si le domaine a une forme plausible (http(s)://...).

    Args:
        domain: Chaîne à tester (déjà normalisée de préférence).

    Returns:
        ``True`` si le domaine matche la regex, ``False`` sinon.
    """
    if not domain:
        return False
    return bool(_DOMAIN_RE.match(domain.strip()))


def ensure_jira_domain(domain: str) -> None:
    """Raise si le domaine n'est pas configuré ou invalide.

    Args:
        domain: Domaine Jira à contrôler.

    Raises:
        KbloValidationError: Avec un message adapté (vide vs invalide).
    """
    if not domain:
        raise KbloValidationError(
            "Veuillez configurer le domaine Jira dans les préférences."
        )
    if not validate_jira_domain(domain):
        raise KbloValidationError("Format de domaine Jira invalide.")
