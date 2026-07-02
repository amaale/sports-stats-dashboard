# Sports Stats Dashboard

Sports Stats Dashboard è un'applicazione web full-stack sviluppata per la consultazione, l'analisi e la gestione delle statistiche di un campionato calcistico. Il focus primario del progetto risiede nella progettazione logico-concettuale e nell'ottimizzazione di una base di dati relazionale. 

Per mantenere il pieno controllo granulare sulle operazioni e massimizzare l'efficienza computazionale delle interrogazioni, lo sviluppo ha escluso l'utilizzo di ORM (Object-Relational Mapping), affidandosi esclusivamente a **SQL puro** tramite le librerie native del linguaggio.

## Stack Tecnologico
- **Backend:** Python 3.x, Flask (Framework micro)
- **Database Architecture:** SQLite 3 (Interfaccia nativa tramite modulo `sqlite3`)
- **Frontend Architecture:** HTML5, CSS3, Jinja2 (Server-side rendering)
- **Data Visualization:** Chart.js (Dipendenze strutturate in locale per operare offline)

## Architettura del Database & Vincoli di Integrità
Il database implementa vincoli di integrità referenziale complessi e costrutti relazionali avanzati per garantire l'atomicità e la coerenza del dato:

1. **Relazione Ternaria (`Rosa`):** Modella il tesseramento stagionale dei calciatori presso una squadra. La chiave primaria composta `PRIMARY KEY(id_giocatore, id_stagione)` impone rigidamente il vincolo di business *"un giocatore può militare in una sola squadra all'interno della medesima stagione"*. Un vincolo `UNIQUE(id_squadra, id_stagione, numero_maglia)` impedisce la duplicazione dei numeri di maglia all'interno della stessa rosa.
2. **Entità Autonoma `Partita`:** Modellata come entità indipendente (e non come relazione N-aria tra squadre) per consentire il referenziamento univoco da parte dei tabellini individuali, superando le criticità legate ai match plurimi (andata/ritorno) nella stessa stagione.
3. **Calcolo della Classifica Dinamica a Runtime:** La vista `v_classifica` computa in tempo reale punti, vittorie, pareggi, sconfitte e differenza reti. La logica separa i contributi dei match interni da quelli esterni attraverso due Common Table Expressions (CTE) aggregate tramite operatore vettoriale `UNION ALL`.
4. **Analisi Statistica Avanzata (`RANK() OVER`):** I report prestazionali (es. classifica marcatori) utilizzano CTE annidate e funzioni finestra di ranking analitico per gestire nativamente e in modo corretto le situazioni di pari-merito, evitando le limitazioni del tradizionale ordinamento sequenziale.
5. **Data Normalization via API JSON:** Gli endpoint applicativi espongono i dati di performance normalizzandoli su scala 0-100 rispetto ai massimi di lega tramite query aggregate concorrenti, permettendo la renderizzazione asincrona di grafici a radar.

## Logica di Business e Sicurezza a Livello DB
I vincoli di consistenza non sono delegati unicamente all'interfaccia applicativa, ma vengono protetti in modo deterministico dal DBMS:
- **Trigger `trg_statistica_rosa_check` (`BEFORE INSERT`):** Verifica tramite clausola `EXISTS` che l'inserimento di una metrica individuale nella tabella `Statistica` sia consentito solo se il calciatore risulta regolarmente tesserato nella `Rosa` di una delle due compagini partecipanti a quella specifica gara. In caso negativo, l'operazione viene abortita via `RAISE(ABORT, ...)`.
- **Transazioni Multi-Statement Atomiche:** Le operazioni CRUD complesse (es. la creazione di un atleta e la contestuale assegnazione alla rosa stagionale) sono incapsulate in blocchi transazionali espliciti con gestione rigorosa di `commit()` e `rollback()` per prevenire la persistenza di record orfani.
- **Data Security:** L'accesso alle funzionalità amministrative e di scrittura è protetto da un middleware di autenticazione assistito da password hashing crittografico asimmetrico.

## Struttura del Repository
```text
sports-stats/
├── app.py                  # Core applicativo Flask (routing, controller e API)
├── schema.sql              # Data Definition Language (DDL): tabelle, indici, viste, trigger
├── seed_demo.py            # Script di data seeding per popolamento automatico del DB
├── stats.db                # Database relazionale SQLite (generato localmente)
├── static/
│   └── js/
│       └── chart.umd.min.js # Libreria grafica Chart.js (vendorizzata localmente)
└── templates/
    ├── base.html            # Master layout e schemi di formattazione comuni
    └── admin/               # Area di gestione riservata (Pannello CRUD e Tabellini)
