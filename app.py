"""
app.py  –  Sports Stats Dashboard
Flask + SQLite  |  Progetto Basi di Dati

Struttura del file:
  1. Helper di connessione al DB (lettura / scrittura)
  2. Autenticazione area amministrazione
  3. Sito pubblico (pagine di sola lettura)
  4. API JSON (riusabili da un client esterno: mobile / SPA / ecc.)
  5. Area amministrazione autenticata (CRUD)
"""
import os, sqlite3, json
from functools import wraps
from flask import (Flask, render_template, request, jsonify, abort,
                    redirect, url_for, session, flash)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# In produzione andrebbe letta da variabile d'ambiente; per il progetto
# didattico un valore fisso e' sufficiente e mantiene le sessioni valide
# anche se il server Flask viene riavviato durante la demo.
app.secret_key = 'db2026-progetto-sports-stats-CAMBIAMI-IN-PRODUZIONE'
DB = os.path.join(os.path.dirname(__file__), 'stats.db')


# ============================================================
#  1. HELPER DI CONNESSIONE AL DB
# ============================================================
def query(sql, params=(), one=False):
    """Esegue una SELECT in una connessione dedicata (sola lettura)."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cur = conn.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


def esegui(sql, params=()):
    """Esegue una singola INSERT/UPDATE/DELETE e fa commit.
    Se lo statement solleva un'eccezione (vincolo CHECK/UNIQUE/FK o
    trigger che chiama RAISE(ABORT,...)), commit() non viene mai
    raggiunto: chiudendo la connessione nel blocco finally, SQLite
    annulla automaticamente la transazione rimasta aperta, quindi qui
    non serve un rollback() esplicito. Lo facciamo invece esplicitamente
    in crea_giocatore_con_rosa() qui sotto, dove l'atomicita' fra DUE
    istruzioni e' proprio il punto da dimostrare."""
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def crea_giocatore_con_rosa(dati_giocatore, id_squadra, id_stagione, numero_maglia):
    """INSERT su Giocatore + INSERT su Rosa nella STESSA transazione.

    Perche' serve una transazione esplicita: se inserissimo il Giocatore
    e poi, in una chiamata separata, la riga Rosa, un fallimento della
    seconda INSERT (es. numero di maglia gia' occupato in quella
    squadra/stagione, vincolo UNIQUE su Rosa) lascerebbe nel database un
    giocatore creato ma senza squadra: un'anomalia. Aprendo entrambe le
    INSERT sulla stessa connessione e chiamando commit() solo se
    ENTRAMBE riescono (altrimenti rollback()), garantiamo atomicita':
    o il giocatore viene creato E tesserato, o non viene creato affatto.
    """
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cur = conn.execute("""INSERT INTO Giocatore
            (nome,cognome,nazionalita,data_nascita,ruolo,piede_preferito,altezza_cm)
            VALUES (?,?,?,?,?,?,?)""", dati_giocatore)
        nuovo_id = cur.lastrowid
        conn.execute("""INSERT INTO Rosa(id_giocatore,id_squadra,id_stagione,numero_maglia)
                        VALUES (?,?,?,?)""",
                     (nuovo_id, id_squadra, id_stagione, numero_maglia))
        conn.commit()
        return nuovo_id, None
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return None, messaggio_errore_db(e)
    finally:
        conn.close()


def messaggio_errore_db(e):
    """Traduce le eccezioni sollevate da SQLite (vincoli CHECK/UNIQUE/
    FOREIGN KEY, trigger) in messaggi comprensibili da mostrare
    all'amministratore, invece del testo tecnico grezzo."""
    msg = str(e)
    mappa = [
        ('Rosa.id_squadra, Rosa.id_stagione, Rosa.numero_maglia',
         'Numero di maglia già assegnato a un altro giocatore in questa squadra e stagione.'),
        ('Utente.username', 'Username già in uso.'),
        ('altezza_cm BETWEEN', 'Altezza non valida: deve essere tra 150 e 220 cm.'),
        ('numero_maglia BETWEEN', 'Numero di maglia non valido: deve essere tra 1 e 99.'),
        ('minuti BETWEEN', 'I minuti giocati devono essere tra 0 e 120.'),
        ('tiri_in_porta', 'I tiri in porta non possono superare i tiri totali.'),
        ('passaggi_riusciti', 'I passaggi riusciti non possono superare i passaggi totali.'),
        ('id_sq_casa != id_sq_ospite', 'Una squadra non può giocare contro se stessa.'),
        ('tesserato', msg),   # messaggio del trigger trg_statistica_rosa_check, gia' in italiano
        ('FOREIGN KEY constraint failed',
         'Operazione non consentita: esistono ancora dati collegati (es. partite già giocate).'),
    ]
    for chiave, testo in mappa:
        if chiave in msg:
            return testo
    return f'Errore nel salvataggio dei dati: {msg}'


# ============================================================
#  2. AUTENTICAZIONE AREA AMMINISTRAZIONE
# ============================================================
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Devi accedere per gestire i dati.', 'error')
            return redirect(url_for('admin_login'))
        return view(*args, **kwargs)
    return wrapped


# ============================================================
#  CONTEXT PROCESSOR  →  stagioni sempre disponibili nei template
# ============================================================
@app.context_processor
def inject_globals():
    stagioni = query("SELECT * FROM Stagione ORDER BY anno_inizio DESC")
    return dict(all_stagioni=stagioni)

def stagione_default(sid=None):
    if sid:
        s = query("SELECT * FROM Stagione WHERE id = ?", (sid,), one=True)
        if s: return s
    return query("SELECT * FROM Stagione ORDER BY anno_inizio DESC LIMIT 1", one=True)


# ============================================================
#  3. SITO PUBBLICO
# ============================================================

#  HOME  –  classifica + ultime partite
@app.route('/')
def index():
    st = stagione_default(request.args.get('stagione', type=int))

    # Vista v_classifica (CTE nel DDL)
    classifica = query("""
        SELECT * FROM v_classifica
        WHERE id_stagione = ?
        ORDER BY punti DESC, diff DESC, gf DESC
    """, (st['id'],))

    ultime = query("""
        SELECT p.id, p.data, p.giornata, p.gol_casa, p.gol_ospiti,
               sc.id AS id_casa,   sc.nome AS sq_casa,
               sp.id AS id_ospite, sp.nome AS sq_ospite
        FROM Partita p
        JOIN Squadra sc ON p.id_sq_casa   = sc.id
        JOIN Squadra sp ON p.id_sq_ospite = sp.id
        WHERE p.id_stagione = ?
        ORDER BY p.data DESC, p.id DESC
        LIMIT 8
    """, (st['id'],))

    n_partite = query("SELECT COUNT(*) AS n FROM Partita WHERE id_stagione=?",
                      (st['id'],), one=True)['n']
    n_gol = query("""SELECT SUM(gol_casa+gol_ospiti) AS n
                     FROM Partita WHERE id_stagione=?""",
                  (st['id'],), one=True)['n'] or 0

    return render_template('index.html',
        stagione=st, classifica=classifica, ultime=ultime,
        n_partite=n_partite, n_gol=n_gol)


#  MARCATORI  –  CTE + RANK() window function
@app.route('/marcatori')
def marcatori():
    st = stagione_default(request.args.get('stagione', type=int))

    # CTE + finestra RANK per classifica marcatori
    top_gol = query("""
        WITH agg AS (
            SELECT
                g.id, g.nome, g.cognome, g.ruolo,
                sq.nome AS squadra, sq.colore_primario, sq.id AS id_sq,
                SUM(s.gol)                AS gol,
                SUM(s.assist)             AS assist,
                ROUND(SUM(s.xG), 2)       AS xg,
                COUNT(DISTINCT s.id_partita) AS presenze,
                SUM(s.tiri)               AS tiri,
                SUM(s.tiri_in_porta)      AS tiri_porta,
                ROUND(SUM(s.gol)*1.0 /
                    NULLIF(COUNT(DISTINCT s.id_partita),0), 2) AS media_gol
            FROM Statistica s
            JOIN Giocatore g ON s.id_giocatore = g.id
            JOIN Partita   p ON s.id_partita   = p.id
            JOIN Rosa      r ON r.id_giocatore = g.id
                             AND r.id_stagione = p.id_stagione
            JOIN Squadra  sq ON r.id_squadra   = sq.id
            WHERE p.id_stagione = ?
            GROUP BY g.id
        )
        SELECT *, RANK() OVER (ORDER BY gol DESC, assist DESC, xg DESC) AS pos
        FROM agg WHERE gol > 0
        ORDER BY pos, xg DESC
        LIMIT 25
    """, (st['id'],))

    # Top assist (include chi non ha gol)
    top_assist = query("""
        SELECT g.id, g.nome, g.cognome, sq.nome AS squadra, sq.colore_primario,
               SUM(s.assist) AS assist, SUM(s.gol) AS gol,
               COUNT(DISTINCT s.id_partita) AS presenze
        FROM Statistica s
        JOIN Giocatore g ON s.id_giocatore = g.id
        JOIN Partita   p ON s.id_partita   = p.id
        JOIN Rosa      r ON r.id_giocatore = g.id
                         AND r.id_stagione = p.id_stagione
        JOIN Squadra  sq ON r.id_squadra   = sq.id
        WHERE p.id_stagione = ?
        GROUP BY g.id HAVING assist > 0
        ORDER BY assist DESC, gol DESC
        LIMIT 10
    """, (st['id'],))

    # Giocatori che hanno partecipato ad ALMENO una partita ma NON hanno
    # ancora segnato né fatto assist (doppio NOT EXISTS)
    senza_contributo = query("""
        SELECT g.nome, g.cognome, g.ruolo, sq.nome AS squadra,
               COUNT(DISTINCT s.id_partita) AS presenze
        FROM Giocatore g
        JOIN Rosa r ON r.id_giocatore = g.id AND r.id_stagione = ?
        JOIN Squadra sq ON r.id_squadra = sq.id
        JOIN Statistica s ON s.id_giocatore = g.id
        WHERE NOT EXISTS (
            SELECT 1 FROM Statistica s2
            WHERE s2.id_giocatore = g.id AND s2.gol > 0
              AND s2.id_partita IN (SELECT id FROM Partita WHERE id_stagione = ?)
        )
        AND NOT EXISTS (
            SELECT 1 FROM Statistica s3
            WHERE s3.id_giocatore = g.id AND s3.assist > 0
              AND s3.id_partita IN (SELECT id FROM Partita WHERE id_stagione = ?)
        )
        GROUP BY g.id HAVING presenze >= 3
        ORDER BY presenze DESC
        LIMIT 5
    """, (st['id'], st['id'], st['id']))

    return render_template('marcatori.html',
        stagione=st, top_gol=top_gol,
        top_assist=top_assist, senza_contributo=senza_contributo)


#  SQUADRA
@app.route('/squadra/<int:sid>')
def squadra(sid):
    sq = query("SELECT * FROM Squadra WHERE id = ?", (sid,), one=True)
    if not sq: abort(404)
    st = stagione_default(request.args.get('stagione', type=int))

    # Rosa con statistiche aggregate (LEFT JOIN per includere chi non ha giocato)
    rosa = query("""
        SELECT g.id, g.nome, g.cognome, g.ruolo, g.nazionalita,
               g.piede_preferito, g.altezza_cm, r.numero_maglia,
               COALESCE(agg.presenze, 0)  AS presenze,
               COALESCE(agg.gol, 0)       AS gol,
               COALESCE(agg.assist, 0)    AS assist,
               COALESCE(agg.gialli, 0)    AS gialli,
               COALESCE(agg.rossi, 0)     AS rossi,
               COALESCE(agg.min_medi, 0)  AS min_medi
        FROM Rosa r
        JOIN Giocatore g ON r.id_giocatore = g.id
        LEFT JOIN (
            SELECT s.id_giocatore,
                   COUNT(DISTINCT s.id_partita) AS presenze,
                   SUM(s.gol)    AS gol,
                   SUM(s.assist) AS assist,
                   SUM(s.cartellini_gialli) AS gialli,
                   SUM(s.cartellini_rossi)  AS rossi,
                   ROUND(AVG(s.minuti), 0)  AS min_medi
            FROM Statistica s
            WHERE s.id_partita IN (
                SELECT id FROM Partita
                WHERE id_stagione = ?
                  AND (id_sq_casa = ? OR id_sq_ospite = ?)
            )
            GROUP BY s.id_giocatore
        ) agg ON agg.id_giocatore = g.id
        WHERE r.id_squadra = ? AND r.id_stagione = ?
        ORDER BY
            CASE g.ruolo WHEN 'Portiere' THEN 1 WHEN 'Difensore' THEN 2
                         WHEN 'Centrocampista' THEN 3 ELSE 4 END,
            gol DESC, g.cognome
    """, (st['id'], sid, sid, sid, st['id']))

    partite = query("""
        SELECT p.id, p.data, p.giornata, p.gol_casa, p.gol_ospiti,
               sc.id AS id_casa,   sc.nome AS sq_casa,
               sp.id AS id_ospite, sp.nome AS sq_ospite
        FROM Partita p
        JOIN Squadra sc ON p.id_sq_casa   = sc.id
        JOIN Squadra sp ON p.id_sq_ospite = sp.id
        WHERE p.id_stagione = ?
          AND (p.id_sq_casa = ? OR p.id_sq_ospite = ?)
        ORDER BY p.data DESC
    """, (st['id'], sid, sid))

    # Forma recente
    forma = []
    for pt in partite[:5]:
        gc, go = pt['gol_casa'], pt['gol_ospiti']
        if pt['id_casa'] == sid:
            forma.append('V' if gc>go else 'P' if gc<go else 'N')
        else:
            forma.append('V' if go>gc else 'P' if go<gc else 'N')

    stats_sq = query("""
        SELECT * FROM v_classifica WHERE id = ? AND id_stagione = ?
    """, (sid, st['id']), one=True)

    return render_template('squadra.html',
        sq=sq, rosa=rosa, partite=partite, forma=forma,
        stats_sq=stats_sq, stagione=st)


#  GIOCATORE  –  profilo + history + chart
@app.route('/giocatore/<int:gid>')
def giocatore(gid):
    g = query("SELECT * FROM Giocatore WHERE id = ?", (gid,), one=True)
    if not g: abort(404)

    # Storia per stagione con aggregati
    storia = query("""
        SELECT
            printf('%d/%02d', st.anno_inizio, st.anno_fine % 100) AS label,
            st.id AS id_stagione,
            sq.id AS id_sq, sq.nome AS squadra, sq.colore_primario,
            r.numero_maglia,
            COALESCE(COUNT(DISTINCT s.id_partita), 0)   AS presenze,
            COALESCE(SUM(s.gol), 0)                     AS gol,
            COALESCE(SUM(s.assist), 0)                  AS assist,
            COALESCE(ROUND(SUM(s.xG),2), 0.0)           AS xg,
            COALESCE(SUM(s.tiri), 0)                    AS tiri,
            COALESCE(SUM(s.tiri_in_porta), 0)           AS tiri_porta,
            COALESCE(SUM(s.cartellini_gialli), 0)       AS gialli,
            COALESCE(SUM(s.cartellini_rossi), 0)        AS rossi,
            COALESCE(ROUND(AVG(s.minuti), 0), 0)        AS min_medi,
            COALESCE(ROUND(AVG(s.passaggi_riusciti*1.0 /
                NULLIF(s.passaggi,0)*100), 1), 0)       AS acc_pass
        FROM Rosa r
        JOIN Stagione st ON r.id_stagione = st.id
        JOIN Squadra  sq ON r.id_squadra  = sq.id
        LEFT JOIN Statistica s ON s.id_giocatore = r.id_giocatore
            AND s.id_partita IN (SELECT id FROM Partita WHERE id_stagione = st.id)
        WHERE r.id_giocatore = ?
        GROUP BY st.id, sq.id
        ORDER BY st.anno_inizio DESC
    """, (gid,))

    ultime = query("""
        SELECT p.id, p.data,
               sc.nome AS sq_casa,   sc.id AS id_casa,
               sp.nome AS sq_ospite, sp.id AS id_ospite,
               p.gol_casa, p.gol_ospiti,
               sq_g.nome AS sq_giocatore,
               s.minuti, s.gol, s.assist,
               s.cartellini_gialli, s.cartellini_rossi,
               s.tiri, s.xG
        FROM Statistica s
        JOIN Partita   p   ON s.id_partita   = p.id
        JOIN Squadra   sc  ON p.id_sq_casa   = sc.id
        JOIN Squadra   sp  ON p.id_sq_ospite = sp.id
        JOIN Rosa      r   ON r.id_giocatore = s.id_giocatore
                          AND r.id_stagione  = p.id_stagione
        JOIN Squadra  sq_g ON r.id_squadra   = sq_g.id
        WHERE s.id_giocatore = ?
        ORDER BY p.data DESC LIMIT 10
    """, (gid,))

    # Squadra corrente (ultima stagione)
    sq_corrente = query("""
        SELECT sq.nome, sq.colore_primario, r.numero_maglia
        FROM Rosa r JOIN Squadra sq ON r.id_squadra = sq.id
        WHERE r.id_giocatore = ?
        ORDER BY r.id_stagione DESC LIMIT 1
    """, (gid,), one=True)

    # Dati per Chart.js (JSON serializzato)
    chart_labels  = [r['label']   for r in storia][::-1]
    chart_gol     = [r['gol']     for r in storia][::-1]
    chart_assist  = [r['assist']  for r in storia][::-1]

    return render_template('giocatore.html',
        g=g, storia=storia, ultime=ultime, sq_corrente=sq_corrente,
        chart_labels=json.dumps(chart_labels),
        chart_gol=json.dumps(chart_gol),
        chart_assist=json.dumps(chart_assist))


#  PARTITA  –  box score dettagliato
@app.route('/partita/<int:pid>')
def partita(pid):
    pt = query("""
        SELECT p.*,
               sc.id AS id_casa,   sc.nome AS sq_casa,
               sc.colore_primario AS col_casa, sc.stadio,
               sp.id AS id_ospite, sp.nome AS sq_ospite,
               sp.colore_primario AS col_ospite,
               printf('%d/%02d', st.anno_inizio, st.anno_fine%100) AS stage_label
        FROM Partita p
        JOIN Squadra  sc ON p.id_sq_casa   = sc.id
        JOIN Squadra  sp ON p.id_sq_ospite = sp.id
        JOIN Stagione st ON p.id_stagione  = st.id
        WHERE p.id = ?
    """, (pid,), one=True)
    if not pt: abort(404)

    def box_score(sq_id):
        return query("""
            SELECT g.id, g.nome, g.cognome, g.ruolo,
                   s.minuti, s.gol, s.assist,
                   s.cartellini_gialli, s.cartellini_rossi,
                   s.tiri, s.tiri_in_porta,
                   s.passaggi, s.passaggi_riusciti,
                   s.dribbling_riusciti, s.contrasti, s.intercetti,
                   ROUND(s.xG, 2) AS xG
            FROM Statistica s
            JOIN Giocatore g ON s.id_giocatore = g.id
            JOIN Rosa r ON r.id_giocatore = g.id
                       AND r.id_squadra   = ?
                       AND r.id_stagione  = ?
            WHERE s.id_partita = ?
            ORDER BY
                CASE g.ruolo WHEN 'Portiere' THEN 1 WHEN 'Difensore' THEN 2
                             WHEN 'Centrocampista' THEN 3 ELSE 4 END,
                s.minuti DESC
        """, (sq_id, pt['id_stagione'], pid))

    stat_casa   = box_score(pt['id_casa'])
    stat_ospite = box_score(pt['id_ospite'])

    # Totali per squadra
    def totali(rows):
        keys = ['gol','assist','tiri','tiri_in_porta',
                'passaggi','passaggi_riusciti','contrasti','intercetti']
        t = {k: sum(r[k] or 0 for r in rows) for k in keys}
        t['xG'] = round(sum(r['xG'] or 0 for r in rows), 2)
        return t

    return render_template('partita.html',
        pt=pt,
        stat_casa=stat_casa, tot_casa=totali(stat_casa),
        stat_ospite=stat_ospite, tot_ospite=totali(stat_ospite))


#  CONFRONTO  –  head-to-head storico
@app.route('/confronto')
def confronto():
    sq1_id = request.args.get('sq1', type=int)
    sq2_id = request.args.get('sq2', type=int)

    tutte = query("SELECT id, nome, colore_primario FROM Squadra ORDER BY nome")
    sq1 = sq2 = risultati = h2h = None

    if sq1_id and sq2_id and sq1_id != sq2_id:
        sq1 = query("SELECT * FROM Squadra WHERE id=?", (sq1_id,), one=True)
        sq2 = query("SELECT * FROM Squadra WHERE id=?", (sq2_id,), one=True)

        risultati = query("""
            SELECT p.id, p.data, p.giornata,
                   sc.nome AS sq_casa, sc.id AS id_casa,
                   sp.nome AS sq_ospite, sp.id AS id_ospite,
                   p.gol_casa, p.gol_ospiti,
                   printf('%d/%02d', st.anno_inizio, st.anno_fine%100) AS stagione
            FROM Partita p
            JOIN Squadra  sc ON p.id_sq_casa   = sc.id
            JOIN Squadra  sp ON p.id_sq_ospite = sp.id
            JOIN Stagione st ON p.id_stagione  = st.id
            WHERE (p.id_sq_casa=? AND p.id_sq_ospite=?)
               OR (p.id_sq_casa=? AND p.id_sq_ospite=?)
            ORDER BY p.data DESC
        """, (sq1_id, sq2_id, sq2_id, sq1_id))

        # Riepilogo H2H
        h2h = query("""
            SELECT COUNT(*) AS totale,
                SUM(CASE
                    WHEN (p.id_sq_casa=?   AND p.gol_casa>p.gol_ospiti)
                      OR (p.id_sq_ospite=? AND p.gol_ospiti>p.gol_casa)
                    THEN 1 ELSE 0 END) AS v1,
                SUM(CASE
                    WHEN (p.id_sq_casa=?   AND p.gol_casa>p.gol_ospiti)
                      OR (p.id_sq_ospite=? AND p.gol_ospiti>p.gol_casa)
                    THEN 1 ELSE 0 END) AS v2,
                SUM(CASE WHEN p.gol_casa=p.gol_ospiti THEN 1 ELSE 0 END) AS pareggi,
                SUM(CASE WHEN p.id_sq_casa=? THEN p.gol_casa
                         ELSE p.gol_ospiti END)  AS gf1,
                SUM(CASE WHEN p.id_sq_casa=? THEN p.gol_ospiti
                         ELSE p.gol_casa END)    AS gf2
            FROM Partita p
            WHERE (p.id_sq_casa=? AND p.id_sq_ospite=?)
               OR (p.id_sq_casa=? AND p.id_sq_ospite=?)
        """, (sq1_id,sq1_id, sq2_id,sq2_id,
              sq1_id,sq1_id,
              sq1_id,sq2_id, sq2_id,sq1_id), one=True)

    return render_template('confronto.html',
        tutte=tutte, sq1=sq1, sq2=sq2,
        risultati=risultati, h2h=h2h,
        sq1_id=sq1_id, sq2_id=sq2_id)


#  CERCA  –  ricerca full-text su giocatori e squadre
@app.route('/cerca')
def cerca():
    q = request.args.get('q', '').strip()
    giocatori = squadre = []
    if q:
        like = f'%{q}%'
        giocatori = query("""
            SELECT g.id, g.nome, g.cognome, g.ruolo, g.nazionalita,
                   sq.nome AS squadra
            FROM Giocatore g
            LEFT JOIN Rosa r ON r.id_giocatore = g.id
            LEFT JOIN Squadra sq ON r.id_squadra = sq.id
            WHERE (g.nome LIKE ? OR g.cognome LIKE ?)
            GROUP BY g.id ORDER BY g.cognome LIMIT 12
        """, (like, like))
        squadre = query("""
            SELECT id, nome, citta, stadio, anno_fondazione, colore_primario
            FROM Squadra WHERE nome LIKE ? OR citta LIKE ?
            ORDER BY nome LIMIT 6
        """, (like, like))
    return render_template('cerca.html', q=q,
                           giocatori=giocatori, squadre=squadre)


# ============================================================
#  4. API JSON  –  utilizzabili anche da un client esterno alla
#     webapp (app mobile, script, dashboard di terzi): e' questa la
#     parte che rende il database "interrogabile... da un'applicazione
#     mobile o distribuita" oltre che dalle pagine HTML.
# ============================================================
@app.route('/api/giocatore/<int:gid>/radar')
def api_radar(gid):
    """Profilo statistico normalizzato 0-100 per il radar chart.
    Ogni metrica viene scalata rispetto al MASSIMO di quella metrica fra
    tutti i giocatori che hanno giocato almeno una partita nella stessa
    stagione (CTE 'massimi'), cosi' valori espressi in unita' diverse
    (tiri a partita, % passaggi riusciti, gol a presenza, ...) diventano
    comparabili sullo stesso asse 0-100."""
    sid = request.args.get('stagione', type=int)
    st = stagione_default(sid)
    r = query("""
        WITH giocatore_stats AS (
            SELECT AVG(s.tiri) AS tiri_m,
                   AVG(s.passaggi_riusciti*100.0/NULLIF(s.passaggi,0)) AS acc_pass,
                   AVG(s.dribbling_riusciti) AS drib_m,
                   AVG(s.contrasti) AS contr_m,
                   AVG(s.intercetti) AS inter_m,
                   SUM(s.gol)*1.0/NULLIF(COUNT(*),0) AS gol_m
            FROM Statistica s JOIN Partita p ON s.id_partita = p.id
            WHERE s.id_giocatore = ? AND p.id_stagione = ?
        ),
        massimi AS (
            SELECT MAX(m_tiri) AS max_tiri, MAX(m_acc) AS max_acc, MAX(m_drib) AS max_drib,
                   MAX(m_contr) AS max_contr, MAX(m_inter) AS max_inter, MAX(m_gol) AS max_gol
            FROM (
                SELECT AVG(s.tiri) AS m_tiri,
                       AVG(s.passaggi_riusciti*100.0/NULLIF(s.passaggi,0)) AS m_acc,
                       AVG(s.dribbling_riusciti) AS m_drib,
                       AVG(s.contrasti) AS m_contr,
                       AVG(s.intercetti) AS m_inter,
                       SUM(s.gol)*1.0/NULLIF(COUNT(*),0) AS m_gol
                FROM Statistica s JOIN Partita p ON s.id_partita = p.id
                WHERE p.id_stagione = ?
                GROUP BY s.id_giocatore
            )
        )
        SELECT
            ROUND(gs.tiri_m   * 100.0 / NULLIF(mx.max_tiri,0),  1) AS tiri,
            ROUND(gs.acc_pass * 100.0 / NULLIF(mx.max_acc,0),   1) AS accuratezza_passaggi,
            ROUND(gs.drib_m   * 100.0 / NULLIF(mx.max_drib,0),  1) AS dribbling,
            ROUND(gs.contr_m  * 100.0 / NULLIF(mx.max_contr,0), 1) AS contrasti,
            ROUND(gs.inter_m  * 100.0 / NULLIF(mx.max_inter,0), 1) AS intercetti,
            ROUND(gs.gol_m    * 100.0 / NULLIF(mx.max_gol,0),   1) AS gol_per_presenza
        FROM giocatore_stats gs, massimi mx
    """, (gid, st['id'], st['id']), one=True)
    dati = {k: (v if v is not None else 0) for k, v in dict(r).items()} if r else {}
    return jsonify(dati)


@app.route('/api/classifica/<int:sid>')
def api_classifica(sid):
    rows = query("""
        SELECT nome, punti, gf, gs, diff
        FROM v_classifica WHERE id_stagione=?
        ORDER BY punti DESC
    """, (sid,))
    return jsonify([dict(r) for r in rows])


# ============================================================
#  5. AREA AMMINISTRAZIONE (autenticata)
# ============================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        utente = query("SELECT * FROM Utente WHERE username = ?", (username,), one=True)
        if utente and check_password_hash(utente['password_hash'], password):
            session['user_id'] = utente['id']
            session['username'] = utente['username']
            flash(f'Bentornato, {utente["username"]}.', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Username o password non corretti.', 'error')
    return render_template('admin/login.html')


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    flash('Disconnesso.', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@login_required
def admin_dashboard():
    conteggi = dict(
        giocatori=query("SELECT COUNT(*) n FROM Giocatore", one=True)['n'],
        squadre=query("SELECT COUNT(*) n FROM Squadra", one=True)['n'],
        partite=query("SELECT COUNT(*) n FROM Partita", one=True)['n'],
        stagioni=query("SELECT COUNT(*) n FROM Stagione", one=True)['n'],
    )
    # Mostra il trigger trg_giocatore_timestamp "in azione": i giocatori
    # modificati piu' di recente salgono in cima a questa lista.
    ultimi_modificati = query("""
        SELECT id, nome, cognome, ultima_modifica
        FROM Giocatore ORDER BY ultima_modifica DESC LIMIT 5
    """)
    ultime_partite = query("""
        SELECT p.id, p.data, sc.nome AS sq_casa, sp.nome AS sq_ospite,
               p.gol_casa, p.gol_ospiti
        FROM Partita p
        JOIN Squadra sc ON p.id_sq_casa = sc.id
        JOIN Squadra sp ON p.id_sq_ospite = sp.id
        ORDER BY p.id DESC LIMIT 5
    """)
    return render_template('admin/dashboard.html',
        conteggi=conteggi, ultimi_modificati=ultimi_modificati,
        ultime_partite=ultime_partite)


# ---------------------------------------------------------
#  Giocatori (CRUD)
# ---------------------------------------------------------
@app.route('/admin/giocatori')
@login_required
def admin_giocatori():
    giocatori = query("""
        SELECT g.*,
               (SELECT sq.nome FROM Rosa r JOIN Squadra sq ON r.id_squadra = sq.id
                WHERE r.id_giocatore = g.id ORDER BY r.id_stagione DESC LIMIT 1) AS squadra_attuale
        FROM Giocatore g
        ORDER BY g.cognome, g.nome
    """)
    return render_template('admin/giocatori.html', giocatori=giocatori)


@app.route('/admin/giocatori/nuovo', methods=['GET', 'POST'])
@login_required
def admin_giocatore_nuovo():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        cognome = request.form.get('cognome', '').strip()
        nazionalita = request.form.get('nazionalita', '').strip() or None
        data_nascita = request.form.get('data_nascita') or None
        ruolo = request.form.get('ruolo')
        piede = request.form.get('piede_preferito') or 'Destro'
        altezza_raw = request.form.get('altezza_cm') or ''

        if not nome or not cognome or not ruolo:
            flash('Nome, cognome e ruolo sono obbligatori.', 'error')
            return redirect(url_for('admin_giocatore_nuovo'))
        try:
            altezza = int(altezza_raw) if altezza_raw else None
            id_squadra = int(request.form['id_squadra'])
            id_stagione = int(request.form['id_stagione'])
            numero_maglia = int(request.form['numero_maglia'])
        except (ValueError, KeyError):
            flash('Controlla i campi numerici (altezza, maglia, squadra, stagione).', 'error')
            return redirect(url_for('admin_giocatore_nuovo'))

        nuovo_id, errore = crea_giocatore_con_rosa(
            (nome, cognome, nazionalita, data_nascita, ruolo, piede, altezza),
            id_squadra, id_stagione, numero_maglia)

        if errore:
            flash(errore, 'error')
            return redirect(url_for('admin_giocatore_nuovo'))

        flash(f'Giocatore {nome} {cognome} creato e tesserato.', 'success')
        return redirect(url_for('admin_giocatori'))

    squadre = query("SELECT id, nome FROM Squadra ORDER BY nome")
    return render_template('admin/giocatore_form.html',
        giocatore=None, modalita='nuovo', squadre=squadre)


@app.route('/admin/giocatori/<int:gid>/modifica', methods=['GET', 'POST'])
@login_required
def admin_giocatore_modifica(gid):
    g = query("SELECT * FROM Giocatore WHERE id = ?", (gid,), one=True)
    if not g: abort(404)

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        cognome = request.form.get('cognome', '').strip()
        nazionalita = request.form.get('nazionalita', '').strip() or None
        data_nascita = request.form.get('data_nascita') or None
        ruolo = request.form.get('ruolo')
        piede = request.form.get('piede_preferito') or 'Destro'
        altezza_raw = request.form.get('altezza_cm') or ''

        if not nome or not cognome or not ruolo:
            flash('Nome, cognome e ruolo sono obbligatori.', 'error')
            return redirect(url_for('admin_giocatore_modifica', gid=gid))
        try:
            altezza = int(altezza_raw) if altezza_raw else None
        except ValueError:
            flash('Altezza non valida.', 'error')
            return redirect(url_for('admin_giocatore_modifica', gid=gid))

        try:
            # Questo UPDATE fa scattare trg_giocatore_timestamp, che
            # aggiorna automaticamente ultima_modifica lato database.
            esegui("""UPDATE Giocatore SET nome=?,cognome=?,nazionalita=?,data_nascita=?,
                      ruolo=?,piede_preferito=?,altezza_cm=? WHERE id=?""",
                   (nome, cognome, nazionalita, data_nascita, ruolo, piede, altezza, gid))
            flash('Dati giocatore aggiornati.', 'success')
            return redirect(url_for('admin_giocatori'))
        except sqlite3.IntegrityError as e:
            flash(messaggio_errore_db(e), 'error')
            return redirect(url_for('admin_giocatore_modifica', gid=gid))

    return render_template('admin/giocatore_form.html',
        giocatore=g, modalita='modifica', squadre=None)


@app.route('/admin/giocatori/<int:gid>/elimina', methods=['POST'])
@login_required
def admin_giocatore_elimina(gid):
    try:
        esegui("DELETE FROM Giocatore WHERE id = ?", (gid,))
        flash('Giocatore eliminato (rosa e statistiche collegate rimosse a cascata).', 'success')
    except sqlite3.IntegrityError as e:
        flash(messaggio_errore_db(e), 'error')
    return redirect(url_for('admin_giocatori'))


# ---------------------------------------------------------
#  Squadre (CRUD)
# ---------------------------------------------------------
@app.route('/admin/squadre')
@login_required
def admin_squadre():
    squadre = query("""
        SELECT sq.*, COUNT(DISTINCT p.id) AS n_partite
        FROM Squadra sq
        LEFT JOIN Partita p ON p.id_sq_casa = sq.id OR p.id_sq_ospite = sq.id
        GROUP BY sq.id ORDER BY sq.nome
    """)
    return render_template('admin/squadre.html', squadre=squadre)


@app.route('/admin/squadre/nuova', methods=['GET', 'POST'])
@login_required
def admin_squadra_nuova():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        citta = request.form.get('citta', '').strip()
        stadio = request.form.get('stadio', '').strip() or None
        anno_raw = request.form.get('anno_fondazione') or ''
        colore = request.form.get('colore_primario') or '#1a2e23'

        if not nome or not citta:
            flash('Nome e città sono obbligatori.', 'error')
            return redirect(url_for('admin_squadra_nuova'))
        try:
            anno = int(anno_raw) if anno_raw else None
        except ValueError:
            flash('Anno di fondazione non valido.', 'error')
            return redirect(url_for('admin_squadra_nuova'))

        try:
            esegui("""INSERT INTO Squadra(nome,citta,stadio,anno_fondazione,colore_primario)
                     VALUES (?,?,?,?,?)""", (nome, citta, stadio, anno, colore))
            flash(f'Squadra {nome} creata.', 'success')
            return redirect(url_for('admin_squadre'))
        except sqlite3.IntegrityError as e:
            flash(messaggio_errore_db(e), 'error')
            return redirect(url_for('admin_squadra_nuova'))

    return render_template('admin/squadra_form.html', sq=None, modalita='nuova')


@app.route('/admin/squadre/<int:sid>/modifica', methods=['GET', 'POST'])
@login_required
def admin_squadra_modifica(sid):
    sq = query("SELECT * FROM Squadra WHERE id = ?", (sid,), one=True)
    if not sq: abort(404)

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        citta = request.form.get('citta', '').strip()
        stadio = request.form.get('stadio', '').strip() or None
        anno_raw = request.form.get('anno_fondazione') or ''
        colore = request.form.get('colore_primario') or '#1a2e23'

        if not nome or not citta:
            flash('Nome e città sono obbligatori.', 'error')
            return redirect(url_for('admin_squadra_modifica', sid=sid))
        try:
            anno = int(anno_raw) if anno_raw else None
        except ValueError:
            flash('Anno di fondazione non valido.', 'error')
            return redirect(url_for('admin_squadra_modifica', sid=sid))

        try:
            esegui("""UPDATE Squadra SET nome=?,citta=?,stadio=?,anno_fondazione=?,
                      colore_primario=? WHERE id=?""",
                   (nome, citta, stadio, anno, colore, sid))
            flash('Squadra aggiornata.', 'success')
            return redirect(url_for('admin_squadre'))
        except sqlite3.IntegrityError as e:
            flash(messaggio_errore_db(e), 'error')
            return redirect(url_for('admin_squadra_modifica', sid=sid))

    return render_template('admin/squadra_form.html', sq=sq, modalita='modifica')


@app.route('/admin/squadre/<int:sid>/elimina', methods=['POST'])
@login_required
def admin_squadra_elimina(sid):
    try:
        # Rosa referenzia Squadra con ON DELETE CASCADE, ma Partita NO
        # (nessuna azione = comportamento di default in SQLite): se la
        # squadra ha gia' giocato delle partite, questa DELETE fallisce
        # con un errore di integrità referenziale e va gestita qui.
        esegui("DELETE FROM Squadra WHERE id = ?", (sid,))
        flash('Squadra eliminata.', 'success')
    except sqlite3.IntegrityError as e:
        flash(messaggio_errore_db(e), 'error')
    return redirect(url_for('admin_squadre'))


# ---------------------------------------------------------
#  Partite + tabellino (CRUD, con Statistica annidata)
# ---------------------------------------------------------
@app.route('/admin/partite')
@login_required
def admin_partite():
    partite = query("""
        SELECT p.id, p.data, p.giornata, p.gol_casa, p.gol_ospiti,
               sc.nome AS sq_casa, sp.nome AS sq_ospite,
               printf('%d/%02d', st.anno_inizio, st.anno_fine%100) AS stagione_label,
               (SELECT COUNT(*) FROM Statistica WHERE id_partita = p.id) AS n_statistiche
        FROM Partita p
        JOIN Squadra sc ON p.id_sq_casa = sc.id
        JOIN Squadra sp ON p.id_sq_ospite = sp.id
        JOIN Stagione st ON p.id_stagione = st.id
        ORDER BY p.data DESC
    """)
    return render_template('admin/partite.html', partite=partite)


@app.route('/admin/partite/nuova', methods=['GET', 'POST'])
@login_required
def admin_partita_nuova():
    if request.method == 'POST':
        try:
            id_stagione = int(request.form['stagione'])
            id_sq_casa = int(request.form['sq_casa'])
            id_sq_ospite = int(request.form['sq_ospite'])
            giornata = int(request.form['giornata'])
            gol_casa = int(request.form.get('gol_casa') or 0)
            gol_ospiti = int(request.form.get('gol_ospiti') or 0)
            spett_raw = request.form.get('spettatori') or ''
            spettatori = int(spett_raw) if spett_raw else None
        except (ValueError, KeyError):
            flash('Controlla i campi numerici della partita.', 'error')
            return redirect(url_for('admin_partita_nuova'))

        data_p = request.form.get('data')
        arbitro = request.form.get('arbitro', '').strip() or None
        if not data_p:
            flash('La data della partita è obbligatoria.', 'error')
            return redirect(url_for('admin_partita_nuova'))
        if id_sq_casa == id_sq_ospite:
            flash('Le due squadre devono essere diverse.', 'error')
            return redirect(url_for('admin_partita_nuova'))

        try:
            nuovo_id = esegui("""INSERT INTO Partita
                (data,giornata,gol_casa,gol_ospiti,spettatori,arbitro,
                 id_stagione,id_sq_casa,id_sq_ospite)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (data_p, giornata, gol_casa, gol_ospiti, spettatori, arbitro,
                 id_stagione, id_sq_casa, id_sq_ospite))
            flash('Partita creata. Ora puoi compilare il tabellino qui sotto.', 'success')
            return redirect(url_for('admin_partita_dettaglio', pid=nuovo_id))
        except sqlite3.IntegrityError as e:
            flash(messaggio_errore_db(e), 'error')
            return redirect(url_for('admin_partita_nuova'))

    squadre = query("SELECT id, nome FROM Squadra ORDER BY nome")
    return render_template('admin/partita_form.html',
        squadre=squadre, stagione_corrente=stagione_default())


@app.route('/admin/partite/<int:pid>')
@login_required
def admin_partita_dettaglio(pid):
    pt = query("""
        SELECT p.*, sc.nome AS sq_casa, sp.nome AS sq_ospite,
               printf('%d/%02d', st.anno_inizio, st.anno_fine%100) AS stage_label
        FROM Partita p
        JOIN Squadra sc ON p.id_sq_casa = sc.id
        JOIN Squadra sp ON p.id_sq_ospite = sp.id
        JOIN Stagione st ON p.id_stagione = st.id
        WHERE p.id = ?
    """, (pid,), one=True)
    if not pt: abort(404)

    statistiche = query("""
        SELECT s.*, g.nome, g.cognome, g.ruolo, sq.id AS id_squadra, sq.nome AS squadra
        FROM Statistica s
        JOIN Giocatore g ON g.id = s.id_giocatore
        JOIN Rosa r ON r.id_giocatore = g.id AND r.id_stagione = ?
        JOIN Squadra sq ON r.id_squadra = sq.id
        WHERE s.id_partita = ?
        ORDER BY sq.id,
            CASE g.ruolo WHEN 'Portiere' THEN 1 WHEN 'Difensore' THEN 2
                         WHEN 'Centrocampista' THEN 3 ELSE 4 END, g.cognome
    """, (pt['id_stagione'], pid))

    # Solo i giocatori tesserati con una delle due squadre in questa
    # stagione E che non hanno ancora una riga in questo tabellino:
    # e' lo stesso filtro imposto anche dal trigger trg_statistica_rosa_check,
    # qui applicato lato applicazione per una UX piu' comoda (il trigger
    # resta comunque come rete di sicurezza a livello di database).
    disponibili = query("""
        SELECT g.id, g.nome, g.cognome, g.ruolo, sq.nome AS squadra
        FROM Rosa r
        JOIN Giocatore g ON r.id_giocatore = g.id
        JOIN Squadra sq ON r.id_squadra = sq.id
        WHERE r.id_stagione = ? AND r.id_squadra IN (?, ?)
          AND r.id_giocatore NOT IN (
              SELECT id_giocatore FROM Statistica WHERE id_partita = ?
          )
        ORDER BY sq.nome, g.cognome
    """, (pt['id_stagione'], pt['id_sq_casa'], pt['id_sq_ospite'], pid))

    return render_template('admin/partita_detail.html',
        pt=pt, statistiche=statistiche, disponibili=disponibili)


@app.route('/admin/partite/<int:pid>/elimina', methods=['POST'])
@login_required
def admin_partita_elimina(pid):
    try:
        esegui("DELETE FROM Partita WHERE id = ?", (pid,))
        flash('Partita eliminata (statistiche collegate rimosse a cascata).', 'success')
    except sqlite3.IntegrityError as e:
        flash(messaggio_errore_db(e), 'error')
    return redirect(url_for('admin_partite'))


def _leggi_campi_statistica(form):
    """Legge e converte i campi numerici del form tabellino."""
    return dict(
        minuti=int(form.get('minuti') or 0),
        gol=int(form.get('gol') or 0),
        assist=int(form.get('assist') or 0),
        cartellini_gialli=1 if form.get('cartellini_gialli') else 0,
        cartellini_rossi=1 if form.get('cartellini_rossi') else 0,
        tiri=int(form.get('tiri') or 0),
        tiri_in_porta=int(form.get('tiri_in_porta') or 0),
        passaggi=int(form.get('passaggi') or 0),
        passaggi_riusciti=int(form.get('passaggi_riusciti') or 0),
        dribbling_riusciti=int(form.get('dribbling_riusciti') or 0),
        contrasti=int(form.get('contrasti') or 0),
        intercetti=int(form.get('intercetti') or 0),
        xG=float(form.get('xG') or 0),
    )


@app.route('/admin/partite/<int:pid>/statistiche/nuova', methods=['POST'])
@login_required
def admin_statistica_nuova(pid):
    try:
        id_giocatore = int(request.form['id_giocatore'])
        c = _leggi_campi_statistica(request.form)
    except (ValueError, KeyError):
        flash('Dati statistica non validi: controlla i campi numerici.', 'error')
        return redirect(url_for('admin_partita_dettaglio', pid=pid))

    try:
        esegui("""INSERT INTO Statistica
            (id_giocatore,id_partita,minuti,gol,assist,cartellini_gialli,cartellini_rossi,
             tiri,tiri_in_porta,passaggi,passaggi_riusciti,dribbling_riusciti,
             contrasti,intercetti,xG)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (id_giocatore, pid, c['minuti'], c['gol'], c['assist'],
             c['cartellini_gialli'], c['cartellini_rossi'],
             c['tiri'], c['tiri_in_porta'], c['passaggi'], c['passaggi_riusciti'],
             c['dribbling_riusciti'], c['contrasti'], c['intercetti'], c['xG']))
        flash('Statistica aggiunta al tabellino.', 'success')
    except sqlite3.IntegrityError as e:
        flash(messaggio_errore_db(e), 'error')
    return redirect(url_for('admin_partita_dettaglio', pid=pid))


@app.route('/admin/partite/<int:pid>/statistiche/<int:stat_id>/modifica', methods=['GET', 'POST'])
@login_required
def admin_statistica_modifica(pid, stat_id):
    stat = query("""SELECT s.*, g.nome, g.cognome FROM Statistica s
                     JOIN Giocatore g ON g.id = s.id_giocatore
                     WHERE s.id = ? AND s.id_partita = ?""", (stat_id, pid), one=True)
    if not stat: abort(404)

    if request.method == 'POST':
        try:
            c = _leggi_campi_statistica(request.form)
        except ValueError:
            flash('Dati statistica non validi.', 'error')
            return redirect(url_for('admin_statistica_modifica', pid=pid, stat_id=stat_id))

        try:
            esegui("""UPDATE Statistica SET minuti=?,gol=?,assist=?,cartellini_gialli=?,
                      cartellini_rossi=?,tiri=?,tiri_in_porta=?,passaggi=?,passaggi_riusciti=?,
                      dribbling_riusciti=?,contrasti=?,intercetti=?,xG=? WHERE id=?""",
                   (c['minuti'], c['gol'], c['assist'], c['cartellini_gialli'],
                    c['cartellini_rossi'], c['tiri'], c['tiri_in_porta'],
                    c['passaggi'], c['passaggi_riusciti'], c['dribbling_riusciti'],
                    c['contrasti'], c['intercetti'], c['xG'], stat_id))
            flash('Statistica aggiornata.', 'success')
            return redirect(url_for('admin_partita_dettaglio', pid=pid))
        except sqlite3.IntegrityError as e:
            flash(messaggio_errore_db(e), 'error')
            return redirect(url_for('admin_statistica_modifica', pid=pid, stat_id=stat_id))

    return render_template('admin/statistica_form.html', stat=stat, pid=pid)


@app.route('/admin/partite/<int:pid>/statistiche/<int:stat_id>/elimina', methods=['POST'])
@login_required
def admin_statistica_elimina(pid, stat_id):
    esegui("DELETE FROM Statistica WHERE id = ? AND id_partita = ?", (stat_id, pid))
    flash('Riga statistica eliminata.', 'success')
    return redirect(url_for('admin_partita_dettaglio', pid=pid))


# ============================================================
#  RUN
# ============================================================
if __name__ == '__main__':
    if not os.path.exists(DB):
        print("DB non trovato – esegui: python seed_demo.py")
    app.run(debug=True)
