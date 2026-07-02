"""
seed_demo.py  -  Popola il DB con dati dimostrativi realistici.
Esegui con:  python seed_demo.py

Rispetto alla versione precedente:
  - genera DUE stagioni (2023/24 e 2024/25) cosi' la "Carriera per stagione"
    nella pagina giocatore e il selettore di stagione hanno davvero
    qualcosa da mostrare;
  - simula 4 trasferimenti di giocatori tra una stagione e l'altra, per dare
    senso concreto alla relazione ternaria Rosa(giocatore, squadra, stagione);
  - crea un utente amministratore (password con hash) per provare le
    funzioni di inserimento/modifica/eliminazione del pannello "Gestione";
  - corregge un bug per cui Milan, Inter e Napoli finivano tutte con la
    IDENTICA rosa di nomi (la formula dell'indice non dipendeva davvero
    dalla squadra) e sostituisce un paio di nomi coincidenti con calciatori
    reali con nomi di fantasia.
"""
import sqlite3, os, random
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

random.seed(42)
DB = os.path.join(os.path.dirname(__file__), 'stats.db')

# helpers
def rnd(lo, hi): return random.randint(lo, hi)
def chance(p):   return random.random() < p

# dati statici
SQUADRE = [
    (1,'Juventus FC','Torino','Allianz Stadium',1897,'#1a1a2e'),
    (2,'AC Milan','Milano','San Siro',1899,'#ac0c2b'),
    (3,'FC Internazionale','Milano','San Siro',1908,'#0033a0'),
    (4,'SSC Napoli','Napoli','Diego A. Maradona',1926,'#1877c9'),
]

# 12 giocatori "base" (rosa Juventus): 1 P · 4 D · 4 C · 3 A
# Indice (slot) nella lista = ruolo fisso, riusato per generare le altre rose
ROSA_TEMPLATE = [
    ('Marco','Rossi','ITA','2001-03-14','Portiere','Destro',192,1),
    ('Luca','Ferrari','ITA','1995-07-22','Difensore','Destro',185,5),
    ('Andrea','Bianchi','ITA','1997-11-08','Difensore','Sinistro',181,6),
    ('Nicolás','García','ARG','1999-02-17','Difensore','Destro',179,3),
    ('Jonas','Becker','GER','1996-09-30','Difensore','Sinistro',184,4),
    ('Riccardo','Conti','ITA','1998-05-12','Centrocampista','Destro',178,8),
    ('Hamza','Diallo','SEN','2000-01-25','Centrocampista','Destro',183,10),
    ('Magnus','Holm','DEN','1994-08-03','Centrocampista','Sinistro',180,7),
    ('Lorenzo','Mancini','ITA','2002-04-19','Centrocampista','Destro',176,16),
    ('Carlos','Vidal','ESP','1997-12-01','Attaccante','Sinistro',177,14),
    ('Kwame','Asante','GHA','1999-06-11','Attaccante','Destro',180,9),
    ('Davide','Romano','ITA','2001-09-28','Attaccante','Sinistro',175,11),
]

# Nomi per le altre 3 squadre, UNA lista dedicata per squadra (stesso ordine
# di ruoli del template) cosi' da garantire 48 giocatori tutti diversi tra
# loro: niente piu' giocatori "fotocopia" su squadre diverse.
NOMI_VARIANTI = {
    2: [  # AC Milan
        ('Simone','Gallo'), ('Matteo','Esposito'), ('Giorgio','Pellegrini'),
        ('Mateo','Funes'), ('Karim','Diallo'), ('Sandro','Vitale'),
        ('Filip','Novak'), ('Aleksandr','Petrov'), ('Marcus','Silva'),
        ('Mario','Pena'), ('Hakan','Demir'), ('Sébastien','Morel'),
    ],
    3: [  # FC Internazionale
        ('Stefano','Greco'), ('Alessio','Moretti'), ('Davide','Caruso'),
        ('Joaquín','Medina'), ('Felix','Brandt'), ('Tommaso','Longo'),
        ('Ibrahima','Sow'), ('Anders','Friis'), ('Gabriele','Testa'),
        ('Diego','Soto'), ('Yaw','Mensah'), ('Nicola','Bruno'),
    ],
    4: [  # SSC Napoli
        ('Antonio','Fontana'), ('Salvatore','Marini'), ('Vincenzo','Leone'),
        ('Tomás','Acosta'), ('Niklas','Krüger'), ('Emanuele','Sartori'),
        ('Mamadou','Faye'), ('Christian','Bach'), ('Raffaele','Pace'),
        ('Adrián','Cano'), ('Kojo','Owusu'), ('Fabio','Lombardi'),
    ],
}

ARBITRI = ['D. Orsato','G. Irrati','M. Massa','F. Fabbri','L. Maresca']

# Trasferimenti tra stagione 1 e stagione 2: (slot, squadra_da, squadra_a).
# Scambiando due giocatori dello STESSO slot (= stesso ruolo, stesso numero
# di maglia "di template") nessuno dei due eredita un numero di maglia gia'
# occupato nella squadra di arrivo: il vincolo UNIQUE(id_squadra,id_stagione,
# numero_maglia) resta soddisfatto senza dover riassegnare le maglie.
TRASFERIMENTI_S2 = [
    (5, 1, 2),   # centrocampista: Juventus <-> Milan
    (9, 3, 4),   # attaccante:     Inter    <-> Napoli
]


# Round-robin doppio: ogni coppia si affronta 2 volte (andata/ritorno)
def genera_schedule(squadre_ids, stagione_id, start_date):
    fixtures = []
    pairs = [(a,b) for i,a in enumerate(squadre_ids)
                   for b in squadre_ids[i+1:]]
    for giornata, (a, b) in enumerate(pairs, start=1):
        fixtures.append((stagione_id, a, b, giornata,
                         start_date + timedelta(weeks=giornata-1)))
    for giornata, (a, b) in enumerate(pairs, start=len(pairs)+1):
        fixtures.append((stagione_id, b, a, giornata,
                         start_date + timedelta(weeks=giornata-1)))
    return fixtures


def genera_stat_giocatore(ruolo):
    """Genera statistiche realistiche in base al ruolo."""
    if ruolo == 'Portiere':
        return dict(minuti=90, gol=0, assist=0,
                    gialli=int(chance(0.05)), rossi=int(chance(0.01)),
                    tiri=0, tiri_in_porta=0,
                    passaggi=rnd(30,55), pass_ok=rnd(25,50),
                    drib=0, contr=rnd(0,2), inter=rnd(0,2),
                    xg=0.0)
    if ruolo == 'Difensore':
        g = 1 if chance(0.07) else 0
        return dict(minuti=rnd(70,90), gol=g, assist=int(chance(0.1)),
                    gialli=int(chance(0.18)), rossi=int(chance(0.03)),
                    tiri=rnd(0,2), tiri_in_porta=rnd(0,1),
                    passaggi=rnd(45,75), pass_ok=rnd(38,68),
                    drib=rnd(0,2), contr=rnd(1,5), inter=rnd(1,4),
                    xg=round(random.uniform(0,0.15),2))
    if ruolo == 'Centrocampista':
        g = 1 if chance(0.13) else 0
        return dict(minuti=rnd(65,90), gol=g, assist=int(chance(0.17)),
                    gialli=int(chance(0.15)), rossi=int(chance(0.02)),
                    tiri=rnd(1,4), tiri_in_porta=rnd(0,2),
                    passaggi=rnd(55,90), pass_ok=rnd(45,80),
                    drib=rnd(0,4), contr=rnd(1,5), inter=rnd(0,4),
                    xg=round(random.uniform(0,0.35),2))
    # Attaccante
    g = 1 if chance(0.28) else (2 if chance(0.05) else 0)
    return dict(minuti=rnd(60,90), gol=g, assist=int(chance(0.20)),
                gialli=int(chance(0.12)), rossi=int(chance(0.02)),
                tiri=rnd(2,6), tiri_in_porta=rnd(1,4),
                passaggi=rnd(20,50), pass_ok=rnd(15,42),
                drib=rnd(1,5), contr=rnd(0,2), inter=rnd(0,2),
                xg=round(random.uniform(0.1,0.9),2))


def genera_stagione(conn, sid, sq_ids, roster, start_date, pid_start):
    """Genera tutte le Partite e le Statistiche di UNA stagione.
    `roster` è {id_squadra: [(id_giocatore, ruolo, maglia, slot), ...]}.
    Ritorna il prossimo id_partita libero, cosi' le stagioni successive
    continuano la numerazione senza collisioni."""
    fixtures = genera_schedule(sq_ids, sid, start_date)
    pid = pid_start
    for (stagione_id, casa, ospite, giornata, data_p) in fixtures:
        gol_c = rnd(0, 3)
        gol_o = rnd(0, 3)
        spett = rnd(25_000, 75_000)
        arb   = random.choice(ARBITRI)
        conn.execute("""INSERT INTO Partita(id,data,giornata,gol_casa,gol_ospiti,
                        spettatori,arbitro,id_stagione,id_sq_casa,id_sq_ospite)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (pid, data_p.isoformat(), giornata, gol_c, gol_o,
                      spett, arb, stagione_id, casa, ospite))

        # Statistiche per gli 11 titolari di ciascuna squadra (il 12°
        # giocatore della rosa resta in panchina, semplificazione voluta)
        for sq_id in (casa, ospite):
            players = [(g, ruolo) for (g, ruolo, _maglia, _slot) in roster[sq_id][:11]]
            gol_rimasti = gol_c if sq_id == casa else gol_o
            stats_rows = []
            for p_gid, ruolo in players:
                st = genera_stat_giocatore(ruolo)
                st['gol'] = 0
                stats_rows.append((p_gid, ruolo, st))

            # I gol della partita vengono distribuiti con probabilita' diversa
            # per ruolo (attaccanti favoriti, portieri esclusi), non in modo
            # uniforme: si costruisce un pool "pesato" ripetendo l'indice di
            # ogni giocatore in proporzione al peso del suo ruolo.
            PESO_RUOLO = {'Attaccante': 6, 'Centrocampista': 2, 'Difensore': 1, 'Portiere': 0}
            pool = []
            for i, (_, ruolo, _) in enumerate(stats_rows):
                pool.extend([i] * PESO_RUOLO.get(ruolo, 0))
            random.shuffle(pool)
            for idx in pool:
                if gol_rimasti <= 0:
                    break
                stats_rows[idx][2]['gol'] = stats_rows[idx][2].get('gol', 0) + 1
                gol_rimasti -= 1

            for p_gid, ruolo, st in stats_rows:
                conn.execute("""INSERT OR IGNORE INTO Statistica(
                    id_giocatore, id_partita, minuti, gol, assist,
                    cartellini_gialli, cartellini_rossi,
                    tiri, tiri_in_porta, passaggi, passaggi_riusciti,
                    dribbling_riusciti, contrasti, intercetti, xG)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p_gid, pid,
                     st['minuti'], st['gol'], st['assist'],
                     st['gialli'], st['rossi'],
                     st['tiri'], min(st['tiri_in_porta'], st['tiri']),
                     st['passaggi'], min(st['pass_ok'], st['passaggi']),
                     st['drib'], st['contr'], st['inter'], st['xg']))
        pid += 1
    return pid


# main
def seed():
    if os.path.exists(DB):
        os.remove(DB)

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")

    # Schema
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path) as f:
        conn.executescript(f.read())

    # Stagioni
    conn.execute("INSERT INTO Stagione(id,anno_inizio,anno_fine,campionato) VALUES(1,2023,2024,'Serie A')")
    conn.execute("INSERT INTO Stagione(id,anno_inizio,anno_fine,campionato) VALUES(2,2024,2025,'Serie A')")

    # Squadre
    for sq in SQUADRE:
        conn.execute("INSERT INTO Squadra VALUES(?,?,?,?,?,?)", sq)

    # Giocatori (anagrafica unica, indipendente dalla stagione) + Rosa stagione 1
    gid = 1
    roster_s1 = {sq_id: [] for sq_id, *_ in SQUADRE}
    for sq_id, *_ in SQUADRE:
        for i, (nome, cognome, naz, dob, ruolo, piede, alt, maglia) in enumerate(ROSA_TEMPLATE):
            if sq_id in NOMI_VARIANTI:
                nome, cognome = NOMI_VARIANTI[sq_id][i]
            conn.execute("""INSERT INTO Giocatore(id,nome,cognome,nazionalita,
                            data_nascita,ruolo,piede_preferito,altezza_cm)
                            VALUES(?,?,?,?,?,?,?,?)""",
                         (gid, nome, cognome, naz, dob, ruolo, piede, alt))
            conn.execute("INSERT INTO Rosa VALUES(?,?,?,?)", (gid, sq_id, 1, maglia))
            roster_s1[sq_id].append((gid, ruolo, maglia, i))
            gid += 1

    # Rosa stagione 2: stessa rosa, applicando gli scambi di TRASFERIMENTI_S2
    roster_s2 = {sq_id: list(players) for sq_id, players in roster_s1.items()}
    for slot_idx, sq_da, sq_a in TRASFERIMENTI_S2:
        gA = next(p for p in roster_s2[sq_da] if p[3] == slot_idx)
        gB = next(p for p in roster_s2[sq_a]  if p[3] == slot_idx)
        roster_s2[sq_da] = [gB if p is gA else p for p in roster_s2[sq_da]]
        roster_s2[sq_a]  = [gA if p is gB else p for p in roster_s2[sq_a]]
    for sq_id, players in roster_s2.items():
        for (p_gid, ruolo, maglia, _slot) in players:
            conn.execute("INSERT INTO Rosa VALUES(?,?,?,?)", (p_gid, sq_id, 2, maglia))

    # Utente amministratore (credenziali demo, password con hash)
    conn.execute("INSERT INTO Utente(username,password_hash,ruolo) VALUES(?,?,?)",
                 ('admin', generate_password_hash('admin123'), 'admin'))

    conn.commit()

    # Partite + Statistiche, una stagione alla volta
    sq_ids = [sq[0] for sq in SQUADRE]
    pid = genera_stagione(conn, sid=1, sq_ids=sq_ids, roster=roster_s1,
                           start_date=date(2023, 9, 17), pid_start=1)
    genera_stagione(conn, sid=2, sq_ids=sq_ids, roster=roster_s2,
                     start_date=date(2024, 9, 15), pid_start=pid)

    conn.commit()
    conn.close()

    # Conteggi
    conn2 = sqlite3.connect(DB)
    rows = lambda q: conn2.execute(q).fetchone()[0]
    print(f"✓ DB creato: {DB}")
    print(f"  Stagioni:    {rows('SELECT COUNT(*) FROM Stagione')}")
    print(f"  Squadre:     {rows('SELECT COUNT(*) FROM Squadra')}")
    print(f"  Giocatori:   {rows('SELECT COUNT(*) FROM Giocatore')}")
    print(f"  Partite:     {rows('SELECT COUNT(*) FROM Partita')}")
    print(f"  Statistiche: {rows('SELECT COUNT(*) FROM Statistica')}")
    print(f"  Rosa:        {rows('SELECT COUNT(*) FROM Rosa')}")
    print(f"  Utenti:      {rows('SELECT COUNT(*) FROM Utente')}")
    print("  Login admin -> utente: admin   password: admin123")
    conn2.close()


if __name__ == '__main__':
    seed()
