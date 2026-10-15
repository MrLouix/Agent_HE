"""Journal d'audit : une entrée par réponse (sources, mode, contrôles déclenchés)."""

import sqlite3

from agent_he.models import EntreeAudit

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY,
    horodatage TEXT NOT NULL,
    mode TEXT NOT NULL,
    contenu TEXT NOT NULL
);
"""


class JournalAudit:
    def __init__(self, connexion: sqlite3.Connection) -> None:
        self._db = connexion
        self._db.executescript(SCHEMA)

    def enregistrer(self, entree: EntreeAudit) -> None:
        self._db.execute(
            "INSERT INTO audit (id, horodatage, mode, contenu) VALUES (?, ?, ?, ?)",
            (str(entree.id), entree.horodatage.isoformat(), entree.mode, entree.model_dump_json()),
        )
        self._db.commit()

    def lister(self, limite: int = 50) -> list[EntreeAudit]:
        lignes = self._db.execute(
            "SELECT contenu FROM audit ORDER BY horodatage DESC LIMIT ?", (limite,)
        ).fetchall()
        return [EntreeAudit.model_validate_json(ligne["contenu"]) for ligne in lignes]
