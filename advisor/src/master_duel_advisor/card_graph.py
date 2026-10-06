"""SQLiteのカード関係。関係の存在を効果の合法性と混同しません。"""
from collections import deque
from enum import StrEnum
from pathlib import Path
import sqlite3

from pydantic import Field

from .models import Model


class Relation(StrEnum):
    SEARCH = "SEARCH"
    SPECIAL_SUMMON = "SPECIAL_SUMMON"
    SEND_TO_GRAVE = "SEND_TO_GRAVE"
    ADD_FROM_GRAVE = "ADD_FROM_GRAVE"
    BANISH = "BANISH"
    FUSION_MATERIAL = "FUSION_MATERIAL"
    LINK_MATERIAL = "LINK_MATERIAL"
    REVIVE = "REVIVE"
    RETURN_TO_DECK = "RETURN_TO_DECK"


class Edge(Model):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: Relation
    condition: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class CardGraph:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS card_edges (source TEXT, target TEXT, relation TEXT, data TEXT, PRIMARY KEY(source,target,relation))")
        self.db.execute("CREATE INDEX IF NOT EXISTS edges_source ON card_edges(source)")
        self.db.commit()

    def import_edges(self, edges: list[Edge]):
        with self.db:
            self.db.executemany("INSERT INTO card_edges VALUES (?,?,?,?) ON CONFLICT(source,target,relation) DO UPDATE SET data=excluded.data",
                                [(e.source,e.target,e.relation,e.model_dump_json()) for e in edges])

    def outgoing(self, source: str) -> list[Edge]:
        return [Edge.model_validate_json(row[0]) for row in self.db.execute(
            "SELECT data FROM card_edges WHERE source=? ORDER BY target,relation", (source,))]

    def paths(self, source: str, target: str, max_depth: int = 4, max_nodes: int = 100):
        if not 1 <= max_depth <= 8 or not 1 <= max_nodes <= 1000:
            raise ValueError("探索の深さは1〜8、探索ノード数は1〜1000で指定してください")
        queue = deque([(source, [], {source})])
        expanded = 0
        while queue and expanded < max_nodes:
            node,path,seen = queue.popleft()
            expanded += 1
            for edge in self.outgoing(node):
                if edge.target in seen:
                    continue
                route = path + [edge]
                if edge.target == target:
                    yield route
                elif len(route) < max_depth:
                    queue.append((edge.target, route, seen | {edge.target}))

    def close(self):
        self.db.close()
