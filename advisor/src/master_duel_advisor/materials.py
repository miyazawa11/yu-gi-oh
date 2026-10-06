"""素材集合そのものの検査。召喚制限・リンク先・耐性は別途確認が必要。"""
from itertools import product

from .models import Material


def valid_materials(method: str, materials: list[Material]) -> bool:
    """同じ個体の二重使用を禁止。カード名は現在適用中の名称を渡す。"""
    if not materials or len({m.instance for m in materials}) != len(materials):
        return False
    if method == "colossus":
        return len(materials) == 1 and all(m.zone == "field" and m.face_up and m.race == "Thunder"
            and m.effect and not m.fusion and not m.token for m in materials)
    if method == "titan_alternative":
        return len(materials) == 2 and any(m.zone == "hand" and m.race == "Thunder" for m in materials) and any(
            m.zone == "field" and m.face_up and m.race == "Thunder" and m.fusion
            and m.card_id != "13924" for m in materials)
    if method in {"fusion_colossus", "fusion_titan"}:
        # 雷龍融合専用。戻せないトークンと裏側除外は不可。
        if any(m.token or m.zone not in {"field", "graveyard", "banished"}
               or (m.zone == "banished" and not m.face_up) for m in materials):
            return False
        if method == "fusion_colossus":
            return len(materials) == 2 and any(
                m.name == "サンダー・ドラゴン" and materials[1-i].race == "Thunder"
                for i, m in enumerate(materials))
        return len(materials) == 3 and all(m.thunder_dragon for m in materials)
    specs = {"striker": (1, 1), "summer": (2, 2), "sheep": (2, 2), "verte": (2, 2),
             "unicorn": (3, 2), "sword": (4, 3), "mech": (4, 2), "access": (4, 2), "ogre": (4, 2)}
    if method not in specs:
        return False
    rating, minimum = specs[method]
    if not minimum <= len(materials) <= rating or any(m.zone != "field" or not m.face_up for m in materials):
        return False
    if method in {"striker", "summer", "sheep", "verte"} and len(materials) != minimum:
        return False
    if method == "striker" and any(m.race != "Dragon" or m.level is None or m.level > 4 for m in materials):
        return False
    if method in {"summer", "mech"} and any(m.race != "Thunder" for m in materials):
        return False
    if method in {"sheep", "unicorn"} and len({m.name for m in materials}) != len(materials):
        return False
    if method in {"verte", "sword", "access"} and any(not m.effect or m.token for m in materials):
        return False
    if method == "ogre" and any(not m.gouki for m in materials):
        return False
    # リンクモンスターは1または自身のリンク数。2や3へ自由に分割しない。
    return any(sum(values) == rating for values in product(*[(1, m.link) if m.link else (1,) for m in materials]))
