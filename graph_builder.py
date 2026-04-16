"""
graph_builder.py
================

Construction d'un graphe dirigé des dépendances "blocks" à partir d'une
liste de :class:`csv_parser.Ticket`.

Convention adoptée :
* Une arête ``A -> B`` signifie **"A bloque B"** (A doit être terminé
  avant B). Dans l'affichage Excalidraw final, la flèche ira donc de A
  vers B, avec A placé plus haut que B.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from csv_parser import Ticket


@dataclass
class DepGraph:
    """Graphe dirigé des dépendances de blocage.

    Attributes:
        nodes: Dictionnaire ``{key: Ticket}``.
        downstream: ``{key: set(keys)}`` — tickets bloqués par ``key``.
        upstream: ``{key: set(keys)}`` — tickets qui bloquent ``key``.
        edges: Liste ordonnée des arêtes ``(bloqueur, bloqué)`` uniques.
        warnings: Messages générés pendant la construction (références
            inconnues, cycles).
    """

    nodes: dict[str, Ticket] = field(default_factory=dict)
    downstream: dict[str, set[str]] = field(default_factory=dict)
    upstream: dict[str, set[str]] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def roots(self) -> list[str]:
        """Tickets sans upstream (bloqueurs purs, au sommet)."""
        return [k for k in self.nodes if not self.upstream.get(k)]

    def orphans(self) -> list[str]:
        """Tickets sans relation entrante ni sortante."""
        return [
            k
            for k in self.nodes
            if not self.upstream.get(k) and not self.downstream.get(k)
        ]


def build_graph(tickets: list[Ticket]) -> DepGraph:
    """Construit un :class:`DepGraph` à partir des tickets parsés.

    - Les relations bidirectionnelles (A.blocks=[B] et B.blocked_by=[A])
      donnent une **seule** arête.
    - Les références vers des tickets absents du CSV sont ignorées avec
      un warning.
    - Les cycles éventuels sont détectés et signalés mais n'empêchent
      pas le graphe d'exister (le layout engine saura s'en accommoder).

    Args:
        tickets: Tickets produits par :func:`csv_parser.parse_jira_csv`.

    Returns:
        Un :class:`DepGraph` prêt à être passé au layout engine.
    """
    graph = DepGraph()
    graph.nodes = {t.key: t for t in tickets}

    # Initialisation des dicts d'adjacence pour tous les tickets.
    for key in graph.nodes:
        graph.downstream[key] = set()
        graph.upstream[key] = set()

    edge_set: set[tuple[str, str]] = set()
    missing_refs: set[str] = set()

    def _add_edge(blocker: str, blocked: str) -> None:
        if blocker == blocked:
            graph.warnings.append(
                f"Auto-référence ignorée sur le ticket {blocker}."
            )
            return
        if blocker not in graph.nodes:
            missing_refs.add(blocker)
            return
        if blocked not in graph.nodes:
            missing_refs.add(blocked)
            return
        edge = (blocker, blocked)
        if edge in edge_set:
            return
        edge_set.add(edge)
        graph.edges.append(edge)
        graph.downstream[blocker].add(blocked)
        graph.upstream[blocked].add(blocker)

    for ticket in tickets:
        for other in ticket.blocks:
            _add_edge(ticket.key, other)
        for other in ticket.blocked_by:
            _add_edge(other, ticket.key)

    if missing_refs:
        graph.warnings.append(
            "Références ignorées (tickets absents du CSV) : "
            + ", ".join(sorted(missing_refs))
        )

    cycles = _find_cycles(graph)
    if cycles:
        graph.warnings.append(
            "Cycles détectés dans les dépendances : "
            + "; ".join(" → ".join(c) for c in cycles)
        )

    return graph


def _find_cycles(graph: DepGraph) -> list[list[str]]:
    """DFS classique pour repérer les cycles.

    Renvoie au maximum un représentant par cycle pour éviter de noyer
    l'utilisateur sous les messages.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {k: WHITE for k in graph.nodes}
    parent: dict[str, str | None] = {k: None for k in graph.nodes}
    cycles: list[list[str]] = []
    seen_signatures: set[frozenset[str]] = set()

    def dfs(start: str) -> None:
        stack: list[tuple[str, iter]] = [(start, iter(sorted(graph.downstream[start])))]
        color[start] = GRAY

        while stack:
            node, children = stack[-1]
            nxt = next(children, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                continue
            if color[nxt] == WHITE:
                parent[nxt] = node
                color[nxt] = GRAY
                stack.append((nxt, iter(sorted(graph.downstream[nxt]))))
            elif color[nxt] == GRAY:
                # Reconstruction du cycle.
                cycle = [nxt]
                cur: str | None = node
                while cur is not None and cur != nxt:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.append(nxt)
                cycle.reverse()
                sig = frozenset(cycle)
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    cycles.append(cycle)

    for k in graph.nodes:
        if color[k] == WHITE:
            dfs(k)

    return cycles
