
-- SPORTS STATS DB  |  schema.sql
--  Progetto Basi di Dati  –  Ingegneria delle Tecnologie Informatiche

PRAGMA foreign_keys = ON;

--  TABELLE

CREATE TABLE IF NOT EXISTS Stagione (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    anno_inizio  INTEGER NOT NULL,
    anno_fine    INTEGER NOT NULL,
    campionato   TEXT    NOT NULL DEFAULT 'Serie A',
    UNIQUE(anno_inizio, campionato),
    CHECK(anno_fine = anno_inizio + 1)
);

CREATE TABLE IF NOT EXISTS Squadra (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    citta           TEXT NOT NULL,
    stadio          TEXT,
    anno_fondazione INTEGER,
    colore_primario TEXT NOT NULL DEFAULT '#1a2e23'
);

CREATE TABLE IF NOT EXISTS Giocatore (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT NOT NULL,
    cognome         TEXT NOT NULL,
    nazionalita     TEXT,
    data_nascita    DATE,
    ruolo           TEXT NOT NULL
                    CHECK(ruolo IN ('Portiere','Difensore','Centrocampista','Attaccante')),
    piede_preferito TEXT DEFAULT 'Destro'
                    CHECK(piede_preferito IN ('Destro','Sinistro','Entrambi')),
    altezza_cm      INTEGER CHECK(altezza_cm BETWEEN 150 AND 220),
    ultima_modifica DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Partita (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    data         DATE    NOT NULL,
    giornata     INTEGER NOT NULL CHECK(giornata > 0),
    gol_casa     INTEGER NOT NULL DEFAULT 0 CHECK(gol_casa >= 0),
    gol_ospiti   INTEGER NOT NULL DEFAULT 0 CHECK(gol_ospiti >= 0),
    spettatori   INTEGER,
    arbitro      TEXT,
    id_stagione  INTEGER NOT NULL REFERENCES Stagione(id)  ON DELETE CASCADE,
    id_sq_casa   INTEGER NOT NULL REFERENCES Squadra(id),
    id_sq_ospite INTEGER NOT NULL REFERENCES Squadra(id),
    CHECK(id_sq_casa != id_sq_ospite)
);

-- Relazione ternaria: un giocatore appartiene a una sola squadra per stagione
CREATE TABLE IF NOT EXISTS Rosa (
    id_giocatore  INTEGER NOT NULL REFERENCES Giocatore(id) ON DELETE CASCADE,
    id_squadra    INTEGER NOT NULL REFERENCES Squadra(id)   ON DELETE CASCADE,
    id_stagione   INTEGER NOT NULL REFERENCES Stagione(id)  ON DELETE CASCADE,
    numero_maglia INTEGER CHECK(numero_maglia BETWEEN 1 AND 99),
    PRIMARY KEY(id_giocatore, id_stagione),
    -- Due giocatori della stessa squadra, nella stessa stagione, non possono
    -- indossare lo stesso numero di maglia
    UNIQUE(id_squadra, id_stagione, numero_maglia)
);

CREATE TABLE IF NOT EXISTS Statistica (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    id_giocatore       INTEGER NOT NULL REFERENCES Giocatore(id) ON DELETE CASCADE,
    id_partita         INTEGER NOT NULL REFERENCES Partita(id)   ON DELETE CASCADE,
    minuti             INTEGER DEFAULT 0   CHECK(minuti BETWEEN 0 AND 120),
    gol                INTEGER DEFAULT 0   CHECK(gol >= 0),
    assist             INTEGER DEFAULT 0   CHECK(assist >= 0),
    cartellini_gialli  INTEGER DEFAULT 0   CHECK(cartellini_gialli IN (0,1)),
    cartellini_rossi   INTEGER DEFAULT 0   CHECK(cartellini_rossi  IN (0,1)),
    tiri               INTEGER DEFAULT 0   CHECK(tiri >= 0),
    tiri_in_porta      INTEGER DEFAULT 0,
    passaggi           INTEGER DEFAULT 0,
    passaggi_riusciti  INTEGER DEFAULT 0,
    dribbling_riusciti INTEGER DEFAULT 0,
    contrasti          INTEGER DEFAULT 0,
    intercetti         INTEGER DEFAULT 0,
    xG                 REAL    DEFAULT 0.0,
    UNIQUE(id_giocatore, id_partita),
    CHECK(tiri_in_porta      <= tiri),
    CHECK(passaggi_riusciti  <= passaggi)
);

-- Utenti amministratori abilitati a inserire/modificare/eliminare dati
-- (entità "di sistema", non fa parte del dominio sportivo)
CREATE TABLE IF NOT EXISTS Utente (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    ruolo           TEXT NOT NULL DEFAULT 'admin' CHECK(ruolo IN ('admin','editor')),
    creato_il       DATETIME DEFAULT CURRENT_TIMESTAMP
);

--  INDICI

CREATE INDEX IF NOT EXISTS idx_stat_giocatore ON Statistica(id_giocatore);
CREATE INDEX IF NOT EXISTS idx_stat_partita   ON Statistica(id_partita);
CREATE INDEX IF NOT EXISTS idx_partita_stage  ON Partita(id_stagione);
CREATE INDEX IF NOT EXISTS idx_partita_casa   ON Partita(id_sq_casa);
CREATE INDEX IF NOT EXISTS idx_partita_ospite ON Partita(id_sq_ospite);
CREATE INDEX IF NOT EXISTS idx_rosa_sq_stage  ON Rosa(id_squadra, id_stagione);

--  VISTA
--  Calcola punti/GF/GS separando i contributi casa e ospite
CREATE VIEW IF NOT EXISTS v_classifica AS
WITH ris_casa AS (
    SELECT sq.id, sq.nome, sq.colore_primario, p.id_stagione,
           1 AS pg,
           CASE WHEN p.gol_casa > p.gol_ospiti THEN 3
                WHEN p.gol_casa = p.gol_ospiti THEN 1
                ELSE 0 END                              AS punti,
           (p.gol_casa > p.gol_ospiti)                 AS v,
           (p.gol_casa = p.gol_ospiti)                 AS n,
           (p.gol_casa < p.gol_ospiti)                 AS s,
           p.gol_casa AS gf, p.gol_ospiti AS gs
    FROM Squadra sq JOIN Partita p ON sq.id = p.id_sq_casa
),
ris_ospite AS (
    SELECT sq.id, sq.nome, sq.colore_primario, p.id_stagione,
           1 AS pg,
           CASE WHEN p.gol_ospiti > p.gol_casa THEN 3
                WHEN p.gol_casa  = p.gol_ospiti THEN 1
                ELSE 0 END                              AS punti,
           (p.gol_ospiti > p.gol_casa)                 AS v,
           (p.gol_casa   = p.gol_ospiti)               AS n,
           (p.gol_ospiti < p.gol_casa)                 AS s,
           p.gol_ospiti AS gf, p.gol_casa AS gs
    FROM Squadra sq JOIN Partita p ON sq.id = p.id_sq_ospite
)
SELECT id, nome, colore_primario, id_stagione,
       SUM(pg)    AS pg,
       SUM(punti) AS punti,
       SUM(v) AS v, SUM(n) AS n, SUM(s) AS s,
       SUM(gf) AS gf, SUM(gs) AS gs,
       SUM(gf) - SUM(gs) AS diff
FROM (SELECT * FROM ris_casa UNION ALL SELECT * FROM ris_ospite)
GROUP BY id, id_stagione;

--  TRIGGER

-- Un CHECK non può confrontare colonne di tabelle diverse: per garantire che
-- una Statistica venga inserita solo per un giocatore effettivamente
-- tesserato (Rosa) con una delle due squadre che disputano quella partita,
-- nella stagione corretta, serve un trigger.
CREATE TRIGGER IF NOT EXISTS trg_statistica_rosa_check
BEFORE INSERT ON Statistica
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM Partita p
    JOIN Rosa r ON r.id_giocatore = NEW.id_giocatore
               AND r.id_stagione  = p.id_stagione
               AND r.id_squadra  IN (p.id_sq_casa, p.id_sq_ospite)
    WHERE p.id = NEW.id_partita
)
BEGIN
    SELECT RAISE(ABORT, 'giocatore non tesserato con questa partita');
END;

-- Aggiorna automaticamente il timestamp di ultima modifica quando un
-- amministratore modifica l'anagrafica di un giocatore dal pannello di
-- gestione. Non innesca un ciclo infinito perché in SQLite
-- PRAGMA recursive_triggers è disattivato di default: l'UPDATE eseguito
-- dal trigger stesso non ri-attiva il trigger.
CREATE TRIGGER IF NOT EXISTS trg_giocatore_timestamp
AFTER UPDATE ON Giocatore
FOR EACH ROW
BEGIN
    UPDATE Giocatore SET ultima_modifica = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
