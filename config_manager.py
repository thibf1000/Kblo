"""
config_manager.py
=================

Gestion du fichier ``config.json`` de Kblo.

Le fichier est crée automatiquement au premier démarrage à côté de
``main.py``. Il stocke le domaine Jira configuré par l'utilisateur ainsi
que le dernier dossier d'export utilisé pour pré-remplir la boîte de
dialogue "Enregistrer sous...".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Emplacement du fichier de configuration : même dossier que ce module.
CONFIG_PATH: Path = Path(__file__).resolve().parent / "config.json"

# Valeurs par défaut au premier démarrage.
DEFAULT_CONFIG: dict[str, Any] = {
    "jira_domain": "",
    "last_export_path": "",
}


def load_config() -> dict[str, Any]:
    """Charge ``config.json`` ou le crée avec les valeurs par défaut.

    Returns:
        Dictionnaire de configuration, toujours valide (contient toutes
        les clés par défaut même si le fichier existait déjà mais était
        incomplet ou corrompu).
    """
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        # Fichier corrompu : on repart sur une base saine plutôt que
        # de faire crasher l'application.
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    # Complétion des clés manquantes pour garder la rétro-compatibilité.
    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return merged


def save_config(cfg: dict[str, Any]) -> None:
    """Sérialise la configuration dans ``config.json`` (indenté UTF-8).

    Args:
        cfg: Dictionnaire à persister. Seules les clés connues dans
            ``DEFAULT_CONFIG`` sont écrites pour éviter d'accumuler du
            bruit ajouté par un utilisateur curieux.
    """
    to_write = {k: cfg.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(to_write, fh, indent=2, ensure_ascii=False)


def normalize_domain(raw: str) -> str:
    """Normalise un domaine Jira saisi par l'utilisateur.

    - Ajoute ``https://`` si le schéma est absent.
    - Supprime le ``/`` final éventuel.
    - Tronque les espaces.

    Args:
        raw: Chaîne brute (ex: ``"company.atlassian.net"``).

    Returns:
        Domaine normalisé (ex: ``"https://company.atlassian.net"``).
        Chaîne vide si l'entrée est vide.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s.rstrip("/")
