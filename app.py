from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os, hashlib
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'stocketf2026CN')

# ─── BASE DE DONNÉES — PostgreSQL (Supabase) ou SQLite (local) ────────────────
DATABASE_URL = os.environ.get('DATABASE_URL', '')
USE_POSTGRES = DATABASE_URL.startswith('postgresql') if DATABASE_URL else False

import sqlite3

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

def adapt_sql(sql):
    """Convertit SQL SQLite en SQL PostgreSQL."""
    sql = sql.replace('?', '%s')
    sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')
    sql = sql.replace('BIGSERIAL PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')
    sql = sql.replace(' AUTOINCREMENT', '')
    sql = sql.replace('TEXT DEFAULT CURRENT_TIMESTAMP', 'TEXT DEFAULT NOW()::TEXT')
    sql = sql.replace('PRAGMA journal_mode=WAL', 'SELECT 1')
    sql = sql.replace('INSERT INTO', 'INSERT INTO')
    sql = sql.replace('INSERT INTO', 'INSERT INTO')
    # Ajouter ON CONFLICT DO NOTHING pour les INSERT INTO avec OR IGNORE
    if 'INSERT INTO' in sql and 'ON CONFLICT' not in sql and 'SELECT' not in sql:
        sql = sql.rstrip().rstrip(';')
        sql += ' ON CONFLICT DO NOTHING'
    return sql

class Connection:
    """Connexion unifiée SQLite/PostgreSQL."""
    def __init__(self):
        if USE_POSTGRES:
            self._conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
            self._conn.autocommit = False
            self._pg = True
        else:
            self._conn = sqlite3.connect(os.environ.get('DATABASE_PATH','stocketf.db'))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._pg = False
    
    def execute(self, sql, params=None):
        if self._pg:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql_adapted = adapt_sql(sql)
            # Ajouter ON CONFLICT DO NOTHING aux INSERT simples
            if sql_adapted.strip().upper().startswith('INSERT INTO') and 'ON CONFLICT' not in sql_adapted.upper():
                sql_adapted += ' ON CONFLICT DO NOTHING'
            try:
                cur.execute(sql_adapted, list(params) if params else None)
            except Exception as e:
                self._conn.rollback()
                raise e
            return PGResult(cur)
        else:
            if params:
                return self._conn.execute(sql, params)
            return self._conn.execute(sql)
    
    def cursor(self):
        """Retourne self pour compatibilité avec le code qui utilise conn.cursor()."""
        return self
    
    def executescript(self, script):
        if self._pg:
            cur = self._conn.cursor()
            stmts = adapt_sql(script).split(';')
            for stmt in stmts:
                stmt = stmt.strip()
                if not stmt or stmt.startswith('--'): continue
                # Ajouter ON CONFLICT DO NOTHING aux INSERT
                if stmt.upper().startswith('INSERT INTO') and 'ON CONFLICT' not in stmt.upper():
                    stmt += ' ON CONFLICT DO NOTHING'
                try:
                    cur.execute(stmt)
                    self._conn.commit()
                except Exception as e:
                    self._conn.rollback()
        else:
            self._conn.executescript(script)
    
    def commit(self):
        self._conn.commit()
    
    def close(self):
        self._conn.close()

class PGRow(dict):
    """Ligne PostgreSQL accessible par nom ET par index."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class PGResult:
    """Résultat PostgreSQL compatible avec l'interface SQLite."""
    def __init__(self, cursor):
        self._cur = cursor
        self._rows = None
    def fetchone(self):
        row = self._cur.fetchone()
        return PGRow(row) if row else None
    def fetchall(self):
        rows = self._cur.fetchall()
        return [PGRow(r) for r in rows]
    def __iter__(self):
        return iter(self.fetchall())
    def __getitem__(self, key):
        row = self.fetchone()
        if row is None: return None
        return row[key]

def get_db():
    return Connection()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_etat_stock(stock, stock_min, stock_alerte):
    if stock == 0: return 'RUPTURE'
    elif stock <= stock_min: return 'CRITIQUE'
    elif stock <= stock_alerte: return 'ALERTE'
    else: return 'OK'

def log_mouvement(conn, type_mv, article_id, quantite, ref_doc, 
                  stock_avant, stock_apres, container_id=0, chantier_id=0, details=''):
    """Enregistrer un mouvement avec infos utilisateur."""
    from flask import session as sess
    user_id = sess.get('user_id', 0) or 0
    user_nom = sess.get('user_nom', '') or ''
    conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
        quantite,reference_doc,stock_avant,stock_apres,container_id,chantier_id,
        user_id,user_nom,details)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
        date.today().isoformat(), type_mv, article_id, quantite, ref_doc,
        stock_avant, stock_apres, container_id or 0, chantier_id or 0,
        user_id, user_nom, details
    ))

def get_next_numero(table, col, prefix):
    conn = get_db()
    row = conn.execute(f"SELECT {col} FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if row and row[0]:
        try: n = int(row[0].replace(prefix,'')) + 1
        except: n = 1
    else: n = 1
    return f"{prefix}{n:03d}"

@app.context_processor
def inject_globals():
    """Injecte les données dynamiques dans tous les templates automatiquement."""
    if 'user_id' not in session:
        return {}
    try:
        conn = get_db()
        nav_containers = conn.execute(
            "SELECT id, nom, code, statut FROM containers WHERE actif=1 ORDER BY nom"
        ).fetchall()
        nav_chantiers = conn.execute(
            "SELECT id, nom, code FROM chantiers WHERE actif=1 ORDER BY nom"
        ).fetchall()
        nav_familles = conn.execute(
            "SELECT id, nom, icone FROM familles WHERE actif=1 ORDER BY nom"
        ).fetchall()
        # Stats rapides pour le menu
        nb_ruptures = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE actif=1 AND stock=0"
        ).fetchone()[0]
        nb_alertes = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE actif=1 AND stock>0 AND stock<=stock_alerte"
        ).fetchone()[0]
        nb_cmds_att = conn.execute(
            "SELECT COUNT(*) FROM commandes WHERE statut='EN ATTENTE'"
        ).fetchone()[0]
        conn.close()
        return dict(
            nav_containers=nav_containers,
            nav_chantiers=nav_chantiers,
            nav_familles=nav_familles,
            nav_ruptures=nb_ruptures,
            nav_alertes=nb_alertes,
            nav_cmds_att=nb_cmds_att,
        )
    except:
        return {}

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS utilisateurs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT DEFAULT 'stock',
        actif INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS familles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT UNIQUE NOT NULL, icone TEXT DEFAULT '📦',
        couleur TEXT DEFAULT '#E8661A', description TEXT DEFAULT '',
        actif INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS containers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, code TEXT UNIQUE NOT NULL,
        numero TEXT DEFAULT '', description TEXT DEFAULT '',
        emplacement TEXT DEFAULT '', chantier_id INTEGER DEFAULT 0,
        statut TEXT DEFAULT 'ACTIF', actif INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS chantiers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, code TEXT UNIQUE NOT NULL,
        adresse TEXT DEFAULT '', chef TEXT DEFAULT '',
        date_debut TEXT DEFAULT '', date_fin TEXT DEFAULT '',
        statut TEXT DEFAULT 'ACTIF', budget REAL DEFAULT 0,
        actif INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS articles (
        id TEXT PRIMARY KEY, famille TEXT NOT NULL, designation TEXT NOT NULL,
        reference TEXT DEFAULT '', marque TEXT DEFAULT '', container_id INTEGER DEFAULT 0,
        emplacement TEXT DEFAULT '', unite TEXT DEFAULT 'UNITE', colisage INTEGER DEFAULT 1,
        prix_achat REAL DEFAULT 0, fournisseur TEXT DEFAULT '', stock INTEGER DEFAULT 0,
        stock_min INTEGER DEFAULT 0, stock_alerte INTEGER DEFAULT 0, stock_max INTEGER DEFAULT 0,
        observations TEXT DEFAULT '', actif INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS bons_sortie (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
        date_sortie TEXT NOT NULL, demandeur TEXT NOT NULL, chantier_id INTEGER DEFAULT 0,
        commentaire TEXT DEFAULT '', statut TEXT DEFAULT 'VALIDE',
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS bons_sortie_lignes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bon_id INTEGER NOT NULL, article_id TEXT NOT NULL,
        quantite INTEGER NOT NULL, prix_achat REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bons_reception (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
        date_reception TEXT NOT NULL, fournisseur TEXT NOT NULL, num_bl TEXT DEFAULT '',
        article_id TEXT NOT NULL, qte_commandee INTEGER DEFAULT 0, qte_recue INTEGER NOT NULL,
        prix_unitaire REAL DEFAULT 0, commentaire TEXT DEFAULT '',
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commandes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
        date_demande TEXT NOT NULL, fournisseur TEXT DEFAULT '',
        statut TEXT DEFAULT 'EN ATTENTE', date_commande TEXT DEFAULT '',
        livraison_prevue TEXT DEFAULT '', date_reception TEXT DEFAULT '',
        commentaire TEXT DEFAULT '', created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commande_lignes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commande_id INTEGER NOT NULL, article_id TEXT NOT NULL,
        quantite INTEGER NOT NULL, prix_unitaire REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS transferts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
        date_transfert TEXT NOT NULL, article_id TEXT NOT NULL,
        container_source INTEGER NOT NULL, container_dest INTEGER NOT NULL,
        quantite INTEGER NOT NULL, commentaire TEXT DEFAULT '',
        created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS inventaires (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL,
        date_inventaire TEXT NOT NULL, container_id INTEGER DEFAULT 0,
        article_id TEXT NOT NULL, stock_theorique INTEGER DEFAULT 0,
        stock_reel INTEGER NOT NULL, ecart INTEGER DEFAULT 0,
        commentaire TEXT DEFAULT '', created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS mouvements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date_mouvement TEXT NOT NULL,
        type_mouvement TEXT NOT NULL, article_id TEXT NOT NULL, quantite INTEGER NOT NULL,
        reference_doc TEXT DEFAULT '', stock_avant INTEGER DEFAULT 0,
        stock_apres INTEGER DEFAULT 0, container_id INTEGER DEFAULT 0,
        chantier_id INTEGER DEFAULT 0, user_id INTEGER DEFAULT 0,
        user_nom TEXT DEFAULT '', details TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS fournisseurs (
        id TEXT PRIMARY KEY, nom TEXT NOT NULL, contact TEXT DEFAULT '',
        telephone TEXT DEFAULT '', email TEXT DEFAULT '', adresse TEXT DEFAULT '',
        delai INTEGER DEFAULT 7, conditions TEXT DEFAULT '30j net',
        articles_fournis TEXT DEFAULT '', commentaires TEXT DEFAULT '', actif INTEGER DEFAULT 1
    );
    """)

    # Utilisateurs
    for u in [
        ('Admin','admin@stocketf.com',hash_pw('admin2026'),'admin'),
        ('Stock','stock@stocketf.com',hash_pw('stock2026'),'magasinier'),
        ('Responsable','responsable@stocketf.com',hash_pw('resp2026'),'responsable'),
        ('Chantier','chantier@stocketf.com',hash_pw('chant2026'),'chef_chantier'),
    ]:
        c.execute("INSERT INTO utilisateurs (nom,email,password_hash,role) VALUES (?,?,?,?)", u)

    # Familles
    familles = [
        ('Protection Individuelle','🧤','#dc2626'),
        ('Vêtements de travail','🦺','#d97706'),
        ('Outillage Manuel','🔧','#16a34a'),
        ('Outillage Électroportatif','⚡','#2563eb'),
        ('Éclairage & Électricité','💡','#f59e0b'),
        ('Batteries & Piles','🔋','#7c3aed'),
        ('Abrasifs & Disques','🔨','#db2777'),
        ('Lubrifiants & Produits','💧','#0891b2'),
        ('Conditionnement & Rangement','📦','#65a30d'),
        ('Nettoyage & Hygiène','🧹','#0d9488'),
        ('Mesure & Traçage','📏','#6366f1'),
        ('Fixations & Visserie','🔩','#9333ea'),
        ('Outillage Ferroviaire','⛏️','#1a1a2e'),
        ('Équipements Spéciaux','⚙️','#E8661A'),
        ('Matériaux & Géotextiles','🏗️','#78716c'),
        ('Gaz & Soudage','🔥','#ef4444'),
    ]
    for f in familles:
        c.execute("INSERT INTO familles (nom,icone,couleur) VALUES (?,?,?)", f)

    # Containers
    containers = [
        ('Container BLEU','BLEU','C-001','EPI, Protection individuelle, Outillage','Base arrière',0,'ACTIF'),
        ('Container 5','C5','C-002','Abrasifs, Disques, Éclairage','Base arrière',0,'ACTIF'),
        ('Container 3','C3','C-003','Fixations, Visserie, Ferroviaire','Base arrière',0,'ACTIF'),
        ('Container 9','C9','C-004','Matériaux, Géotextiles, Produits','Base arrière',0,'ACTIF'),
        ('Container Fabrice','FABRICE','C-005','Outillage Manuel, Sangles','Base arrière',0,'ACTIF'),
        ('Zone Gaz — Plein Air','GAZ','C-006','Bouteilles gaz stockées en extérieur','Stockage plein air',0,'ACTIF'),
    ]
    for ct in containers:
        c.execute("INSERT INTO containers (nom,code,numero,description,emplacement,chantier_id,statut) VALUES (?,?,?,?,?,?,?)", ct)

    # Chantiers
    chantiers = [
        ('Chantier A - Zone 1','CH-001','Zone industrielle Nord','Martin J.','2025-01-01','2025-12-31','ACTIF',50000),
        ('Chantier A - Zone 2','CH-002','Zone industrielle Nord','Dupont P.','2025-02-01','2025-12-31','ACTIF',35000),
        ('Chantier B','CH-003','Gare centrale','Bernard L.','2025-01-15','2025-10-31','ACTIF',80000),
        ('Chantier C','CH-004','Voie ferrée km 42','Martin J.','2025-03-01','2025-09-30','ACTIF',60000),
        ('Base arrière','CH-005','Dépôt principal','Admin','2025-01-01','2026-12-31','ACTIF',0),
    ]
    for ch in chantiers:
        c.execute("INSERT INTO chantiers (nom,code,adresse,chef,date_debut,date_fin,statut,budget) VALUES (?,?,?,?,?,?,?,?)", ch)

    # 612 articles réels avec marque et fournisseur séparés
    articles = [
        ('ART-001','Outillage Électroportatif','TRONCONNEUSE STIHL','TS440','Stihl',1,'A1','UNITE',1,0.0,'Stihl France',2,1,0,3,''),
        ('ART-002','Outillage Électroportatif','PROJECTEUR LED','10 000LM','',1,'A1','UNITE',1,0.0,'Prolian',3,1,0,3,''),
        ('ART-003','Protection Individuelle','GANTS ANTI-COUPURE','HONEYWELL   WOEKEASY   13G GY NT A3/C  WE23-5313G-10','Honeywell',1,'A1','PAQUET',1,2.7,'Mabeo',25,0,0,0,''),
        ('ART-004','Outillage Manuel','PULVERISATEUR','MARQUE MESTO  18L','Mesto',2,'A1','UNITE',1,0.0,'Wurth France',19,0,0,0,''),
        ('ART-005','Fixations & Visserie','DOUILLE 13,5 POUR LIASON ELECTRIQUE AU RAIL','AR 66','',3,'A1','UNITE',1,0.0,'Cembre',63,0,0,0,''),
        ('ART-006','Lubrifiants & Produits','BOMBE DE PEINTURE JAUNE','MARQUE RUST- OLEUM   TOUT TYPE DE SUFACE (1CARTON = 6 BOMBES)','Rust-',3,'A1','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-007','Lubrifiants & Produits','BOMBE DE PEINTURE NOIR','MARQUE RUST- OLEUM   TOUT TYPE DE SUFACE (1CARTON = 6 BOMBES)','Rust-',3,'A1','BOITE',1,0.0,'',2,0,0,0,''),
        ('ART-008','Lubrifiants & Produits','BOMBE DE PEINTURE ROUGE','MARQUE RUST- OLEUM   TOUT TYPE DE SUFACE (1CARTON = 6 BOMBES)','Rust-',3,'A1','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-009','Protection Individuelle','LUNETTE TRONCONNAGE JAUNE','SPECTN12W BOLLE (1 BOITE AVEC 5 PAIRES)','Bolle',1,'A2','BOITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-010','Protection Individuelle','LUNETTE TRONCONNAGE BLEU/ JAUNE','BLAPSI BOLLE (1 BOITE AVEC 5 PAIRES) LUNETTE MASQUE SPECTRUM NR/JN PC INC AERE PLAT L','Bolle',1,'A2','BOITE',1,0.0,'Prolian',9,0,0,0,''),
        ('ART-011','Protection Individuelle','LUNETTE SECURITE BLANC','RUSHPPSI BOLLE','Bolle',1,'A2','BOITE',1,0.0,'Prolian',25,30,0,100,''),
        ('ART-012','Protection Individuelle','LUNETTE SECURITE SOLAIRE','RUSHPPSF BOLLE','Bolle',1,'A2','BOITE',1,0.0,'Prolian',11,0,0,0,''),
        ('ART-013','Protection Individuelle','GANTS ANTI-COUPURE','HONEYWELL   WOEKEASY   13G GY NT A3/C  WE23-5313G-9','Honeywell',1,'A1','UNITE',1,2.7,'',21,0,0,0,''),
        ('ART-014','Protection Individuelle','GANTS L ORANGE / NOIR JETABLE','899470122','',1,'A2','UNITE',1,0.0,'Wurth France',4,0,0,0,''),
        ('ART-015','Outillage Manuel','PULVERISATEUR','MARQUE XHANDER  5L','Xhander',2,'A2','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-016','Nettoyage & Hygiène','CHIFFONS','','',2,'A2','SAC',1,0.0,'',4,0,0,0,''),
        ('ART-017','Nettoyage & Hygiène','NETTOYANT FREINS','REF : 0890 108 7','',2,'A2','UNITE',1,0.0,'',38,0,0,0,''),
        ('ART-018','Nettoyage & Hygiène','SAC POUBELLE NOIR 100L','','',2,'A2','ROULEAU',1,0.0,'',14,0,0,0,''),
        ('ART-019','Nettoyage & Hygiène','SAC POUBELLE TRANSPARENT 110L','','',2,'A2','ROULEAU',1,0.0,'',2,0,0,0,''),
        ('ART-020','Conditionnement & Rangement','FILM TRANSPARENT','','',2,'A2','ROULEAU',1,0.0,'',5,0,0,0,''),
        ('ART-021','Outillage Manuel','Pompe de transvasement à levier manuel','REF : 891621','',2,'A2','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-022','Nettoyage & Hygiène','CHIFFON ABSORBANT MULTI USAGE','REF : 0899 700 450','',2,'A2','PAQUET',1,0.0,'Wurth France',7,0,0,0,''),
        ('ART-023','Nettoyage & Hygiène','SAC A GRAVAT','REF : 0899 910 911','',2,'A2','UNITE',1,0.0,'Wurth France',500,0,0,0,''),
        ('ART-024','Fixations & Visserie','OLIVE','REF : KIT AR266D-16,5-12 ( 1 BOITE = 100)','',3,'A2','BOITE',1,8.57,'Cembre',12,5,0,5,''),
        ('ART-025','Fixations & Visserie','BOULON','M10X70   0057 91070   (1BOITE = 100 BOULONS)','',3,'A2','BOITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-026','Fixations & Visserie','VIS BTR','20X140   CLE 17','',3,'A2','UNITE',1,0.0,'',10,0,0,0,''),
        ('ART-027','Fixations & Visserie','VIS BTR','M16X2,2','',3,'A2','UNITE',1,0.0,'',16,0,0,0,''),
        ('ART-028','Outillage Ferroviaire','Couronne de forage rapide SP-H','Couronne B 30/430 SP-H speed #2216079','',3,'A2','UNITE',1,0.0,'Hilti France',16,0,0,0,''),
        ('ART-029','Fixations & Visserie','FRAISE 13,5','CY132','',3,'A2','UNITE',1,0.0,'Cembre',66,10,0,50,''),
        ('ART-030','Fixations & Visserie','FRAISE 23','TCT RAIL    RAPTR230/SCRWC23','',3,'A2','UNITE',1,0.0,'Doga',26,10,0,50,''),
        ('ART-031','Fixations & Visserie','ECROU','M10X150    J.LANFRANCO  CODE : ERM100150ZHST02','',3,'A2','BOITE',1,0.0,'',4,0,0,0,''),
        ('ART-032','Fixations & Visserie','ECROU ZINGUE','MARQUE BOSSARD  M10  (1 BOITE=100 UNITE)','Bossard',3,'A2','BOITE',1,0.0,'',12,0,0,0,''),
        ('ART-033','Fixations & Visserie','RONDELLE','M10 (1 BOITE= 100 UNITE) MARQUE INDEX   D902110','Index',3,'A2','BOITE',1,0.0,'',2,0,0,0,''),
        ('ART-034','Fixations & Visserie','BOULON','MARQUE NORM  M10X60','Norm',3,'A2','BOITE',1,0.0,'',9,0,0,0,''),
        ('ART-035','Fixations & Visserie','POINTE ACIER','8X18  5KG','',3,'A2','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-036','Fixations & Visserie','BOULON','0083 16 45    M16X45  (25PAR BOITE)','',3,'A2','BOITE',1,0.0,'Wurth France',4,0,0,0,''),
        ('ART-037','Fixations & Visserie','ECROU AUTOFREINES','0391 10   M10 ( 25 PAR BOITE)','',3,'A2','BOITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-038','Outillage Ferroviaire','Couronne de forage SPX-L','B47/320 SPX-L  2374765','',3,'A2','UNITE',1,0.0,'Hilti France',3,0,0,0,''),
        ('ART-039','Fixations & Visserie','VIS','6X60/37MM 17736060  (1BOITE = 100 UNITE)','',3,'A2','BOITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-040','Fixations & Visserie','VIS','5,5X60/24 TX25 (1 BOITE = 100)','',3,'A2','BOITE',1,0.0,'',5,0,0,0,''),
        ('ART-041','Outillage Ferroviaire','COURONNE FORAGE DIAMANT','CORE BIT BR 32/320 SPX-L   2159404','',3,'A2','UNITE',1,0.0,'Hilti France',2,0,0,0,''),
        ('ART-042','Équipements Spéciaux','MASTIQUE ACRYLIQUE','','',3,'A2','UNITE',1,0.0,'Prolian',10,0,0,0,''),
        ('ART-043','Abrasifs & Disques','DISQUE 230X3,2','MEULE TRONC DEPORT 230X3,2 A30S-BF42  AC/IN XHANDER  00573841','Xhander',2,'A2','BOITE',1,0.0,'Prolian',17,0,0,0,''),
        ('ART-044','Équipements Spéciaux','ESSUIE MAIN','','',2,'A2 + AU SOL','BOITE',1,0.0,'',3,0,0,0,''),
        ('ART-045','Protection Individuelle','CASQUE ANTI-BRUIT','HONEYWELL   VERISHIELD VS 100DH','Honeywell',1,'A3','UNITE',1,0.0,'Prolian',8,0,0,0,''),
        ('ART-046','Abrasifs & Disques','DISQUE DISQUEUSE FT33','150X2XX22,23 ACIER MARQUE RHODIUS (1 BOITE = 25 PCS)','Rhodius',1,'A3','BOITE',1,0.0,'',4,0,0,0,''),
        ('ART-047','Abrasifs & Disques','DISQUE','230X2,5X22,23 METAL MARQUE TYROLIT  (1BOITE =25PCS)','Tyrolit',1,'A3','BOITE',1,0.0,'',10,0,0,0,''),
        ('ART-048','Abrasifs & Disques','DISQUE DISQUEUSE','125X1,6X22,23 METAL MARQUE TYROLIT  (1BOITE =25PCS)','Tyrolit',1,'A3','BOITE',1,0.0,'',3,0,0,0,''),
        ('ART-049','Abrasifs & Disques','DISQUE A LAMELLE','125X22,23 METAL MARQUE TYROLIT  (1BOITE =10PCS)','Tyrolit',1,'A3','BOITE',1,0.0,'Prolian',4,1,0,5,''),
        ('ART-050','Abrasifs & Disques','DISQUE ACIER/ INOX','125X6,4X22,23 MARQUE OPSIAL   113309633 (1 BOITE = 10PCS)','Opsial',1,'A3','BOITE',1,0.0,'Prolian',10,5,0,5,''),
        ('ART-051','Mesure & Traçage','RUBAN A MESURER    DECAMETRE','0714 641 653 30 M','',1,'A3','BOITE',1,0.0,'Wurth France',3,0,0,0,''),
        ('ART-052','Équipements Spéciaux','LAMES DE SCIE METAL ET BOIS','4MM    32145  MARQUE ERKO (5 LAMES DS 1 PAQUETS)','Erko',1,'A3','PAQUET',1,0.0,'',5,0,0,0,''),
        ('ART-053','Équipements Spéciaux','ROULEAU DE PONCAGE','40X25 MM MARQUE RHODIUS  100M','Rhodius',1,'A3','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-054','Conditionnement & Rangement','ETIQUETTES SAC PRELEVEMENT','121315  1,000   120X57MM MARQUE APLI','Apli',1,'A3','BOITE',1,0.0,'RMS Ferroviaire',4,0,0,0,''),
        ('ART-055','Conditionnement & Rangement','SACS POUBELLE','110L MARQUE FLEXIGREEN (1 ROULEAU = 25 SACS)','Flexigreen',1,'A3','PAQUET',1,0.0,'',1,0,0,0,''),
        ('ART-056','Équipements Spéciaux','KIT ABSORBANT','REF : 0899 900 300','',2,'A3','UNITE',1,0.0,'Wurth France',12,5,0,10,''),
        ('ART-057','Abrasifs & Disques','DISQUE A TRONCONNER 360','UNE BOITE DE 10 DIQUES','',2,'A3','UNITE',1,0.0,'Prolian',64,0,0,0,''),
        ('ART-058','Abrasifs & Disques','DISQUE A TRONCONNER 360','UNE BOITE DE 10 DIQUES','',2,'A3','UNITE',1,0.0,'St Gobain',0,0,0,0,''),
        ('ART-059','Abrasifs & Disques','DISQUE 300','20 DISQUES DANS UNE BOITE  MARQUE PFERD','Pferd',2,'A3','BOITE',1,0.0,'Prolian',7,0,0,0,''),
        ('ART-060','Nettoyage & Hygiène','SOLVANT VERT - DETERGENT - DEGRAISSANT','5L MARQUE HALECO','Haleco',2,'A3','BIDON',1,0.0,'',2,0,0,0,''),
        ('ART-061','Nettoyage & Hygiène','NETTOYANT FREIN 5L','REF : 0890 108 715','',2,'A3','BIDON',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-062','Lubrifiants & Produits','HUILE FILANTE POUR CHAINE 5L','','',2,'A3','BIDON',1,0.0,'',2,0,0,0,''),
        ('ART-063','Lubrifiants & Produits','HUILE DE COUPE SOLUBLE NG  5L','REF : 0893 120 105','',2,'A3','BIDON',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-064','Lubrifiants & Produits','HUILE DE COUPE A DILUER AVEC DE L`EAU','MARQUE KF REF : LUB 21   5L','Kf',2,'A3','BIDON',1,0.0,'',11,0,0,0,''),
        ('ART-065','Vêtements de travail','COMBINAISON BLANCHE TAILLE LG','','',2,'A3','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-066','Équipements Spéciaux','TRACEUR DE CHANTIER BLANC','0893 175 1','',3,'A3','BOITE',1,0.0,'Wurth France',14,5,0,20,''),
        ('ART-067','Équipements Spéciaux','TRACEUR DE CHANTIER ROUGE','0892 175 3','',3,'A3','BOITE',1,0.0,'Wurth France',14,5,0,20,''),
        ('ART-068','Équipements Spéciaux','TRACEUR DE CHANTIER JAUNE','0892 175 5','',3,'A3','BOITE',1,0.0,'Wurth France',12,5,0,20,''),
        ('ART-069','Équipements Spéciaux','TRACEUR DE CHANTIER BLEU','0892 175 2','',3,'A3','BOITE',1,0.0,'Wurth France',12,5,0,20,''),
        ('ART-070','Équipements Spéciaux','TRUELLE A JOINTS - LANGUE DE CHAT','','',1,'A4','UNITE',1,0.0,'',9,5,0,10,''),
        ('ART-071','Outillage Manuel','MARTEAU','MARQUE EXPERT 40 MM 1020G','Expert',1,'A4','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-072','Outillage Manuel','PINCE A FEUILLARD','','',1,'A4','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-073','Équipements Spéciaux','TETE PRISE ELECTIQUE','MARQUE LEGRAND','Legrand',1,'A4','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-074','Fixations & Visserie','CLE A BOULON D`ECLISSE 23','MECARAIL161 0380C   2022 3005','',1,'A4','UNITE',1,0.0,'Mecarail',4,0,0,0,''),
        ('ART-075','Protection Individuelle','LUNETTES DIVERS','CHALUMAGE OPSIAL  ET SECURITE BOLLE','Bolle',1,'A4','UNITE',1,0.0,'',37,0,0,0,''),
        ('ART-076','Équipements Spéciaux','TALOCHE DE MACON','MARQUE PV VINMER  270X180','Pv',1,'A4','UNITE',1,0.0,'',7,0,0,0,''),
        ('ART-077','Équipements Spéciaux','TRUELLE 22CM','','',1,'A4','UNITE',1,0.0,'Prolian',9,0,0,0,''),
        ('ART-078','Équipements Spéciaux','TRUELLE PETITE','0993943163 (6)      695971214','',1,'A4','UNITE',1,0.0,'Wurth France',7,0,0,0,''),
        ('ART-079','Équipements Spéciaux','BAC INOX (CUISINE)','MARQUE PROVITEQ','Proviteq',1,'A4','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-080','Équipements Spéciaux','BROSSE METALIQUE','5252','',1,'A4','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-081','Matériaux & Géotextiles','SABLE ABSORBANT  20L','REF : 0890 61','',2,'A4','UNITE',1,0.0,'Wurth France',15,0,0,0,''),
        ('ART-082','Lubrifiants & Produits','GRAISSE MULTIFONCTIONNELE','BERRULUB ECO SUPER 2','',2,'A4','UNITE',1,0.0,'Bechem',1,0,0,0,''),
        ('ART-083','Lubrifiants & Produits','HUILE DE COUPE 5L','MARQUE KF REF : 6540 LUB COUP II','Kf',2,'A4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-084','Équipements Spéciaux','GEL HYDRO ALCOOLIQUE','MARQUE  GARCIN BACTINYL REF : BACTIMAINS GHA','Garcin',2,'A4','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-085','Outillage Ferroviaire','Mèche de forage métrique TE-CX (SDS Plus)','TE-CX 10/17  MP32    2022052','',3,'A4','BOITE',1,0.0,'Hilti France',30,0,0,0,''),
        ('ART-086','Outillage Ferroviaire','Couronne de forage SPX-L','BR-F 30/320 SPX-L     2374741','',3,'A4','BOITE',1,0.0,'Hilti France',14,0,0,0,''),
        ('ART-087','Outillage Ferroviaire','Couronne de forage SPX-L','BR-F 28/320 SPX-L     2374740','',3,'A4','BOITE',1,0.0,'Hilti France',5,0,0,0,''),
        ('ART-088','Équipements Spéciaux','MASTIC ET COLLE','MARQUE SIKA PRO-11 FC','Sika',3,'A4','UNITE',1,0.0,'',28,0,0,0,''),
        ('ART-089','Fixations & Visserie','BOULON','0057 910 60  M10X60','',3,'A4','BOITE',1,0.0,'Wurth France',11,0,0,0,''),
        ('ART-090','Équipements Spéciaux','PROTECTION GENOUX','0 7835 010 MARQUE CARPENTIER','Carpentier',1,'A5','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-091','Équipements Spéciaux','Résine époxy HIT-RE 500 V4','1 CARTON = 20','',1,'A5','BOITE',1,0.0,'Hilti France',5,5,0,5,''),
        ('ART-092','Équipements Spéciaux','CREME LAVANTE 4L','MARQUE ARMA','Arma',1,'A5','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-093','Éclairage & Électricité','BATTERIE','M18 FB8 MARQUE MILWAUKEE  4932 4921 31','Milwaukee',1,'AR 1','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-094','Équipements Spéciaux','AMPOULE','MARQUE OSRAM   60W 230 V','Osram',1,'AR 1','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-095','Équipements Spéciaux','CADENAS   A CODE','MARQUE ABUS REF : 145/40 TITANIUM LT  NIVEAU DE SECURITE 4','Abus',1,'AR 1','UNITE',1,0.0,'Prolian',1,0,0,0,''),
        ('ART-096','Équipements Spéciaux','CADENAS A CODE','MARQUE ABUS  REF : NAUTIC CODE 180 NIVEAU DE SECURITE 5','Abus',1,'AR 1','UNITE',1,0.0,'Prolian',4,0,0,0,''),
        ('ART-097','Équipements Spéciaux','SCOTCH GRIS','','',1,'AR 2','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-098','Fixations & Visserie','COFFRET TOURNEVIS','PARTIELLEMENT REMPLIE','',1,'AR 2','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-099','Équipements Spéciaux','Ecouvillon métallique rond','HIT-RB 18 #336551','',1,'AR 3','UNITE',1,0.0,'Hilti France',4,0,0,0,''),
        ('ART-100','Équipements Spéciaux','Ecouvillon métallique rond','HIT-RB 16 #336550','',1,'AR 3','UNITE',1,0.0,'Hilti France',1,0,0,0,''),
        ('ART-101','Équipements Spéciaux','Ecouvillon métallique rond','HIT-RB 14 #336549','',1,'AR 3','UNITE',1,0.0,'Hilti France',5,0,0,0,''),
        ('ART-102','Équipements Spéciaux','Ecouvillon métallique rond','HIT-RB 12  #336548','',1,'AR 3','UNITE',1,0.0,'Hilti France',3,0,0,0,''),
        ('ART-103','Équipements Spéciaux','BRIDE THERMIQUE','6001994   TH034','',1,'AR 3','UNITE',1,0.0,'Cembre',5,0,0,0,''),
        ('ART-104','Outillage Ferroviaire','PERCAGE RAIL','APED135/165','',1,'AR 3','UNITE',1,0.0,'Cembre',4,0,0,0,''),
        ('ART-105','Fixations & Visserie','POINTEAUX','PP1 6001131 PUNTA PILOTA','',1,'AR 3','UNITE',1,0.0,'Cembre',20,0,0,0,''),
        ('ART-106','Fixations & Visserie','POINTEAUX','P100068','',1,'AR 3','UNITE',1,0.0,'Cembre',1,0,0,0,''),
        ('ART-107','Fixations & Visserie','POINTEAUX','PPL2','',1,'AR 3','UNITE',1,0.0,'Cembre',3,0,0,0,''),
        ('ART-108','Fixations & Visserie','POINTEAUX','PPL1','',1,'AR 3','UNITE',1,0.0,'Cembre',2,0,0,0,''),
        ('ART-109','Outillage Manuel','CLE A ERGO','','',1,'AR 3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-110','Fixations & Visserie','TOURNEVIS','PRECISIONS/DIVERS','',1,'AR 3','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-111','Mesure & Traçage','REGLES','20CM MARQUE SAM  781-2','Sam',1,'AR 4','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-112','Mesure & Traçage','REGLES','15 CM','',1,'AR 4','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-113','Équipements Spéciaux','CUTTER A BEC DE PERROQUET','SECUMAX 350 NO 35001 MARQUE MARTOR','Martor',1,'AR 4','UNITE',1,0.0,'Prolian',10,0,0,0,''),
        ('ART-114','Équipements Spéciaux','LAME CUTTER','SECUMAX BLADE NO 3550 MARQUE MARTOR','Martor',1,'AR 4','UNITE',1,0.0,'Prolian',10,0,0,0,''),
        ('ART-115','Équipements Spéciaux','LAME CUTTER','0715 66 02','',1,'AR 5','BOITE',1,0.0,'Wurth France',9,0,0,0,''),
        ('ART-116','Équipements Spéciaux','GABARIT DE PERSAGE  1/2','MRF CODE : 2872102','',1,'AR 5','UNITE',1,0.0,'Cembre',2,0,0,0,''),
        ('ART-117','Équipements Spéciaux','LAME CUTTER','0715 66 053','',1,'AR 5','BOITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-118','Équipements Spéciaux','LAME DE SCIE','BI-METAL 300MM (12`) 24T SAFE FLEX MARQUE STARRETT','Starrett',1,'AR 5','UNITE',1,0.0,'',7,0,0,0,''),
        ('ART-119','Équipements Spéciaux','CROCHET DE SECURITE','EN FORME DE M OU W','',1,'AR 5','UNITE',1,0.0,'',10,0,0,0,''),
        ('ART-120','Mesure & Traçage','Jauge de précision','N° 071351 42','',1,'AR 5','UNITE',1,0.0,'Wurth France',5,0,0,0,''),
        ('ART-121','Outillage Ferroviaire','Thermomètre à rail','310.014','',1,'AR 5','UNITE',1,0.0,'Mecarail',13,0,0,0,''),
        ('ART-122','Équipements Spéciaux','GOUPILLE FENDU','','',1,'AR 5','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-123','Équipements Spéciaux','extrudeurs','OG10.5','',1,'AR 5','UNITE',1,0.0,'Cembre',38,0,0,0,''),
        ('ART-124','Équipements Spéciaux','MARQUEUR BLANC','967910303','',1,'AR 5','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-125','Équipements Spéciaux','CUTTER','FACOM','Facom',1,'AR 5','UNITE',1,0.0,'Wurth France',4,0,0,0,''),
        ('ART-126','Fixations & Visserie','DOUILLE 23','N00087','',1,'AR 6','UNITE',1,0.0,'Geismar',1,0,0,0,''),
        ('ART-127','Fixations & Visserie','DOUILLE 30','FACOM','Facom',1,'AR 6','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-128','Fixations & Visserie','DOUILLE 16','XANDER','',1,'AR 6','UNITE',1,0.0,'Prolian',3,0,0,0,''),
        ('ART-129','Fixations & Visserie','DOUILLE 13','2070389 SI-S 1/2`-13L','',1,'AR 6','UNITE',1,0.0,'Hilti France',4,0,0,0,''),
        ('ART-130','Fixations & Visserie','DOUILLE 2','2076827 SI-S EXT 1/2`-2','',1,'AR 6','UNITE',1,0.0,'Hilti France',2,0,0,0,''),
        ('ART-131','Outillage Manuel','CLE PLATE 10','MARQUE EXPERT','Expert',1,'AR 6','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-132','Outillage Manuel','CLE PLATE 13','','',1,'AR 6','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-133','Outillage Manuel','CLE HEXAGONAL','61313005','',1,'AR 6','UNITE',1,0.0,'Wurth France',6,0,0,0,''),
        ('ART-134','Équipements Spéciaux','ELEMENT RADAR PEDAGOGIQUE','','',1,'AR 6','UNITE',1,0.0,'Prozon',1,0,0,0,''),
        ('ART-135','Équipements Spéciaux','BLOC ETALONNAGE','CEG 12,5K  N°140822-15','',1,'AR 6','UNITE',1,0.0,'Sofranel',1,0,0,0,''),
        ('ART-136','Équipements Spéciaux','BOBINE FILS','100M','',1,'AR 6','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-137','Équipements Spéciaux','FILLIERE DE FILTAGE','CODE : 0110000000010 FILLIERE M22X250 DIAM : 50,8MM','',1,'AR 6','UNITE',1,0.0,'Mecarail',7,0,0,0,''),
        ('ART-138','Fixations & Visserie','DOUILLE 17','SI-S  1/2`17S 2070374','',1,'AR 7','UNITE',1,0.0,'Hilti France',4,0,0,0,''),
        ('ART-139','Fixations & Visserie','DOUILLE 17','7141314','',1,'AR 7','UNITE',1,0.0,'Wurth France',22,0,0,0,''),
        ('ART-140','Fixations & Visserie','DOUILLE 17','MARQUE FACOM 1/2` 6PT   NS.17A','Facom',1,'AR 7','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-141','Fixations & Visserie','DOUILLE 41','','',1,'AR 7','UNITE',1,0.0,'Geismar',16,0,0,0,''),
        ('ART-142','Fixations & Visserie','DOUILLE 23','2020 2383     120-023  C23','',1,'AR 7','UNITE',1,0.0,'Mecarail',8,0,0,0,''),
        ('ART-143','Équipements Spéciaux','BROCHE DE MACON','MARQUE MOB REF : 7311','Mob',1,'AR 7','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-144','Outillage Manuel','JOINT CLE A CHOC','','',1,'AR 8','UNITE',1,0.0,'',100,0,0,0,''),
        ('ART-145','Équipements Spéciaux','FIXATION A BILLE','STE880E','',1,'AR 8','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-146','Fixations & Visserie','POINTEAUX 3','MARQUE SAM    7C29A','Sam',1,'AR 8','UNITE',1,0.0,'',10,0,0,0,''),
        ('ART-147','Outillage Manuel','TETE CLE A CHOC','014 10 004','',1,'AR 8','UNITE',1,0.0,'Mecarail',2,0,0,0,''),
        ('ART-148','Fixations & Visserie','DOUILLE 38','N00098','',1,'AR 9','UNITE',1,0.0,'Geismar',2,0,0,0,''),
        ('ART-149','Fixations & Visserie','DOUILLE 38','122.038-H38MM','',1,'AR 9','UNITE',1,0.0,'Mecarail',4,0,0,0,''),
        ('ART-150','Fixations & Visserie','DOUILLE 38','MARQUE FACOM   1`6PT     NM,38A','Facom',1,'AR 9','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-151','Fixations & Visserie','DOUILLE 38','XANDER 3/4`  CODE : 69144799','',1,'AR 9','UNITE',1,0.0,'Prolian',13,0,0,0,''),
        ('ART-152','Outillage Ferroviaire','BROSSE DE FORAGE','','',1,'AR 9','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-153','Équipements Spéciaux','FORET 18 MM','1D9','',1,'AR 9','UNITE',1,0.0,'Geismar',4,0,0,0,''),
        ('ART-154','Équipements Spéciaux','JETON NON NUMEROTE','COULEUR OR','',1,'AR 9','UNITE',1,0.0,'Manutan',100,0,0,0,''),
        ('ART-155','Mesure & Traçage','THERMOMETRE CIRCULAIRE AIMANTE','','',1,'AR 9','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-156','Mesure & Traçage','JAUGE ECARTEMENT DES JOINTS','C5.4.001','',1,'AR4','UNITE',1,0.0,'Mecarail',4,0,0,0,''),
        ('ART-157','Équipements Spéciaux','SOUPAPE DE PURGE','6001397 VALVOLA SFIATO COMPL LD-1P/2E   POS : 1A0058','',1,'AR4','UNITE',1,0.0,'Cembre',13,0,0,0,''),
        ('ART-158','Outillage Ferroviaire','CALIBRES DE POSITIONNEMENT DE LA PERFORATRICE DE RAIL','MPAF -U33','',1,'AR4','UNITE',1,0.0,'Cembre',4,0,0,0,''),
        ('ART-159','Outillage Ferroviaire','CALIBRES DE POSITIONNEMENT DE LA PERFORATRICE DE RAIL','MPAF -U50','',1,'AR4','UNITE',1,0.0,'Cembre',4,0,0,0,''),
        ('ART-160','Outillage Ferroviaire','CALIBRES DE POSITIONNEMENT DE LA PERFORATRICE DE RAIL','MPAF -UIC60','',1,'AR4','UNITE',1,0.0,'Cembre',4,0,0,0,''),
        ('ART-161','Outillage Manuel','GOUPILLE CLE A CHOC','','',1,'AR4','UNITE',1,0.0,'',83,0,0,0,''),
        ('ART-162','Équipements Spéciaux','CRAYON CHANTIER','','',1,'ARMOIR','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-163','Équipements Spéciaux','ZEBRA','','',1,'ARMOIR','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-164','Outillage Manuel','CLE ALLEN','','',1,'ARMOIR','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-165','Outillage Manuel','JOINT METAL CLE A CHOC','','',1,'ARMOIR','UNITE',1,0.0,'',83,0,0,0,''),
        ('ART-166','Équipements Spéciaux','SI-S','EXT 1/2`  2`','',1,'ARMOIR','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-167','Équipements Spéciaux','SI-S','EXT 1/2`  17`','',1,'ARMOIR','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-168','Équipements Spéciaux','SI-S','EXT 1/2`  13`','',1,'ARMOIR','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-169','Équipements Spéciaux','MDAF','U33','',1,'ARMOIR','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-170','Équipements Spéciaux','FEELE GAUGES','0,10-0,50','',1,'ARMOIR','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-171','Équipements Spéciaux','SOUDEUR','','',1,'ARMOIR','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-172','Équipements Spéciaux','CADENAS LIOSE','','',1,'ARMOIR','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-173','Fixations & Visserie','FORET OILOTE POUR 2 FRAISE','6001131','',1,'ARMOIR','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-174','Équipements Spéciaux','JOINT PLASTIQUE','','',1,'ARMOIR','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-175','Équipements Spéciaux','TAMISEUSE ELECTRON MAGNETIQUE','QUENTIN.L','',1,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-176','Outillage Électroportatif','TRONCONNEUSE A RAIL','AVEC GUIDE REF :  MTZ MODELE 1 : 350AS/400 AS','',1,'AU SOL','UNITE',1,0.0,'Geismar',3,0,0,0,''),
        ('ART-177','Équipements Spéciaux','PASSAGE CABLE','','',1,'AU SOL','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-178','Mesure & Traçage','REGLE A DEVERS','CODE ARTICLE : H80822','',1,'AU SOL','UNITE',1,0.0,'Geismar',0,0,0,0,''),
        ('ART-179','Conditionnement & Rangement','BIG BAG','90X90X90','',2,'AU SOL','UNITE',1,0.0,'123 Big Bag',10,0,0,0,''),
        ('ART-180','Nettoyage & Hygiène','NETTOYANT POUR SOL DE GARAGE ET INDUSTRIEL','MARQUE NATURA SOL 20L','Natura',2,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-181','Équipements Spéciaux','LIQUIDE DE REFROIDISSEMENT','LR21 CODE 8172308','',2,'AU SOL','UNITE',1,0.0,'Cembre',0,0,0,0,''),
        ('ART-182','Lubrifiants & Produits','HUILE  15W40','RUBIA WORKS 20L','',2,'AU SOL','UNITE',1,0.0,'Total Energie',1,0,0,0,''),
        ('ART-183','Équipements Spéciaux','APPAREIL DE PASSAGE A NIVEAU','MODEL : 01122300','',2,'AU SOL','UNITE',1,0.0,'Strail',2,0,0,0,''),
        ('ART-184','Équipements Spéciaux','POUBELLE DE BUREAU','','',2,'AU SOL','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-185','Équipements Spéciaux','CROIX','','',2,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-186','Équipements Spéciaux','FOURREAUX TRANSPARENT','','',2,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-187','Équipements Spéciaux','CABLE ELECTRIQUE','','',2,'AU SOL','ROULEAU',1,0.0,'',1,0,0,0,''),
        ('ART-188','Équipements Spéciaux','PANNEAUX STOP','','',2,'AU SOL','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-189','Nettoyage & Hygiène','NETTOYANT FREIN 20 L','REF : 0890 108 720','',2,'AU SOL','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-190','Lubrifiants & Produits','LUBRIFIANT MULTIFONCTION','MARQUE SIPROTEC LUBRIFIANT REF : STRALUB 30L','Siprotec',2,'AU SOL','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-191','Éclairage & Électricité','SOUFFLEUR A BATTERIE','MARQUE MILWAUKEE','Milwaukee',2,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-192','Équipements Spéciaux','DEGRIPPANT  20L','REF : 0890 3001','',2,'AU SOL','UNITE',1,0.0,'Wurth France',10,0,0,0,''),
        ('ART-193','Équipements Spéciaux','EAU CRISTALINE 50CL','','',2,'AU SOL','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-194','Conditionnement & Rangement','BIG BAG','90X90X110','',2,'AU SOL','UNITE',1,0.0,'Prolian',85,0,0,0,''),
        ('ART-195','Équipements Spéciaux','BARRIERES EXTENSIBLE 100100','PROCITY','',1,'AU SOL','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-196','Équipements Spéciaux','ENROULEUR A AIR COMPRIME','MARQUE PRESVOST 15M','Presvost',1,'B1','UNITE',1,0.0,'',1,1,0,1,''),
        ('ART-197','Équipements Spéciaux','ENROULEUR ELECTRIQUE 40M','MARQUE OPSIAL','Opsial',1,'B1','UNITE',1,0.0,'',1,1,0,2,''),
        ('ART-198','Équipements Spéciaux','CHAUFFAGE PORTABLE 3KW','','',1,'B1','UNITE',1,0.0,'Prolian',1,1,0,1,''),
        ('ART-199','Équipements Spéciaux','TAMIS 31,50','MARQUE PROVITEQ TOLE PERFOREE','Proviteq',1,'B1','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-200','Abrasifs & Disques','Meuleuse d`angle électrique 230 mm EWS 24-230-T','','',1,'B1','UNITE',1,0.0,'Wurth France',1,1,0,1,''),
        ('ART-201','Éclairage & Électricité','BATTERIE RECHARGEABLE M18 FB8','MARQUE MILWAUKEE','Milwaukee',1,'B1','UNITE',1,0.0,'',4,1,0,4,''),
        ('ART-202','Équipements Spéciaux','Mélangeur HIT-RE-M #337111','','',1,'B1','UNITE',1,0.0,'Hilti France',52,50,0,100,''),
        ('ART-203','Protection Individuelle','GANTS CUIRE BLANC T11','1 PAQUET = 10 PAIRES','',1,'B2','PAQUET',1,0.0,'Wurth France',19,0,0,0,''),
        ('ART-204','Équipements Spéciaux','PORTE AFFICHE','KRABG25B1','',1,'B3','UNITE',1,0.0,'Prozon',10,0,0,0,''),
        ('ART-205','Protection Individuelle','BOUCHONS D`OREILLE','1 PAQUET = 4 PAIRES  0899 300 338','',1,'B3','PAQUET',1,0.0,'Wurth France',98,10,0,20,''),
        ('ART-206','Équipements Spéciaux','CHAUFFRETTES A MAIN','','',1,'B3','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-207','Équipements Spéciaux','ENSEMBRE DE PLUIE XL','MARQUE OPSIAL','Opsial',1,'B3','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-208','Mesure & Traçage','ODOMETRE','068594979  ROUE 320 MM XHANDER','Xhander',1,'B3','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-209','Équipements Spéciaux','SPATULE','','',1,'B4','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-210','Équipements Spéciaux','BROSSE METALIQUE','68,920,671','',1,'B4','UNITE',1,0.0,'Prolian',21,0,0,0,''),
        ('ART-211','Équipements Spéciaux','CHAINE 25M','6MM CODE 050 407','',1,'B4','BOITE',1,0.0,'Prolian',1,0,0,0,''),
        ('ART-212','Outillage Manuel','Pompe soufflante #60579','AUSBLASPUMPE','',1,'B4','UNITE',1,0.0,'Hilti France',4,0,0,0,''),
        ('ART-213','Équipements Spéciaux','Porte-cartouche HIT-CR 500 #2007059','','',1,'B4','UNITE',1,0.0,'Hilti France',4,0,0,0,''),
        ('ART-214','Vêtements de travail','COMBINAISON DE PROTECTION LG','ORANGE','',1,'B4','UNITE',1,0.0,'Dupont',7,10,0,0,''),
        ('ART-215','Vêtements de travail','COMBINAISON DE PROTECTION MD','ORANGE','',1,'B4','UNITE',1,0.0,'Dupont',12,10,0,0,''),
        ('ART-216','Vêtements de travail','COMBINAISON DE PROTECTION XL','ORANGE','',1,'B4','UNITE',1,0.0,'Dupont',7,10,0,0,''),
        ('ART-217','Vêtements de travail','COMBINAISON DE PROTECTION LG','BLANCHE','',1,'B5','UNITE',1,0.0,'Dupont',23,0,0,0,''),
        ('ART-218','Outillage Électroportatif','VISSEUSE M18FDD3-502X','MARQUE MILWAUKEE','Milwaukee',1,'C1','UNITE',1,0.0,'',1,1,0,1,''),
        ('ART-219','Fixations & Visserie','BOULONNEUSE FIW2F12-0X','MARQUE MILWAUKEE','Milwaukee',1,'C1','UNITE',1,0.0,'',3,1,0,2,''),
        ('ART-220','Abrasifs & Disques','Meuleuse d`angle M18 FLAG230XPDB-121C','MARQUE MILWAUKEE','Milwaukee',1,'C1','UNITE',1,0.0,'',1,1,0,2,''),
        ('ART-221','Outillage Électroportatif','VISSEUSE MAKITA  DDF453','MAKITA','Makita',1,'C1','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-222','Outillage Manuel','CLE A CHOC M18 ONFEHIWF1-802X','MARQUE MILWAUKEE','Milwaukee',1,'C1','UNITE',1,0.0,'',1,2,0,2,''),
        ('ART-223','Équipements Spéciaux','Perforateur TE 30-ATC/AVR','MARQUE HILTI','Hilti',1,'C1','UNITE',1,0.0,'Hilti France',4,1,0,2,''),
        ('ART-224','Outillage Manuel','Pince d`injection sans fil pour scellement chimique HDE 500-22','MARQUE HILTI','Hilti',1,'C1','UNITE',1,0.0,'Hilti France',2,1,0,1,''),
        ('ART-225','Protection Individuelle','Gants de Soudeur W-110 EN 388, 420 et 12477A - taille 10','53 50 050 110','',1,'C2','UNITE',1,0.0,'Wurth France',14,10,0,30,''),
        ('ART-226','Protection Individuelle','Gants de Soudeur W-110 EN 388, 420 et 12477A - taille 9','5350050109','',1,'C2','UNITE',1,0.0,'Wurth France',5,10,0,30,''),
        ('ART-227','Protection Individuelle','Gant soudeur BLUE WELDER','Code P : P702LYQ  Réf. PROLIANS : 66581276','Prolian',1,'C2','PAIRE',1,0.0,'Prolian',11,10,0,30,''),
        ('ART-228','Équipements Spéciaux','TABLIER SOUDEUR','','',1,'C2','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-229','Protection Individuelle','GANTS PROTECTION CHIMIQUE','','',1,'C2','PAIRE',1,0.0,'',2,0,0,0,''),
        ('ART-230','Éclairage & Électricité','VISILITE LED LUMINEUX','MARQUE JSP      AHV 860 000 800','Jsp',1,'C2','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-231','Éclairage & Électricité','LAMPE FRONTAL (XLANDER)','','',1,'C2','UNITE',1,0.0,'Prolian',4,0,0,0,''),
        ('ART-232','Éclairage & Électricité','LAMPE FRONTALE (LEDLENSER)','LEDLENSER  H7R CORE','',1,'C2','UNITE',1,0.0,'Manutan',23,20,0,50,''),
        ('ART-233','Éclairage & Électricité','CLIPS CROCH LAMPE (4)','E04350','',1,'C2','SAC',1,0.0,'',40,20,0,50,''),
        ('ART-234','Protection Individuelle','GUETRE DE TRONCONNAGES','GUETRE SOUDEUR CUIR RHT ARMATURE RESSORT H36/Paire   TSV00008','',1,'C3','PAIRE',1,116.0,'Pandrol',11,4,0,10,''),
        ('ART-235','Éclairage & Électricité','PILE LR06','PROCEL','',1,'C3','BOITE',1,0.0,'',6,0,0,0,''),
        ('ART-236','Éclairage & Électricité','PILE AAA LR3','MARQUE VARTA','Varta',1,'C3','UNITE',1,0.0,'Prolian',360,0,0,0,''),
        ('ART-237','Éclairage & Électricité','PILE POUR LANTERNE ELECTRIQUE PORTATIVE GLR20','6LR20      MARQUE CECASA   SNCF TYPE 6LR20   SYMBOLE :0.816.8652','Cecasa',1,'C3','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-238','Éclairage & Électricité','PILES  POUR LANTERNE DE QUEUE DE TRAIN','PCFF - 200   MARQUE MFI   SYMBOLE : 0.816.8651','Mfi',1,'C3','UNITE',1,0.0,'ETF Beauchamp',2,5,0,10,''),
        ('ART-239','Équipements Spéciaux','AMPOULE HALOGENR 52 V 0,85 A','OHG900l','',1,'C3','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-240','Équipements Spéciaux','AMPOULE OSRAM','H21W 24V','',1,'C3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-241','Outillage Électroportatif','PROJECTEUR LED MAGNETIQUE','LW.MARQUE LED WORK  REF : SYDNEY  LWK0033','Led',1,'C3','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-242','Outillage Électroportatif','PROJECTEUR BATTERIE 6V','MARQUE VARTA WORK LIGHT BL 40','Varta',1,'C3','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-243','Éclairage & Électricité','BATTERIE 6V','MARQUE VARTA  435 / 4LR25-2','Varta',1,'C3','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-244','Équipements Spéciaux','CONTACTEUR','MARQUE LEGRAND 4.125.45','Legrand',1,'C3','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-245','Outillage Manuel','ELINGUE','3M 4T MARQUE WURTH : 0713 50 411','Wurth',1,'C3','UNITE',1,0.0,'Wurth France',3,2,0,4,''),
        ('ART-246','Outillage Manuel','ELINGUE','2M 3T MARQUE WURTH  0713 50 34','Wurth',1,'C3','UNITE',1,0.0,'Wurth France',4,2,0,4,''),
        ('ART-247','Outillage Manuel','ELINGUE','4M 2T MARQUE WURTH 0713 50 28','Wurth',1,'C3','UNITE',1,0.0,'Wurth France',11,2,0,4,''),
        ('ART-248','Équipements Spéciaux','SCIE A METAUX','MARQUE FACOM','Facom',1,'C4','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-249','Outillage Manuel','MARTEAU FACOM','MARQUE FACOM  200C,30   B  755391','Facom',1,'C4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-250','Lubrifiants & Produits','FLEXIBLE GRAISSE M10 X 100','300 MM  REF : 07400300 MARQUE ALGI','Algi',1,'C4','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-251','Équipements Spéciaux','TENAILLE  220 MM','MARQUE OPSIAL REF : OPS38325698','Opsial',1,'C4','UNITE',1,0.0,'Prolian',6,2,0,5,''),
        ('ART-252','Équipements Spéciaux','BURIN MECANICIEN','MARQUE WURTH : 0714 630 05','Wurth',1,'C4','UNITE',1,0.0,'Wurth France',6,2,0,5,''),
        ('ART-253','Outillage Manuel','CLE 41 PLATE','MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-254','Outillage Manuel','CLE 36 PLATE','MARQUE SAM ET WURTH','Sam',1,'C4','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-255','Outillage Manuel','CLE 32 PLATE','MARQUE SAM ET WURTH','Sam',1,'C4','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-256','Outillage Manuel','CLE 30 PLATE','MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-257','Outillage Manuel','CLE 28 PLATE','MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-258','Outillage Manuel','CLE 26 PLATE','MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-259','Outillage Manuel','CLE 24 PLATE','MARQUE OPSIAL','Opsial',1,'C4','UNITE',1,0.0,'Prolian',1,0,0,0,''),
        ('ART-260','Outillage Manuel','CLE 22 PLATE','MARQUE SAM ET WURTH','Sam',1,'C4','UNITE',1,0.0,'Wurth France',11,0,0,0,''),
        ('ART-261','Outillage Manuel','CLE 21 PLATE','MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-262','Outillage Manuel','CLE 19 PLAT A','MARQUE WURTH','Wurth',1,'C4','UNITE',1,0.0,'Wurth France',0,5,0,10,''),
        ('ART-263','Outillage Manuel','CLE MIXTE A CLIQUET 17 MM','69142788','',1,'','UNITE',1,0.0,'Prolian',10,0,0,0,''),
        ('ART-264','Outillage Manuel','CLE 17 PLATE','MARQUE FACOM','Facom',1,'C4','UNITE',1,0.0,'',6,5,0,10,''),
        ('ART-265','Fixations & Visserie','TOURNEVISE PLAT 1X 5,5','MARQUE WURTH','Wurth',1,'C4','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-266','Outillage Manuel','CLE 4 ALAINE','61311644','',1,'C4','UNITE',1,0.0,'Wurth France',9,0,0,0,''),
        ('ART-267','Outillage Manuel','CLE 13','MARQUE FACOM','Facom',1,'C4','UNITE',1,0.0,'',11,0,0,0,''),
        ('ART-268','Mesure & Traçage','NIVEAU POUR REGLE A DEVERS','','',1,'C4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-269','Outillage Manuel','CLE A MOLETTE','15` MARQUE WURTH','Wurth',1,'C4','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-270','Outillage Manuel','CLE A MOLETTE','250 MM MARQUE SAM','Sam',1,'C4','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-271','Outillage Manuel','CLE A CLIQUET 1/2','MARQUE XANDER','Xander',1,'C4','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-272','Outillage Manuel','MASSETTE SANS REBOND','MARQUE FACOM  40MM','Facom',1,'C4','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-273','Équipements Spéciaux','SERINGUE','500ML MARQUE WURTH REF : 0695 081 92','Wurth',1,'C4','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-274','Outillage Manuel','PINCEAU D`ANGLE','40 24 15','',1,'C4','UNITE',1,0.0,'',15,0,0,0,''),
        ('ART-275','Équipements Spéciaux','GUIDE CHAINE','3003-000-5213 MARQUE STILL','Still',1,'C4','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-276','Équipements Spéciaux','GUIDE CHAINE','3003-000-9431 MARQUE STILL','Still',1,'C4','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-277','Équipements Spéciaux','KLAXON PNEUMATIQUE','','',1,'C5','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-278','Fixations & Visserie','DOUILLE 38','','',1,'C5','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-279','Fixations & Visserie','DOUILLE 36','','',1,'C5','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-280','Fixations & Visserie','DOUILLE 34','','',1,'C5','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-281','Fixations & Visserie','DOUILLE 23','','',1,'C5','UNITE',1,0.0,'',22,0,0,0,''),
        ('ART-282','Fixations & Visserie','DOUILLE 19','','',1,'C5','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-283','Outillage Électroportatif','MECHE   PERCEUSE','MELANGE DE DIFFERENTES TAILLE NON INSCRIT','',1,'C5','UNITE',1,0.0,'',30,0,0,0,''),
        ('ART-284','Gaz & Soudage','RACCORD GAZ G1-AD','10-25MM','',1,'C5','UNITE',1,0.0,'',18,0,0,0,''),
        ('ART-285','Gaz & Soudage','RACCORD GAZ G2 AC','35/10','',1,'C5','UNITE',1,0.0,'',35,0,0,0,''),
        ('ART-286','Gaz & Soudage','RACCORD GAZ ACETYLENE','M16  1,5 LH MARQUE AIR PRODUCT  REF : INTEGRA CYLINDER','Air',1,'C5','UNITE',1,0.0,'',17,0,0,0,''),
        ('ART-287','Gaz & Soudage','RACCORD GAZ PAIRE RARORMATIC','OXY GAZ  10X17','',1,'C5','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-288','Gaz & Soudage','COLLIER RACCORD GAZ','','',1,'C5','UNITE',1,0.0,'',98,0,0,0,''),
        ('ART-289','Équipements Spéciaux','CHAUFFE MAIN','','',1,'C5','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-290','Équipements Spéciaux','HARNAI (SECURITE)','MARQUE MILLER','Miller',1,'C5','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-291','Équipements Spéciaux','HARNAI (SECURITE) Longe drisse fourche - LDF 11','MAX 150 KG MARQUE TRACTEL','Tractel',1,'C5','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-292','Protection Individuelle','DEMI-MASQUE','MARQUE OPSIAL REF : P3 RD','Opsial',1,'D1','UNITE',1,0.0,'Prolian',13,20,0,50,''),
        ('ART-293','Équipements Spéciaux','FILTRE DE REMPLACEMENT','MARQUE OPSIAL REF : SPR316ODUA','Opsial',1,'D1','BOITE',1,0.0,'Prolian',8,5,0,20,''),
        ('ART-294','Équipements Spéciaux','JERRICAN METALIQUE 10L VERT','','',1,'D1','UNITE',1,0.0,'',2,2,0,5,''),
        ('ART-295','Protection Individuelle','MASQUE PRÊT A L`EMPLOI','MARQUE OPSIAL REF : ABEK1P3RD','Opsial',1,'D1','UNITE',1,0.0,'Prolian',7,10,0,20,''),
        ('ART-296','Protection Individuelle','MASQUE AIR FIT','JETABLE FFP3 MARQUE OPSIAL','Opsial',1,'D1','BOITE',1,0.0,'Prolian',25,0,0,0,''),
        ('ART-297','Équipements Spéciaux','BACHE DE SOUDURE ANTI-FEU','TOILE THETIS ANTI CHALEUR 200 X 200CM','',1,'D2','UNITE',1,105.0,'Prolian',7,4,0,8,''),
        ('ART-298','Équipements Spéciaux','Percuteur  REF HS-SC-3000','MARQUE HILTI','Hilti',1,'D2','UNITE',1,0.0,'Hilti France',8,6,0,10,''),
        ('ART-299','Mesure & Traçage','METRE (10M)','MARQUE STANLEY','Stanley',1,'D2','UNITE',1,0.0,'Prolian',11,5,0,10,''),
        ('ART-300','Mesure & Traçage','METRE (8M)','MARQUE OPSIAL','Opsial',1,'D2','UNITE',1,0.0,'',9,10,0,30,''),
        ('ART-301','Mesure & Traçage','METRE (8M)','MARQUE STANLEY','Stanley',1,'D2','UNITE',1,0.0,'Prolian',11,5,0,20,''),
        ('ART-302','Mesure & Traçage','METRE (5M)','','',1,'D2','UNITE',1,0.0,'Prolian',1,10,0,40,''),
        ('ART-303','Mesure & Traçage','METRE (3M)','MARQUE XANDER','Xander',1,'D2','UNITE',1,0.0,'Prolian',9,5,0,20,''),
        ('ART-304','Nettoyage & Hygiène','LINGETTE NETTOYANTE POUR LES MAINS','SAUT DE 72 LINGETTES MARQUE SCRUBS','Scrubs',1,'D2','UNITE',1,0.0,'Prolian',12,4,0,10,''),
        ('ART-305','Équipements Spéciaux','LINGETTE IMPREGNEES UNIVERSELLES','0893 936 70','',1,'D2','UNITE',1,0.0,'Wurth France',11,0,0,0,''),
        ('ART-306','Équipements Spéciaux','PAPIER BLANC FORMAT A3','','',1,'D3','UNITE',1,0.0,'Lyreco',6,0,0,0,''),
        ('ART-307','Éclairage & Électricité','BATTERIE CEMBRE LIHD 36V,8-0AH','RECHARGABLE CEMBRE','Cembre',1,'D3','UNITE',1,0.0,'Cembre',5,0,0,0,''),
        ('ART-308','Éclairage & Électricité','BATTERIE 14.4 VOLT LI-ION 2,6 AH CPC','MARQUE HILTI B144/2,6      9857536','Hilti',1,'D3','UNITE',1,0.0,'Hilti France',2,0,0,0,''),
        ('ART-309','Éclairage & Électricité','CHARGEUR  BATTERIE','MARQUE HILTI C4/36-90','Hilti',1,'D3','UNITE',1,0.0,'Hilti France',2,0,0,0,''),
        ('ART-310','Éclairage & Électricité','CHARGEUR BATTERIE','MARQUE HILTI C4/36-350','Hilti',1,'D3','UNITE',1,0.0,'Hilti France',2,0,0,0,''),
        ('ART-311','Éclairage & Électricité','CHARGEUR BATTERIE','MARQUE HILTI C4-22','Hilti',1,'D3','UNITE',1,0.0,'Hilti France',1,0,0,0,''),
        ('ART-312','Équipements Spéciaux','RALLONGE 10M AVEC 4 PRISES','','',1,'D3','UNITE',1,0.0,'Prolian',4,0,0,0,''),
        ('ART-313','Équipements Spéciaux','RUBALISE','','',1,'D3','ROULEAU',1,0.0,'',25,10,0,30,''),
        ('ART-314','Outillage Électroportatif','GABARIT DE PERCEUSE A RAIL CEMBRE','SPA /1 U60/U50','Cembre',1,'D3','UNITE',1,0.0,'Cembre',2,1,0,3,''),
        ('ART-315','Équipements Spéciaux','GABARIT DE PERSAGE 2/2','SPA-UIC60-U50-3','',1,'D3','UNITE',1,0.0,'Cembre',4,0,0,0,''),
        ('ART-316','Protection Individuelle','LUNETTES  DE PROTECTION A METTRE SUR CASQUE','EN166-EN 170 MARQUE JSP  REF : EVOSPEC CLEAR ANTIMIST N','Jsp',1,'D4','UNITE',1,0.0,'',26,0,0,0,''),
        ('ART-317','Équipements Spéciaux','PRESSE HYDRAULIQUE D`EXTRUSION','REF: HTEPF-EX SYMBOLE T.391.0269','',1,'D4','UNITE',1,0.0,'Cembre',3,1,0,1,''),
        ('ART-318','Équipements Spéciaux','RACCORDS  EXPRESSE CANNELE 19MM','P019 MARQUE BOUTTE','Boutte',1,'D4','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-319','Nettoyage & Hygiène','NETTOYANT LUBRIFIANT  SPECIAL CONTACT','MARQUE KF','Kf',1,'D4','UNITE',1,0.0,'Prolian',20,0,0,0,''),
        ('ART-320','Équipements Spéciaux','BALANCES','SIWABBP QUENTIN.L','',1,'D5','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-321','Abrasifs & Disques','BROSSE A TOILETTE','','',1,'D5','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-322','Équipements Spéciaux','SIKATOP 122 FR','BIDON','',4,'SUR PALETTE','UNITE',1,0.0,'',22,0,0,0,''),
        ('ART-323','Équipements Spéciaux','EAU CRISTALINE 50CL','','',1,'SUR PALETTE','UNITE',1,0.0,'Lyreco',29,0,0,0,''),
        ('ART-324','Équipements Spéciaux','SIKATOP 122 FR','SAC','',4,'SUR PALETTE','UNITE',1,0.0,'',17,0,0,0,''),
        ('ART-325','Équipements Spéciaux','4T','6 BIDONS DANS UN CARTON = 24 CARTON SUR UNE PALETTE','',2,'SUR PALETTE','BOITE',1,0.0,'Extruplast',35,25,0,0,''),
        ('ART-326','Équipements Spéciaux','2T','6 BIDONS DANS UN CARTON = 24 CARTON SUR UNE PALETTE','',2,'SUR PALETTE','BOITE',1,0.0,'Extruplast',55,25,0,0,''),
        ('ART-327','Fixations & Visserie','POINTEAUX ALPHABET','10 MM  MARQUE MOB REF : 7268100001','Mob',1,'TI 1','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-328','Outillage Manuel','CADENAS A CLE NOIR','SECURITE 4','',1,'TI 1','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-329','Abrasifs & Disques','DISQUE MAKITA 300X3,5 X20MM','','Makita',2,'A3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-330','Abrasifs & Disques','DISQUE 230X8.0X22,2','LONG LIFE  REF : 660 162 308','',1,'TI 2','UNITE',1,0.0,'Wurth France',12,0,0,0,''),
        ('ART-331','Outillage Manuel','BOITE A CLE','MARQUE : MASTER','',1,'TI 2','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-332','Équipements Spéciaux','BOITE OUTIL','Douilles de 1/2 pouce et 1/4 pouce Assortiment de 56 pièces    N° 096517 56','',1,'TI 3','UNITE',1,0.0,'Wurth France',1,0,0,0,''),
        ('ART-333','Outillage Manuel','CLE ALLEN 17','MARQUE SAM','Sam',1,'TI 3','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-334','Outillage Manuel','CLE ALLEN 14','MARQUE SAM','Sam',1,'TI 3','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-335','Outillage Manuel','CLE ALLEN 12','MARQUE SAM','Sam',1,'TI 3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-336','Outillage Manuel','CLE ALLEN 6','MARQUE SAM','Sam',1,'TI 3','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-337','Abrasifs & Disques','DISQUE METAL','300X3,8X20 MARQUE MASTERPRO (1BOITE = 25 PCS)','Masterpro',3,'','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-338','Abrasifs & Disques','DISQUE METAL','300X3,5X21 MARQUE TYROLIT (1BOITE = 10PCS)','Tyrolit',3,'A3','BOITE',1,0.0,'',6,0,0,0,''),
        ('ART-339','Équipements Spéciaux','ENROBE A FROID NOIR 25KG','89035525','',1,'','UNITE',1,0.0,'Wurth France',10,0,0,0,''),
        ('ART-340','Équipements Spéciaux','FOURREAUX ROUGE  50M','FAMALEX ROUGE 63','',4,'','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-341','Lubrifiants & Produits','GRAISSE POUR AIGUILLE','REF SNCF','',4,'','UNITE',1,0.0,'Bechem',8,0,0,0,''),
        ('ART-342','Équipements Spéciaux','BIDIM NOIR','25M MARQUE TERRAM','Terram',4,'','UNITE',1,0.0,'',30,0,0,0,''),
        ('ART-343','Équipements Spéciaux','BIDIM GRIS','50M','',4,'','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-344','Équipements Spéciaux','BIDIM','TERAM BLEU','',4,'','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-345','Équipements Spéciaux','BIDIM NOIR GRAVEL','','',4,'','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-346','Équipements Spéciaux','TAPIS ROUGE','','',4,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-347','Équipements Spéciaux','ECLISSE TANCONI PAIRE','','',4,'','PAIRE',1,0.0,'',2,0,0,0,''),
        ('ART-348','Équipements Spéciaux','SAM','2 JAUNE + 1 BLEU + 2BLANC','',4,'','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-349','Équipements Spéciaux','ABSORBANT','','',4,'','UNITE',1,0.0,'Difope',14,5,0,15,''),
        ('ART-350','Conditionnement & Rangement','FILM  POLYETHYLENE','','',4,'','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-351','Outillage Manuel','CHAINE + CROCHER(PELLE)','','',4,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-352','Équipements Spéciaux','CUVE ADBLUE 100L','','',1,'','UNITE',1,0.0,'Total Energie',600,0,0,0,''),
        ('ART-353','Équipements Spéciaux','FUT AD BLUE 200L','','',1,'','UNITE',1,0.0,'Total Energie',1,0,0,0,''),
        ('ART-354','Équipements Spéciaux','NEON','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-355','Équipements Spéciaux','COMPTEUR ELECTRIQUE','','',1,'','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-356','Fixations & Visserie','ECROU','M8+ M6','',1,'','BOITE',1,0.0,'',1,0,0,0,''),
        ('ART-357','Outillage Manuel','BOUCLE DE SERRAGE','','',3,'B2','BOITE',1,0.0,'',4,0,0,0,''),
        ('ART-358','Outillage Manuel','ELINGUE','','',1,'','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-359','Équipements Spéciaux','SAM 3 BLANC + 1 ROUGE + 1 JAUNE','','',1,'','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-360','Outillage Manuel','SANGLE','','',1,'','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-361','Équipements Spéciaux','CHALUMEAU','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-362','Équipements Spéciaux','SAM BLANC','','',1,'','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-363','Éclairage & Électricité','PILE PCFF 2000','4,5 200AH','',1,'','BOITE',1,0.0,'',2,0,0,0,''),
        ('ART-364','Équipements Spéciaux','ENROULEUR ELECTRIQUE','40 M','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-365','Équipements Spéciaux','CHARGEUR TALKIE WALKIE','KENWOOO','',1,'','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-366','Équipements Spéciaux','GLK 112-1','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-367','Équipements Spéciaux','GLK 123-1','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-368','Équipements Spéciaux','GLK 221-1','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-369','Équipements Spéciaux','CHARGEUR MOTOROLA','','',1,'','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-370','Équipements Spéciaux','CHARGEUR ICOM','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-371','Équipements Spéciaux','CHARGEUR LEICA','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-372','Équipements Spéciaux','CABLE D`ANTENNE 2,8M','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-373','Équipements Spéciaux','POCHETTE TALKIE WALKIE','','',1,'','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-374','Équipements Spéciaux','FRIGO','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-375','Équipements Spéciaux','FLEXIBLE','06,CP,P92','',1,'','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-376','Équipements Spéciaux','POIGAN','SPCFP92','',1,'','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-377','Équipements Spéciaux','TETE D`ACCOUPLEMENT RACCORD','','',1,'','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-378','Abrasifs & Disques','DISQUE  MEULE A TRONCONNES','125X1,6X22,23','',1,'','UNITE',1,0.0,'',16,0,0,0,''),
        ('ART-379','Équipements Spéciaux','CHARGEUR','C4/36.350','',1,'','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-380','Équipements Spéciaux','CHARGEUR','C4/90','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-381','Éclairage & Électricité','BATTERIE','14,4/2,6 AH','',1,'','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-382','Fixations & Visserie','DOUILLE','13,5 MM','',1,'','UNITE',1,0.0,'Cembre',14,0,0,0,''),
        ('ART-383','Équipements Spéciaux','COMPTEUR EAU','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-384','Équipements Spéciaux','PRISE','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-385','Outillage Manuel','CLE JAUNE','DIAMETRE 38 MANCHE COURT','',1,'','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-386','Équipements Spéciaux','RUBAN','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-387','Mesure & Traçage','REGLE ASER CHANTIER','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-388','Équipements Spéciaux','PIED DE BICHE','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-389','Conditionnement & Rangement','FILM 3X25 M','','',1,'','ROULEAU',1,0.0,'',1,0,0,0,''),
        ('ART-390','Vêtements de travail','GILETS 3XL ENCADRANT','','',1,'','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-391','Vêtements de travail','GILETS 2XL','','',1,'','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-392','Vêtements de travail','GILETS XL','','',1,'','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-393','Vêtements de travail','GILETS L','','',1,'','UNITE',1,0.0,'',13,0,0,0,''),
        ('ART-394','Vêtements de travail','GILETS M','','',1,'','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-395','Vêtements de travail','GILETS S','','',1,'','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-396','Équipements Spéciaux','ROULEAU POLYANE','','',1,'','ROULEAU',1,0.0,'Prolian',4,0,0,0,''),
        ('ART-397','Nettoyage & Hygiène','SAC A GRAVAT','MARQUE OPSIAL 50L 5 SACS DANS UN PAQUET','Opsial',2,'','PAQUET',1,0.0,'Prolian',0,0,0,0,''),
        ('ART-398','Équipements Spéciaux','FEUILLARD / CERCLAGE','','',3,'B2','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-399','Équipements Spéciaux','PIQUET PORTE LANTERNE','','',4,'','UNITE',1,0.0,'',28,0,0,0,''),
        ('ART-400','Outillage Manuel','SANGLES EN 1M','','',1,'','UNITE',1,0.0,'Mabeo',11,0,0,0,''),
        ('ART-476','Équipements Spéciaux','FOURCHE A CAILLOUX','','',1,'','UNITE',1,0.0,'Wurth France',20,5,0,0,''),
        ('ART-477','Équipements Spéciaux','PROTEGE FOURCHE','','',1,'','UNITE',1,0.0,'New Technik',4,0,0,0,''),
        ('ART-478','Équipements Spéciaux','BAR ECARTEMENT','','',3,'B4','UNITE',1,0.0,'Robel',8,0,0,0,''),
        ('ART-479','Équipements Spéciaux','CRIC HYDRAULIQUE','','',3,'B4','UNITE',1,0.0,'Geismar',7,0,0,0,''),
        ('ART-480','Équipements Spéciaux','CRIC MANUEL','','',3,'B4','UNITE',1,0.0,'Strail',1,0,0,0,''),
        ('ART-481','Outillage Ferroviaire','TENAILLE RAIL','','',3,'B4','UNITE',1,0.0,'Robel',3,0,0,0,''),
        ('ART-482','Outillage Ferroviaire','PINCE A RAIL GALET','','',3,'B4','UNITE',1,0.0,'Robel',2,0,0,0,''),
        ('ART-483','Équipements Spéciaux','BROSSE DECALAMINEUSE','DIAM 203 X25,4X25,4','',3,'B1','UNITE',1,0.0,'Geismar',150,0,0,0,''),
        ('ART-484','Équipements Spéciaux','BROSSE METALIQUE CYLINDRIQUE','6000 MAX RPM','',3,'B1','UNITE',1,0.0,'',18,0,0,0,''),
        ('ART-485','Abrasifs & Disques','DISQUE CENTRE','MSFS 3600 RPM','',3,'B1','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-486','Équipements Spéciaux','ROUE A LAMELLE','RPM 5200 MAX  165X50X30    MARQUE FLEXOVIT    KX 310','Flexovit',3,'B1','UNITE',1,0.0,'',55,0,0,0,''),
        ('ART-487','Outillage Électroportatif','PROJECTEUR ELECTRIQUE','','',3,'B1','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-488','Équipements Spéciaux','TRACEUR DE CHANTIER BLEU','','',1,'B2','UNITE',1,0.0,'',2,5,0,20,''),
        ('ART-489','Équipements Spéciaux','TRACEUR DE CHANTIER ROUGE','','',1,'','UNITE',1,0.0,'',2,5,0,20,''),
        ('ART-490','Équipements Spéciaux','TRACEUR DE CHANTIER JAUNE','','',1,'','UNITE',1,0.0,'',2,5,0,20,''),
        ('ART-491','Outillage Manuel','KIT CERCLAGE FEUILLARD AVEC 200 BOUCLES','','',3,'B2','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-492','Équipements Spéciaux','BOITE ELECTRIQUE RESISTANTE  DERIVATION','','',3,'B2','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-493','Équipements Spéciaux','RACCORD SYMETRIQUE POMPIER','','',3,'B2','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-494','Équipements Spéciaux','MICRO ONDE','SAMSUNG','',3,'B2','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-495','Équipements Spéciaux','TUYAU POMPIER','','',3,'B2','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-496','Outillage Manuel','MANCHE PIOCHE EN PLASTIQUE','MARQUE LEBORGNE 532900','Leborgne',3,'B2','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-497','Outillage Manuel','MANCHE PIOCHE EN BOIS','MARQUE OPSIAL OPS43087312','Opsial',3,'B2','UNITE',1,0.0,'Prolian',5,0,0,0,''),
        ('ART-498','Équipements Spéciaux','MANCHE RATEAU EN BOIS','','',3,'B2','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-499','Équipements Spéciaux','MANCHE MASSE EN BOIS','MARQUE PICARD 00990010','Picard',3,'B2','UNITE',1,0.0,'',5,0,0,0,''),
        ('ART-500','Outillage Manuel','MANCHE DE PELLE EN BOIS','','',3,'B2','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-501','Équipements Spéciaux','MANCHE BALAIS EN BOIS','','',3,'B2','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-502','Équipements Spéciaux','RATEAUX SANS MANCHE','0695943581','',3,'B2','UNITE',1,0.0,'Wurth France',3,0,0,0,''),
        ('ART-503','Outillage Manuel','PELLE RONDE SANS MANCHE','29CM   069590229','',3,'B2','UNITE',1,0.0,'Wurth France',3,0,0,0,''),
        ('ART-504','Outillage Manuel','PELLE CARRE','23 CM 069590223','',3,'B2','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-505','Équipements Spéciaux','BARRIERE EXTENSIBLE','4M','',3,'B2','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-506','Équipements Spéciaux','CRIC HYDRAULIQUE','','',3,'B3','UNITE',1,0.0,'Robel',3,0,0,0,''),
        ('ART-507','Outillage Ferroviaire','TENAILLE RAIL','','',3,'B3','UNITE',1,0.0,'Geismar',2,0,0,0,''),
        ('ART-508','Outillage Manuel','ELINGUE 10T TEXTILE','','',3,'B3','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-509','Fixations & Visserie','VIS  ENTRETOISE','M10X70 MARQUE INDEX  (1BOITE = 400 UNITES)','Index',3,'B3','BOITE',1,0.0,'',15,0,0,0,''),
        ('ART-510','Fixations & Visserie','VIS + MECHE','','',3,'B3','UNITE',1,0.0,'',90,0,0,0,''),
        ('ART-511','Équipements Spéciaux','BONBONNE   3L','GROUPE DE REFRIGERATION SR3000','',1,'','UNITE',1,0.0,'Cembre',4,1,0,4,''),
        ('ART-512','Équipements Spéciaux','CORDE LASH TRAVERSES','105   32M','',3,'B3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-513','Équipements Spéciaux','BALAIS INDUSTRIEL','60CM EN BOIS','',3,'B3','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-514','Équipements Spéciaux','BALAIS  ATELIER','55CM EN BOIS','',3,'B3','UNITE',1,0.0,'Prolian',2,0,0,0,''),
        ('ART-515','Équipements Spéciaux','BALAYETTE','30 CM MANCHE LONG 450X30 XHANDER','Xhander',3,'B3','UNITE',1,0.0,'Prolian',3,0,0,0,''),
        ('ART-516','Équipements Spéciaux','BALAYETTE','','',3,'B3','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-517','Outillage Manuel','PELLE CARRE METAL POUR BALAYETTE','','',3,'B3','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-518','Équipements Spéciaux','TOURET DE CABLE RIGIDE INTERNET','C6','',3,'B3','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-519','Équipements Spéciaux','BARRE A MINE','','',3,'AU SOL','UNITE',1,0.0,'Wurth France',2,0,0,0,''),
        ('ART-520','Outillage Manuel','PINCE A TALON','CODE ARTICLE 21 125   MECARAIL OU REVEX','',3,'AU SOL','UNITE',1,0.0,'Mecarail',13,0,0,0,''),
        ('ART-521','Équipements Spéciaux','BARRE A MINE LOURDE','','',3,'AU SOL','UNITE',1,0.0,'',9,0,0,0,''),
        ('ART-522','Équipements Spéciaux','BARRE BLANCHE','FASTCLIP PART NUMBER AE16180/FR','',3,'AU SOL','UNITE',1,0.0,'Pandrol',5,0,0,0,''),
        ('ART-523','Équipements Spéciaux','BARRE JAUNE','FASTCLIP AE17122/FR','',3,'AU SOL','UNITE',1,0.0,'Pandrol',0,0,0,0,''),
        ('ART-524','Équipements Spéciaux','MAILLET','CODE ARTICLE  21 266','',3,'AU SOL','UNITE',1,0.0,'Mecarail',4,0,0,0,''),
        ('ART-525','Équipements Spéciaux','MAILLET BLANC','MARTEAU HALDER MARQUE SUPERCRAFT D80 / 4 KG','Supercraft',3,'AU SOL','UNITE',1,0.0,'Prolian',10,3,0,10,''),
        ('ART-526','Outillage Ferroviaire','TENAILLE RAIL','','',3,'AU SOL','UNITE',1,0.0,'',12,0,0,0,''),
        ('ART-527','Équipements Spéciaux','MASSE 4KG','MARQUE XHANDER 4KG 68600731','Xhander',3,'AU SOL','UNITE',1,0.0,'Prolian',8,0,0,0,''),
        ('ART-528','Outillage Manuel','PIOCHE','','',3,'AU SOL','UNITE',1,0.0,'',4,0,0,0,''),
        ('ART-529','Outillage Manuel','PINCE    EN C','','',3,'AU SOL','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-530','Équipements Spéciaux','CRIC MANUEL','','',3,'AU SOL','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-531','Équipements Spéciaux','CHEVALIER  SOUDEUR','RAIL TECH','',3,'AU SOL','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-532','Équipements Spéciaux','FOURCHE A CAILLOUX AVEC MANCHE','0695943855','',3,'AU SOL','UNITE',1,0.0,'Wurth France',5,0,0,0,''),
        ('ART-533','Équipements Spéciaux','RATEAUX  AVEC MANCHE','','',3,'AU SOL','UNITE',1,0.0,'',3,0,0,0,''),
        ('ART-534','Équipements Spéciaux','BRAS DE LORRY','','',3,'AU SOL','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-535','Outillage Manuel','CLE A SERRE','','',3,'AU SOL','UNITE',1,0.0,'',8,0,0,0,''),
        ('ART-536','Équipements Spéciaux','MIRE TOPOGRAPHIE','','',3,'AU SOL','UNITE',1,0.0,'',1,0,0,0,''),
        ('ART-537','Mesure & Traçage','REGLE RIPAGE','','',3,'AU SOL','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-538','Équipements Spéciaux','FICELLE TRESSE PP 3MM  BLANC','','3M',3,'A1','UNITE',1,0.0,'',2,0,0,0,''),
        ('ART-539','Équipements Spéciaux','PROTEGE FOURCHE','','',3,'AU SOL','UNITE',1,0.0,'New Technik',1,0,0,0,''),
        ('ART-540','Équipements Spéciaux','ARGON','PLEIN','',1,'','UNITE',1,0.0,'Novair',3,0,0,0,''),
        ('ART-546','Équipements Spéciaux','ARGON','FQ27GEP   PLEIN','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-547','Équipements Spéciaux','ARGON','HB41CRH PLEIN','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-548','Équipements Spéciaux','ARGON','PX53FX7 PLEIN','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-549','Équipements Spéciaux','ARGON','ER15AKV   VIDE','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-550','Équipements Spéciaux','ARGON','AP71KCM  VIDE','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-551','Équipements Spéciaux','ARGON','HB36XJY   VIDE','',1,'','UNITE',1,0.0,'Novair',1,0,0,0,''),
        ('ART-576','Équipements Spéciaux','PROTEGE FOURCHE','','',3,'B3','PAIRE',1,0.0,'Ops',4,0,0,0,''),
        ('ART-577','Abrasifs & Disques','DISQUE 320X3,2X22','XHANDER','Xhander',2,'A3','BOITE',1,0.0,'Prolian',1,0,0,0,''),
        ('ART-578','Protection Individuelle','GANTS HIVER','GANT NYLON CHAUD NINJA T10','',1,'A2','PAQUET',1,0.0,'Prolian',145,0,0,0,''),
        ('ART-579','Équipements Spéciaux','CHARRUE A BALLAST','1UCB000','',3,'AU SOL','UNITE',1,0.0,'RMS Ferroviaire',4,1,0,5,''),
        ('ART-580','Outillage Manuel','COUVERCLE DE POUBELLE','','',1,'B1','UNITE',1,0.0,'Fix On',7,0,0,0,''),
        ('ART-581','Équipements Spéciaux','PRESSE A SERTIR','HT120 OUTIL TYPE   2610420','',1,'B1','UNITE',1,0.0,'Cembre',1,0,0,0,''),
        ('ART-582','Fixations & Visserie','VIS M10X60','005791060   BOITE DE 100','',3,'A3','BOITE',1,0.0,'Wurth France',10,5,0,10,''),
        ('ART-583','Équipements Spéciaux','COLLIER 2 OREILLES ACIER D-15-18 W1','06502156','',1,'AR 2','UNITE',1,0.0,'Prolian',80,0,0,0,''),
        ('ART-584','Fixations & Visserie','ECROUS HEXAGONAUX COMBINES','14F45000009 M10  1BOITE=100 PIECES','',3,'A2','BOITE',1,0.0,'Bossard',11,10,0,50,''),
        ('ART-600','Fixations & Visserie','VIS A TETE HEXAGONALE  M10X60  BOULON','BN21200','',3,'A2','UNITE',1,0.0,'Bossard',0,0,0,0,''),
        ('ART-601','Équipements Spéciaux','CRAIE POUR STEATITE','09844005','',1,'','BOITE',1,0.0,'Wurth France',5,0,0,0,''),
        ('ART-602','Équipements Spéciaux','GRILLAGE ORANGE','','',1,'','ROULEAU',1,0.0,'Prolian',5,0,0,0,''),
        ('ART-603','Équipements Spéciaux','GUIDE CHAINE DE 40','GUIDE`40CM*3/8 1,6MM ROLLOMATIC','',1,'B3','UNITE',1,61.1,'Crosnier',0,0,0,0,''),
        ('ART-604','Équipements Spéciaux','CHAINE DE 40','CHAINE 3/8 1,6MM 60M RAPID MICRO','',1,'B3','UNITE',1,26.34,'Crosnier',0,0,0,0,''),
        ('ART-605','Outillage Manuel','POMPE ROTATIVE ADBLUE','','',1,'','UNITE',1,0.0,'Manutan',3,0,0,0,''),
        ('ART-606','Outillage Manuel','ELINGUE 10T 6M','','',3,'','UNITE',1,123.0,'Mabeo',4,0,0,0,''),
        ('ART-607','Outillage Manuel','ELINGUE','5M  5T MARQUE WURTH','Wurth',1,'','UNITE',1,0.0,'',6,0,0,0,''),
        ('ART-608','Équipements Spéciaux','PAPIER THERMIQUE PESON DOOSAN JAUNE','DIAM : 35MM    LARGEUR : 80MM','',1,'','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-609','Outillage Manuel','SANGLE 6T 9M','713921192','',1,'','UNITE',1,0.0,'Wurth France',5,0,0,0,''),
        ('ART-610','Conditionnement & Rangement','SAC DE PRELEVMENT','','',1,'','UNITE',1,0.0,'',0,0,0,0,''),
        ('ART-611','Gaz & Soudage','Bouteille Oxygène','','Air Liquide',6,'Zone Gaz','UNITE',1,0.0,'Air Liquide',37,5,10,50,'Stockage plein air'),
        ('ART-612','Gaz & Soudage','Bouteille Acétylène','','Air Liquide',6,'Zone Gaz','UNITE',1,0.0,'Air Liquide',30,3,8,40,'Stockage plein air')
    ]
    for a in articles:
        c.execute("""INSERT INTO articles
            (id,famille,designation,reference,marque,container_id,emplacement,unite,colisage,
             prix_achat,fournisseur,stock,stock_min,stock_alerte,stock_max,observations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", a)

    # Fournisseurs
    fournisseurs = [
        ('F-001','Wurth France','','','','',5,'30j net','EPI, Cles, Fixations, Nettoyants',''),
        ('F-002','Hilti France','','','','',7,'30j net','Perfo, Couronnes, Forets',''),
        ('F-003','Bossard','','','','',10,'45j net','Boulons, Visserie, Ecrous',''),
        ('F-004','Prolian','','','','',5,'30j net','EPI, Combinaisons, Lunettes, Disques',''),
        ('F-005','Mabeo','','','','',7,'30j net','Gants, EPI, Levage',''),
        ('F-006','Geismar','','','','',14,'45j net','Outillage ferroviaire',''),
        ('F-007','Robel','','','','',21,'45j net','Outillage ferroviaire',''),
        ('F-008','Pandrol','','','','',30,'60j net','Fixations rail, Attaches',''),
        ('F-009','Stihl France','','','','',14,'30j net','Tronconneuses, Accessoires',''),
        ('F-010','Cembre','','','','',14,'45j net','Liaisons electriques rail',''),
        ('F-011','Doga','','','','',10,'30j net','Fraises, Outillage ferroviaire',''),
        ('F-012','RMS Ferroviaire','','','','',21,'60j net','Materiel voie ferrée',''),
        ('F-013','Air Liquide','','','','',7,'30j net','Bouteilles gaz, Acetylene, Oxygene',''),
        ('F-014','Mecarail','','','','',14,'45j net','Materiel ferroviaire',''),
        ('F-015','Bechem','','','','',10,'30j net','Lubrifiants, Graisses',''),
        ('F-016','Sofranel','','','','',14,'45j net','Outillage, Materiel',''),
        ('F-017','Strail','','','','',21,'60j net','Systemes ferroviaires',''),
        ('F-018','Novair','','','','',7,'30j net','Compresseurs, Air',''),
        ('F-019','Total Energie','','','','',5,'30j net','Carburants, Lubrifiants',''),
        ('F-020','Extruplast','','','','',14,'30j net','Plastiques, Conditionnement',''),
        ('F-021','123 Big Bag','','','','',7,'30j net','Big bags, Conditionnement',''),
        ('F-022','Lyreco','','','','',5,'30j net','Fournitures bureau, Hygiene',''),
        ('F-023','Manutan','','','','',7,'30j net','Outillage, EPI, Rangement',''),
        ('F-024','Difope','','','','',10,'30j net','Outillage, Fixations',''),
        ('F-025','Fix On','','','','',7,'30j net','Fixations, Adhesifs',''),
        ('F-026','St Gobain','','','','',14,'45j net','Materiaux, Abrasifs',''),
        ('F-027','L`Outil Parfait','','','','',7,'30j net','Outillage professionnel',''),
        ('F-028','Crosnier','','','','',14,'30j net','Materiel ferroviaire',''),
        ('F-029','Dupont','','','','',7,'30j net','EPI, Protection',''),
        ('F-030','ETF Beauchamp','','','','',3,'interne','Materiel interne ETF',''),
        ('F-031','New Technik','','','','',14,'30j net','Outillage, Technique',''),
        ('F-032','Prozon','','','','',10,'30j net','Nettoyage, Hygiene',''),
        ('F-033','Ops','','','','',7,'30j net','EPI, Securite',''),
        ('F-034','OPS','','','','',7,'30j net','Securite, EPI',''),
    ]
    for f in fournisseurs:
        c.execute("""INSERT INTO fournisseurs
            (id,nom,contact,telephone,email,adresse,delai,conditions,articles_fournis,commentaires)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", f)

    # Bons sortie exemples
    bons_s = [
        ('BS-001','2025-01-15','Martin J.',1,'Distribution initiale'),
        ('BS-002','2025-02-03','Dupont P.',2,'Tronconnage rail km 42'),
        ('BS-003','2025-02-10','Bernard L.',3,'Lampes frontales'),
        ('BS-004','2025-02-15','Martin J.',1,'EPI equipe A'),
        ('BS-005','2025-03-01','Dupont P.',4,'Levage et decoupe'),
        ('BS-006','2025-03-10','Martin J.',3,'Entretien et meulage'),
    ]
    for bs in bons_s:
        c.execute("""INSERT INTO bons_sortie
            (numero,date_sortie,demandeur,chantier_id,commentaire)
            VALUES (?,?,?,?,?)""", bs)
    # Lignes bons de sortie
    bs_lignes = [
        (1,'ART-011',10),(1,'ART-012',3),(1,'ART-017',1),
        (2,'ART-081',15),(2,'ART-083',10),(2,'ART-086',10),
        (3,'ART-076',40),(3,'ART-071',5),
        (4,'ART-011',5),(4,'ART-020',2),
        (5,'ART-046',2),(5,'ART-050',5),
        (6,'ART-091',2),(6,'ART-086',5),
    ]
    for bl in bs_lignes:
        c.execute("INSERT INTO bons_sortie_lignes (bon_id,article_id,quantite) VALUES (?,?,?)", bl)

    # Bons reception
    bons_r = [
        ('BR-001','2025-01-10','Wurth','BL-WURTH-001','ART-011',100,91,1.5,'Reception OK'),
        ('BR-002','2025-01-10','Xhander','BL-PIE-001','ART-081',120,120,18.0,'OK'),
        ('BR-003','2025-01-12','Varta','BL-VAR-001','ART-076',400,400,0.35,'OK'),
        ('BR-004','2025-02-20','Bossard','BL-BOSS-001','ART-122',20,17,14.0,'3 boites manquantes'),
        ('BR-005','2025-03-05','Hilti','BL-HIL-001','ART-062',10,8,0.0,'OK'),
        ('BR-006','2025-03-08','KF','BL-KF-001','ART-091',15,11,18.0,'4 manquants'),
        ('BR-007','2025-03-10','Bolle','BL-BOL-001','ART-017',50,45,22.0,'OK'),
        ('BR-008','2025-03-12','Opsial','BL-OPS-001','ART-013',20,17,12.0,'OK'),
    ]
    for br in bons_r:
        c.execute("""INSERT INTO bons_reception
            (numero,date_reception,fournisseur,num_bl,article_id,qte_commandee,qte_recue,prix_unitaire,commentaire)
            VALUES (?,?,?,?,?,?,?,?,?)""", br)

    # Commandes
    cmds = [
        ('CMD-001','2025-03-01','Bossard','RECEPTIONNEE','2025-03-01','2025-03-05','2025-03-08','Boulons rail'),
        ('CMD-002','2025-03-10','KF Lubricants','EN COURS','2025-03-10','2025-03-20','','En transit'),
        ('CMD-003','2025-03-12','Opsial','VALIDEE','2025-03-12','2025-03-25','','Urgent'),
        ('CMD-004','2025-03-14','Wurth France SAS','EN ATTENTE','','','',''),
        ('CMD-005','2025-03-15','Hilti France','EN ATTENTE','','','','Stock critique'),
    ]
    for cmd in cmds:
        c.execute("""INSERT INTO commandes
            (numero,date_demande,fournisseur,statut,date_commande,livraison_prevue,date_reception,commentaire)
            VALUES (?,?,?,?,?,?,?,?)""", cmd)
    # Lignes des commandes de démonstration
    cmd_lignes = [
        (1,'ART-122',20,14.0),(1,'ART-124',50,8.0),
        (2,'ART-091',10,18.0),(2,'ART-092',5,12.0),
        (3,'ART-013',5,12.0),
        (4,'ART-003',10,3.2),(4,'ART-004',10,3.2),
        (5,'ART-139',5,89.0),(5,'ART-021',10,28.0),
    ]
    for cl in cmd_lignes:
        c.execute("INSERT INTO commande_lignes (commande_id,article_id,quantite,prix_unitaire) VALUES (?,?,?,?)", cl)

    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# ─── AUTH ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        pw = request.form.get('password','')
        conn = get_db()
        user = conn.execute("SELECT * FROM utilisateurs WHERE email=? AND actif=1",(email,)).fetchone()
        conn.close()
        if user and user['password_hash'] == hash_pw(pw):
            session['user_id'] = user['id']
            session['user_nom'] = user['nom']
            session['user_role'] = user['role']
            return redirect(url_for('dashboard'))
        flash('Email ou mot de passe incorrect','error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    articles = conn.execute("SELECT * FROM articles WHERE actif=1").fetchall()
    total = len(articles)
    ruptures = sum(1 for a in articles if a['stock']==0)
    critiques = sum(1 for a in articles if 0<a['stock']<=a['stock_min'])
    alertes = sum(1 for a in articles if a['stock_min']<a['stock']<=a['stock_alerte'])
    valeur = sum(a['stock']*a['prix_achat'] for a in articles)
    urgents = sorted([a for a in articles if a['stock']<=a['stock_min']], key=lambda x:x['stock'])
    bons_s_raw = conn.execute("""SELECT bs.*, ch.nom as chantier_nom FROM bons_sortie bs
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id ORDER BY bs.id DESC LIMIT 8""").fetchall()
    bons_s = []
    for b in bons_s_raw:
        l = conn.execute("""SELECT bsl.*, a.designation FROM bons_sortie_lignes bsl
            LEFT JOIN articles a ON bsl.article_id=a.id WHERE bsl.bon_id=? LIMIT 1""",(b['id'],)).fetchone()
        bons_s.append({'bon':b,'first':l,'nb':conn.execute("SELECT COUNT(*) FROM bons_sortie_lignes WHERE bon_id=?",(b['id'],)).fetchone()[0]})
    cmds_raw = conn.execute("""SELECT * FROM commandes
        WHERE statut IN ('EN ATTENTE','EN COURS','VALIDEE') ORDER BY id DESC LIMIT 6""").fetchall()
    cmds = []
    for c in cmds_raw:
        lignes = conn.execute("""SELECT cl.*, a.designation FROM commande_lignes cl
            LEFT JOIN articles a ON cl.article_id=a.id WHERE cl.commande_id=? LIMIT 1""",(c['id'],)).fetchall()
        cmds.append({'cmd':c,'lignes':lignes,'nb_lignes':len(lignes)})
    containers = conn.execute("SELECT * FROM containers WHERE actif=1").fetchall()
    container_stats = []
    for ct in containers:
        arts = conn.execute("SELECT * FROM articles WHERE container_id=? AND actif=1",(ct['id'],)).fetchall()
        val = sum(a['stock']*a['prix_achat'] for a in arts)
        alerts = sum(1 for a in arts if a['stock']<=a['stock_alerte'])
        container_stats.append({'container':ct,'nb':len(arts),'valeur':val,'alertes':alerts})
    conn.close()
    return render_template('dashboard.html',
        total=total, ruptures=ruptures, critiques=critiques, alertes=alertes,
        valeur=valeur, urgents=urgents[:8], bons_s=bons_s, cmds=cmds,
        container_stats=container_stats, get_etat=get_etat_stock,
        nb_cmds_attente=len([c for c in cmds_raw if c['statut']=='EN ATTENTE']))

# ─── CONTAINERS ───────────────────────────────────────────────────────────────

@app.route('/containers')
@login_required
def containers():
    conn = get_db()
    cts = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    result = []
    for ct in cts:
        arts = conn.execute("SELECT * FROM articles WHERE container_id=? AND actif=1",(ct['id'],)).fetchall()
        valeur = sum(a['stock']*a['prix_achat'] for a in arts)
        alertes = sum(1 for a in arts if a['stock']<=a['stock_alerte'])
        ruptures = sum(1 for a in arts if a['stock']==0)
        result.append({'ct':ct,'nb':len(arts),'valeur':valeur,'alertes':alertes,'ruptures':ruptures})
    conn.close()
    return render_template('containers.html', containers=result)

@app.route('/containers/ajouter', methods=['POST'])
@login_required
def ajouter_container():
    conn = get_db()
    try:
        conn.execute("""INSERT INTO containers (nom,code,numero,description,emplacement,statut)
            VALUES (?,?,?,?,?,?)""",(
            request.form.get('nom',''),
            request.form.get('code','').upper(),
            request.form.get('numero',''),
            request.form.get('description',''),
            request.form.get('emplacement',''),
            request.form.get('statut','ACTIF'),
        ))
        conn.commit()
        flash('Container ajouté avec succès','success')
    except Exception as e:
        flash(f'Erreur : code déjà existant','error')
    conn.close()
    return redirect(url_for('containers'))

@app.route('/containers/modifier/<int:id>', methods=['POST'])
@login_required
def modifier_container(id):
    conn = get_db()
    conn.execute("""UPDATE containers SET nom=?,description=?,emplacement=?,statut=? WHERE id=?""",(
        request.form.get('nom',''),
        request.form.get('description',''),
        request.form.get('emplacement',''),
        request.form.get('statut','ACTIF'),
        id,
    ))
    conn.commit(); conn.close()
    flash('Container modifié','success')
    return redirect(url_for('containers'))

@app.route('/containers/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_container(id):
    conn = get_db()
    nb = conn.execute("SELECT COUNT(*) FROM articles WHERE container_id=? AND actif=1",(id,)).fetchone()[0]
    if nb > 0:
        flash(f'Impossible : {nb} article(s) dans ce container. Déplacez-les d\'abord.','error')
    else:
        conn.execute("UPDATE containers SET actif=0 WHERE id=?",(id,))
        conn.commit()
        flash('Container supprimé','success')
    conn.close()
    return redirect(url_for('containers'))

@app.route('/containers/<int:id>/stock')
@login_required
def container_stock(id):
    conn = get_db()
    ct = conn.execute("SELECT * FROM containers WHERE id=?",(id,)).fetchone()
    if not ct:
        flash('Container introuvable','error')
        return redirect(url_for('containers'))
    articles = conn.execute("""SELECT a.*, c.nom as container_nom FROM articles a
        LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.container_id=? AND a.actif=1 ORDER BY a.famille, a.designation""",(id,)).fetchall()
    valeur = sum(a['stock']*a['prix_achat'] for a in articles)
    mouvs = conn.execute("""SELECT m.*, a.designation FROM mouvements m
        LEFT JOIN articles a ON m.article_id=a.id
        WHERE m.container_id=? ORDER BY m.id DESC LIMIT 20""",(id,)).fetchall()
    conn.close()
    return render_template('container_stock.html', ct=ct, articles=articles,
        valeur=valeur, mouvs=mouvs, get_etat=get_etat_stock)

# ─── TRANSFERTS ───────────────────────────────────────────────────────────────

@app.route('/transferts')
@login_required
def transferts():
    conn = get_db()
    trs = conn.execute("""SELECT t.*, a.designation, a.unite,
        cs.nom as source_nom, cd.nom as dest_nom
        FROM transferts t
        LEFT JOIN articles a ON t.article_id=a.id
        LEFT JOIN containers cs ON t.container_source=cs.id
        LEFT JOIN containers cd ON t.container_dest=cd.id
        ORDER BY t.id DESC""").fetchall()
    conn.close()
    return render_template('transferts.html', transferts=trs)

@app.route('/transferts/nouveau', methods=['GET','POST'])
@login_required
def nouveau_transfert():
    if request.method == 'POST':
        article_id = request.form.get('article_id','')
        src = int(request.form.get('container_source',0))
        dst = int(request.form.get('container_dest',0))
        qte = int(request.form.get('quantite',0))
        conn = get_db()
        article = conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
        if not article:
            flash('Article introuvable','error'); conn.close()
            return redirect(url_for('nouveau_transfert'))
        if src == dst:
            flash('Source et destination identiques','error'); conn.close()
            return redirect(url_for('nouveau_transfert'))
        if qte > article['stock']:
            flash(f'Stock insuffisant : {article["stock"]} disponible','error'); conn.close()
            return redirect(url_for('nouveau_transfert'))
        numero = get_next_numero('transferts','numero','TRF-')
        conn.execute("""INSERT INTO transferts
            (numero,date_transfert,article_id,container_source,container_dest,quantite,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?,?)""",(
            numero, request.form.get('date_transfert',date.today().isoformat()),
            article_id, src, dst, qte,
            request.form.get('commentaire',''), session.get('user_id'),
        ))
        conn.execute("UPDATE articles SET container_id=? WHERE id=?",(dst, article_id))
        log_mouvement(conn,'TRANSFERT',article_id,qte,numero,
            article['stock'],article['stock'],dst,0,
            f"De container {src} vers {dst}")
        conn.commit(); conn.close()
        flash(f'Transfert {numero} effectué','success')
        return redirect(url_for('transferts'))
    conn = get_db()
    articles = conn.execute("SELECT a.*,c.nom as ct_nom FROM articles a LEFT JOIN containers c ON a.container_id=c.id WHERE a.actif=1 ORDER BY a.designation").fetchall()
    containers = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('nouveau_transfert.html', articles=articles, containers=containers, today=date.today().isoformat())

# ─── CHANTIERS ────────────────────────────────────────────────────────────────

@app.route('/chantiers')
@login_required
def chantiers():
    conn = get_db()
    chs = conn.execute("SELECT * FROM chantiers WHERE actif=1 ORDER BY statut,nom").fetchall()
    result = []
    for ch in chs:
        nb_sorties = conn.execute("SELECT COUNT(*) FROM bons_sortie WHERE chantier_id=?",(ch['id'],)).fetchone()[0]
        cout = conn.execute("""SELECT SUM(bsl.quantite * a.prix_achat)
            FROM bons_sortie bs LEFT JOIN bons_sortie_lignes bsl ON bsl.bon_id=bs.id
            LEFT JOIN articles a ON bsl.article_id=a.id WHERE bs.chantier_id=?""",(ch['id'],)).fetchone()[0] or 0
        result.append({'ch':ch,'nb_sorties':nb_sorties,'cout':cout})
    conn.close()
    return render_template('chantiers.html', chantiers=result)

@app.route('/chantiers/ajouter', methods=['POST'])
@login_required
def ajouter_chantier():
    conn = get_db()
    try:
        conn.execute("""INSERT INTO chantiers (nom,code,adresse,chef,date_debut,date_fin,statut,budget)
            VALUES (?,?,?,?,?,?,?,?)""",(
            request.form.get('nom',''),
            request.form.get('code','').upper(),
            request.form.get('adresse',''),
            request.form.get('chef',''),
            request.form.get('date_debut',''),
            request.form.get('date_fin',''),
            request.form.get('statut','ACTIF'),
            float(request.form.get('budget',0)),
        ))
        conn.commit()
        flash('Chantier ajouté','success')
    except Exception as e:
        flash(f'Erreur : code déjà existant','error')
    conn.close()
    return redirect(url_for('chantiers'))

@app.route('/chantiers/modifier/<int:id>', methods=['POST'])
@login_required
def modifier_chantier(id):
    conn = get_db()
    conn.execute("""UPDATE chantiers SET nom=?,adresse=?,chef=?,date_debut=?,date_fin=?,statut=?,budget=? WHERE id=?""",(
        request.form.get('nom',''), request.form.get('adresse',''),
        request.form.get('chef',''), request.form.get('date_debut',''),
        request.form.get('date_fin',''), request.form.get('statut','ACTIF'),
        float(request.form.get('budget',0)), id,
    ))
    conn.commit(); conn.close()
    flash('Chantier modifié','success')
    return redirect(url_for('chantiers'))

@app.route('/chantiers/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_chantier(id):
    conn = get_db()
    conn.execute("UPDATE chantiers SET actif=0 WHERE id=?",(id,))
    conn.commit(); conn.close()
    flash('Chantier archivé','success')
    return redirect(url_for('chantiers'))

# ─── FAMILLES ─────────────────────────────────────────────────────────────────

@app.route('/familles')
@login_required
def familles():
    conn = get_db()
    fams = conn.execute("SELECT * FROM familles WHERE actif=1 ORDER BY nom").fetchall()
    result = []
    for f in fams:
        nb = conn.execute("SELECT COUNT(*) FROM articles WHERE famille=? AND actif=1",(f['nom'],)).fetchone()[0]
        result.append({'f':f,'nb':nb})
    conn.close()
    return render_template('familles.html', familles=result)

@app.route('/familles/ajouter', methods=['POST'])
@login_required
def ajouter_famille():
    conn = get_db()
    try:
        conn.execute("INSERT INTO familles (nom,icone,couleur,description) VALUES (?,?,?,?)",(
            request.form.get('nom','').upper(),
            request.form.get('icone','📦'),
            request.form.get('couleur','#E8661A'),
            request.form.get('description',''),
        ))
        conn.commit(); flash('Famille ajoutée','success')
    except: flash('Famille déjà existante','error')
    conn.close()
    return redirect(url_for('familles'))

@app.route('/familles/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_famille(id):
    conn = get_db()
    f = conn.execute("SELECT nom FROM familles WHERE id=?",(id,)).fetchone()
    if f:
        nb = conn.execute("SELECT COUNT(*) FROM articles WHERE famille=? AND actif=1",(f['nom'],)).fetchone()[0]
        if nb > 0:
            flash(f'Impossible : {nb} article(s) dans cette famille','error')
        else:
            conn.execute("UPDATE familles SET actif=0 WHERE id=?",(id,))
            conn.commit(); flash('Famille supprimée','success')
    conn.close()
    return redirect(url_for('familles'))

# ─── CATALOGUE ────────────────────────────────────────────────────────────────

@app.route('/catalogue')
@login_required
def catalogue():
    conn = get_db()
    q = request.args.get('q','')
    famille = request.args.get('famille','')
    container_id = request.args.get('container_id','')
    etat = request.args.get('etat','')
    sql = """SELECT a.*, c.nom as container_nom, c.code as container_code
             FROM articles a LEFT JOIN containers c ON a.container_id=c.id WHERE a.actif=1"""
    params = []
    if q:
        sql += " AND (a.designation LIKE ? OR a.id LIKE ? OR a.reference LIKE ? OR a.marque LIKE ?)"
        params += [f'%{q}%']*4
    if famille:
        sql += " AND a.famille=?"; params.append(famille)
    if container_id:
        sql += " AND a.container_id=?"; params.append(container_id)
    sql += " ORDER BY a.famille, a.designation"
    articles = list(conn.execute(sql, params).fetchall())
    if etat == 'RUPTURE': articles = [a for a in articles if a['stock']==0]
    elif etat == 'CRITIQUE': articles = [a for a in articles if 0<a['stock']<=a['stock_min']]
    elif etat == 'ALERTE': articles = [a for a in articles if a['stock_min']<a['stock']<=a['stock_alerte']]
    elif etat == 'OK': articles = [a for a in articles if a['stock']>a['stock_alerte']]
    familles = conn.execute("SELECT DISTINCT famille FROM articles WHERE actif=1 ORDER BY famille").fetchall()
    containers = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('catalogue.html', articles=articles, familles=familles,
        containers=containers, q=q, famille_sel=famille, container_sel=container_id,
        etat_sel=etat, get_etat=get_etat_stock)

@app.route('/catalogue/ajouter', methods=['GET','POST'])
@login_required
def ajouter_article():
    if request.method == 'POST':
        conn = get_db()
        last = conn.execute("SELECT id FROM articles ORDER BY id DESC LIMIT 1").fetchone()
        try: n = int(last['id'].replace('ART-',''))+1 if last else 148
        except: n = 148
        new_id = f"ART-{n:03d}"
        conn.execute("""INSERT INTO articles
            (id,famille,designation,reference,marque,container_id,emplacement,unite,colisage,
             prix_achat,fournisseur,stock,stock_min,stock_alerte,stock_max,delai_livraison,observations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            new_id, request.form.get('famille',''), request.form.get('designation',''),
            request.form.get('reference',''), request.form.get('marque',''),
            int(request.form.get('container_id',1)), request.form.get('emplacement',''),
            request.form.get('unite','UNITE'), int(request.form.get('colisage',1)),
            float(request.form.get('prix_achat',0)), request.form.get('fournisseur',''),
            int(request.form.get('stock',0)), int(request.form.get('stock_min',0)),
            int(request.form.get('stock_alerte',0)), int(request.form.get('stock_max',0)),
            int(request.form.get('delai_livraison',0)),
            request.form.get('observations',''),
        ))
        conn.commit(); conn.close()
        flash(f'Article {new_id} créé','success')
        return redirect(url_for('catalogue'))
    conn = get_db()
    familles = conn.execute("SELECT * FROM familles WHERE actif=1 ORDER BY nom").fetchall()
    fournisseurs = conn.execute("SELECT nom FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    containers = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('ajouter_article.html', familles=familles, fournisseurs=fournisseurs, containers=containers)

@app.route('/catalogue/modifier/<id>', methods=['GET','POST'])
@login_required
def modifier_article(id):
    conn = get_db()
    article = conn.execute("SELECT * FROM articles WHERE id=?",(id,)).fetchone()
    if not article:
        flash('Article introuvable','error'); conn.close()
        return redirect(url_for('catalogue'))
    if request.method == 'POST':
        conn.execute("""UPDATE articles SET famille=?,designation=?,reference=?,marque=?,
            container_id=?,emplacement=?,unite=?,colisage=?,prix_achat=?,fournisseur=?,
            stock_min=?,stock_alerte=?,stock_max=?,delai_livraison=?,observations=? WHERE id=?""",(
            request.form.get('famille',''), request.form.get('designation',''),
            request.form.get('reference',''), request.form.get('marque',''),
            int(request.form.get('container_id',1)), request.form.get('emplacement',''),
            request.form.get('unite','UNITE'), int(request.form.get('colisage',1)),
            float(request.form.get('prix_achat',0)), request.form.get('fournisseur',''),
            int(request.form.get('stock_min',0)), int(request.form.get('stock_alerte',0)),
            int(request.form.get('stock_max',0)), int(request.form.get('delai_livraison',0)),
            request.form.get('observations',''), id,
        ))
        conn.commit(); conn.close()
        flash('Article modifié','success')
        return redirect(url_for('catalogue'))
    familles = conn.execute("SELECT * FROM familles WHERE actif=1 ORDER BY nom").fetchall()
    fournisseurs = conn.execute("SELECT nom FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    containers = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('modifier_article.html', article=article, familles=familles, fournisseurs=fournisseurs, containers=containers)

@app.route('/catalogue/supprimer/<id>', methods=['POST'])
@login_required
def supprimer_article(id):
    conn = get_db()
    conn.execute("UPDATE articles SET actif=0 WHERE id=?",(id,))
    conn.commit(); conn.close()
    flash('Article archivé','success')
    return redirect(url_for('catalogue'))

@app.route('/api/article/<id>')
@login_required
def api_article(id):
    conn = get_db()
    a = conn.execute("SELECT a.*,c.nom as ct_nom FROM articles a LEFT JOIN containers c ON a.container_id=c.id WHERE a.id=?",(id,)).fetchone()
    conn.close()
    if a:
        return jsonify({'ok':True,'designation':a['designation'],'stock':a['stock'],
                        'unite':a['unite'],'fournisseur':a['fournisseur'],'prix':a['prix_achat'],
                        'container':a['ct_nom'] or ''})
    return jsonify({'ok':False})

# ─── BONS SORTIE ──────────────────────────────────────────────────────────────

@app.route('/bons-sortie')
@login_required
def bons_sortie():
    conn = get_db()
    bons_raw = conn.execute("""SELECT bs.*, ch.nom as chantier_nom FROM bons_sortie bs
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id ORDER BY bs.id DESC""").fetchall()
    bons = []
    for b in bons_raw:
        lignes = conn.execute("""SELECT bsl.*, a.designation, a.unite, a.prix_achat
            FROM bons_sortie_lignes bsl LEFT JOIN articles a ON bsl.article_id=a.id
            WHERE bsl.bon_id=?""",(b['id'],)).fetchall()
        montant = sum(l['quantite']*(l['prix_achat'] or 0) for l in lignes)
        bons.append({'bon':b,'lignes':lignes,'montant':montant,'nb':len(lignes)})
    conn.close()
    return render_template('bons_sortie.html', bons=bons)

@app.route('/bons-sortie/nouveau', methods=['GET','POST'])
@login_required
def nouveau_bon_sortie():
    if request.method == 'POST':
        conn = get_db()
        articles_ids = request.form.getlist('article_id[]')
        quantites = request.form.getlist('quantite[]')
        chantier_id = int(request.form.get('chantier_id',0))
        date_sortie = request.form.get('date_sortie',date.today().isoformat())
        demandeur = request.form.get('demandeur','')
        # Vérifier stocks
        errors = []
        lignes_ok = []
        for i, art_id in enumerate(articles_ids):
            if not art_id.strip(): continue
            qte = int(quantites[i]) if i<len(quantites) and quantites[i] else 0
            if qte <= 0: continue
            article = conn.execute("SELECT * FROM articles WHERE id=?",(art_id,)).fetchone()
            if not article:
                errors.append(f'Article {art_id} introuvable')
            elif qte > article['stock']:
                errors.append(f'{article["designation"]} : stock insuffisant ({article["stock"]} dispo)')
            else:
                lignes_ok.append((article, qte))
        if errors:
            for e in errors: flash(e,'error')
            conn.close(); return redirect(url_for('nouveau_bon_sortie'))
        if not lignes_ok:
            flash('Ajoutez au moins un article','error')
            conn.close(); return redirect(url_for('nouveau_bon_sortie'))
        numero = get_next_numero('bons_sortie','numero','BS-')
        conn.execute("""INSERT INTO bons_sortie
            (numero,date_sortie,demandeur,chantier_id,commentaire,created_by)
            VALUES (?,?,?,?,?,?)""",(
            numero, date_sortie, demandeur, chantier_id,
            request.form.get('commentaire',''), session.get('user_id'),
        ))
        bon_id = conn.execute("SELECT id FROM bons_sortie WHERE numero=?",(numero,)).fetchone()['id']
        for article, qte in lignes_ok:
            s_avant = article['stock']; s_apres = s_avant - qte
            conn.execute("INSERT INTO bons_sortie_lignes (bon_id,article_id,quantite,prix_achat) VALUES (?,?,?,?)",
                (bon_id, article['id'], qte, article['prix_achat']))
            conn.execute("UPDATE articles SET stock=? WHERE id=?",(s_apres, article['id']))
            conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
                quantite,reference_doc,stock_avant,stock_apres,container_id,chantier_id)
                VALUES (?,?,?,?,?,?,?,?,?)""",(
                date.today().isoformat(),'SORTIE',article['id'],qte,numero,
                s_avant,s_apres,article['container_id'],chantier_id
            ))
        conn.commit(); conn.close()
        flash(f'Bon {numero} créé — {len(lignes_ok)} article(s) sortis','success')
        return redirect(url_for('bons_sortie'))
    conn = get_db()
    articles = conn.execute("""SELECT a.*, c.nom as ct_nom FROM articles a
        LEFT JOIN containers c ON a.container_id=c.id WHERE a.actif=1 ORDER BY a.famille,a.designation""").fetchall()
    chantiers = conn.execute("SELECT * FROM chantiers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('nouveau_bon_sortie.html', articles=articles, chantiers=chantiers, today=date.today().isoformat())

# ─── BONS RECEPTION ───────────────────────────────────────────────────────────

@app.route('/bons-reception')
@login_required
def bons_reception():
    conn = get_db()
    bons = conn.execute("""SELECT br.*, a.designation, a.unite FROM bons_reception br
        LEFT JOIN articles a ON br.article_id=a.id ORDER BY br.id DESC""").fetchall()
    conn.close()
    return render_template('bons_reception.html', bons=bons)

@app.route('/bons-reception/nouveau', methods=['GET','POST'])
@login_required
def nouveau_bon_reception():
    if request.method == 'POST':
        article_id = request.form.get('article_id','').strip()
        qte_recue = int(request.form.get('qte_recue',0))
        conn = get_db()
        article = conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
        if not article:
            flash('Article introuvable','error'); conn.close()
            return redirect(url_for('nouveau_bon_reception'))
        numero = get_next_numero('bons_reception','numero','BR-')
        s_avant = article['stock']; s_apres = s_avant + qte_recue
        conn.execute("""INSERT INTO bons_reception
            (numero,date_reception,fournisseur,num_bl,article_id,qte_commandee,
             qte_recue,prix_unitaire,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",(
            numero, request.form.get('date_reception',date.today().isoformat()),
            request.form.get('fournisseur',''), request.form.get('num_bl',''),
            article_id, int(request.form.get('qte_commandee',0)), qte_recue,
            float(request.form.get('prix_unitaire',0)),
            request.form.get('commentaire',''), session.get('user_id'),
        ))
        conn.execute("UPDATE articles SET stock=? WHERE id=?",(s_apres,article_id))
        conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
            quantite,reference_doc,stock_avant,stock_apres,container_id)
            VALUES (?,?,?,?,?,?,?,?)""",(
            date.today().isoformat(),'RECEPTION',article_id,qte_recue,numero,
            s_avant,s_apres,article['container_id']
        ))
        conn.commit(); conn.close()
        flash(f'Bon {numero} créé — Nouveau stock : {s_apres} {article["unite"]}','success')
        return redirect(url_for('bons_reception'))
    conn = get_db()
    articles = conn.execute("""SELECT a.*, c.nom as ct_nom FROM articles a
        LEFT JOIN containers c ON a.container_id=c.id WHERE a.actif=1 ORDER BY a.famille,a.designation""").fetchall()
    fournisseurs = conn.execute("SELECT nom FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('nouveau_bon_reception.html', articles=articles, fournisseurs=fournisseurs, today=date.today().isoformat())

# ─── COMMANDES ────────────────────────────────────────────────────────────────

@app.route('/commandes')
@login_required
def commandes():
    conn = get_db()
    statut = request.args.get('statut','')
    sql = "SELECT * FROM commandes"
    params = []
    if statut: sql += " WHERE statut=?"; params.append(statut)
    sql += " ORDER BY id DESC"
    cmds_raw = conn.execute(sql, params).fetchall()
    cmds = []
    for c in cmds_raw:
        lignes = conn.execute("""SELECT cl.*, a.designation, a.unite FROM commande_lignes cl
            LEFT JOIN articles a ON cl.article_id=a.id WHERE cl.commande_id=?""",(c['id'],)).fetchall()
        montant = sum(l['quantite']*l['prix_unitaire'] for l in lignes)
        cmds.append({'cmd':c,'lignes':lignes,'montant':montant,'nb':len(lignes)})
    conn.close()
    return render_template('commandes.html', cmds=cmds, statut_sel=statut)

@app.route('/commandes/nouvelle', methods=['GET','POST'])
@login_required
def nouvelle_commande():
    if request.method == 'POST':
        numero = get_next_numero('commandes','numero','CMD-')
        conn = get_db()
        date_dem = request.form.get('date_demande', date.today().isoformat())
        livraison = request.form.get('livraison_prevue','')
        delai_jours = 0
        if livraison and date_dem:
            try:
                from datetime import datetime as dt2
                d1 = dt2.strptime(date_dem, '%Y-%m-%d')
                d2 = dt2.strptime(livraison, '%Y-%m-%d')
                delai_jours = max(0, (d2 - d1).days)
            except: pass
        conn.execute("""INSERT INTO commandes
            (numero,date_demande,fournisseur,statut,livraison_prevue,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?)""",(
            numero, date_dem,
            request.form.get('fournisseur',''),
            'EN ATTENTE', livraison,
            request.form.get('commentaire',''),
            session.get('user_id'),
        ))
        cmd_id = conn.execute("SELECT id FROM commandes WHERE numero=?",(numero,)).fetchone()['id']
        # Lignes articles
        articles_ids = request.form.getlist('article_id[]')
        quantites = request.form.getlist('quantite[]')
        prix = request.form.getlist('prix_unitaire[]')
        for i, art_id in enumerate(articles_ids):
            if art_id and art_id.strip():
                conn.execute("INSERT INTO commande_lignes (commande_id,article_id,quantite,prix_unitaire) VALUES (?,?,?,?)",(
                    cmd_id, art_id.strip(),
                    int(quantites[i]) if i<len(quantites) and quantites[i] else 1,
                    float(prix[i]) if i<len(prix) and prix[i] else 0,
                ))
        conn.commit(); conn.close()
        flash(f'Commande {numero} créée avec {len([a for a in articles_ids if a])} article(s)','success')
        return redirect(url_for('commandes'))
    conn = get_db()
    articles = conn.execute("SELECT id,designation,stock,stock_min,fournisseur,prix_achat FROM articles WHERE actif=1 ORDER BY famille,designation").fetchall()
    fournisseurs = conn.execute("SELECT nom FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('nouvelle_commande.html', articles=articles, fournisseurs=fournisseurs, today=date.today().isoformat())

@app.route('/commandes/statut/<int:id>', methods=['POST'])
@login_required
def maj_statut_commande(id):
    statut = request.form.get('statut','')
    conn = get_db()
    conn.execute("UPDATE commandes SET statut=? WHERE id=?",(statut,id))
    if statut == 'VALIDEE':
        conn.execute("UPDATE commandes SET date_commande=? WHERE id=?",(date.today().isoformat(),id))
    elif statut == 'RECEPTIONNEE':
        conn.execute("UPDATE commandes SET date_reception=? WHERE id=?",(date.today().isoformat(),id))
    conn.commit(); conn.close()
    flash('Statut mis à jour','success')
    return redirect(url_for('commandes'))

@app.route('/commandes/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_commande(id):
    conn = get_db()
    conn.execute("DELETE FROM commande_lignes WHERE commande_id=?",(id,))
    conn.execute("DELETE FROM commandes WHERE id=?",(id,))
    conn.commit(); conn.close()
    flash('Commande supprimée','success')
    return redirect(url_for('commandes'))

# ─── INVENTAIRE ───────────────────────────────────────────────────────────────

@app.route('/inventaire')
@login_required
def inventaire():
    conn = get_db()
    invs = conn.execute("""SELECT i.*, a.designation, a.unite,
        c.nom as container_nom FROM inventaires i
        LEFT JOIN articles a ON i.article_id=a.id
        LEFT JOIN containers c ON i.container_id=c.id
        ORDER BY i.id DESC LIMIT 100""").fetchall()
    conn.close()
    return render_template('inventaire.html', inventaires=invs)

@app.route('/inventaire/nouveau', methods=['GET','POST'])
@login_required
def nouvel_inventaire():
    if request.method == 'POST':
        article_id = request.form.get('article_id','')
        stock_reel = int(request.form.get('stock_reel',0))
        conn = get_db()
        article = conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
        if not article:
            flash('Article introuvable','error'); conn.close()
            return redirect(url_for('nouvel_inventaire'))
        stock_theorique = article['stock']
        ecart = stock_reel - stock_theorique
        numero = get_next_numero('inventaires','numero','INV-')
        conn.execute("""INSERT INTO inventaires
            (numero,date_inventaire,container_id,article_id,stock_theorique,stock_reel,ecart,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?,?,?)""",(
            numero, request.form.get('date_inventaire',date.today().isoformat()),
            article['container_id'], article_id, stock_theorique, stock_reel, ecart,
            request.form.get('commentaire',''), session.get('user_id'),
        ))
        if request.form.get('appliquer') == '1':
            conn.execute("UPDATE articles SET stock=? WHERE id=?",(stock_reel,article_id))
            log_mouvement(conn,'INVENTAIRE',article_id,abs(ecart),numero,
                stock_theorique,stock_reel,article['container_id'],0,
                f"Inventaire — écart {ecart:+d}")
        conn.commit(); conn.close()
        flash(f'Inventaire {numero} enregistré — Écart : {ecart:+d}','success')
        return redirect(url_for('inventaire'))
    conn = get_db()
    articles = conn.execute("""SELECT a.*,c.nom as ct_nom FROM articles a
        LEFT JOIN containers c ON a.container_id=c.id WHERE a.actif=1 ORDER BY a.famille,a.designation""").fetchall()
    containers = conn.execute("SELECT * FROM containers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('nouvel_inventaire.html', articles=articles, containers=containers, today=date.today().isoformat())

# ─── MOUVEMENTS ───────────────────────────────────────────────────────────────

@app.route('/mouvements')
@login_required
def mouvements():
    conn = get_db()
    q = request.args.get('q','')
    type_filtre = request.args.get('type','')
    sql = """SELECT m.*, a.designation, c.nom as container_nom,
        ch.nom as chantier_nom FROM mouvements m
        LEFT JOIN articles a ON m.article_id=a.id
        LEFT JOIN containers c ON m.container_id=c.id
        LEFT JOIN chantiers ch ON m.chantier_id=ch.id
        WHERE 1=1"""
    params = []
    if q:
        sql += " AND (LOWER(a.designation) LIKE ? OR LOWER(m.article_id) LIKE ? OR LOWER(m.user_nom) LIKE ?)"
        params += [f'%{q.lower()}%']*3
    if type_filtre:
        sql += " AND m.type_mouvement=?"
        params.append(type_filtre)
    sql += " ORDER BY m.id DESC LIMIT 500"
    mvts = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template('mouvements.html', mouvements=mvts, q=q, type_filtre=type_filtre)

# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@app.route('/analytics')
@login_required
def analytics():
    conn = get_db()
    try:
        articles = conn.execute("SELECT * FROM articles WHERE actif=1").fetchall()
        valeur_totale = sum((a['stock'] or 0)*(a['prix_achat'] or 0) for a in articles)
        total = len(articles)
        ruptures = sum(1 for a in articles if (a['stock'] or 0)==0)
        critiques = sum(1 for a in articles if 0<(a['stock'] or 0)<=(a['stock_min'] or 0))
        alertes = sum(1 for a in articles if (a['stock_min'] or 0)<(a['stock'] or 0)<=(a['stock_alerte'] or 0))
        
        familles_stats = {}
        for a in articles:
            f = a['famille'] or 'Divers'
            if f not in familles_stats:
                familles_stats[f] = {'nb':0,'valeur':0,'ruptures':0,'alertes':0}
            familles_stats[f]['nb'] += 1
            familles_stats[f]['valeur'] += (a['stock'] or 0)*(a['prix_achat'] or 0)
            etat = get_etat_stock(a['stock'] or 0, a['stock_min'] or 0, a['stock_alerte'] or 0)
            if etat == 'RUPTURE': familles_stats[f]['ruptures'] += 1
            elif etat in ('CRITIQUE','ALERTE'): familles_stats[f]['alertes'] += 1
        familles_list = sorted(familles_stats.items(), key=lambda x:x[1]['valeur'], reverse=True)
        
        try:
            top_sorties = conn.execute("""SELECT bsl.article_id, a.designation,
                SUM(bsl.quantite) as total_sorti, a.unite, MAX(bs.date_sortie) as derniere_sortie
                FROM bons_sortie_lignes bsl LEFT JOIN articles a ON bsl.article_id=a.id
                LEFT JOIN bons_sortie bs ON bsl.bon_id=bs.id
                GROUP BY bsl.article_id, a.designation, a.unite
                ORDER BY total_sorti DESC LIMIT 10""").fetchall()
        except: top_sorties = []
        
        urgents = sorted([a for a in articles if (a['stock'] or 0)<=(a['stock_min'] or 0)],
                        key=lambda x: x['stock'] or 0)
        
        mois = date.today().strftime('%Y-%m')
        try:
            nb_sorties_mois = conn.execute(
                "SELECT COUNT(DISTINCT bs.id) FROM bons_sortie bs WHERE bs.date_sortie LIKE ?",
                (f'{mois}%',)).fetchone()[0] or 0
        except: nb_sorties_mois = 0
        
        try:
            nb_receptions_mois = conn.execute(
                "SELECT COUNT(*) FROM bons_reception WHERE date_reception LIKE ?",
                (f'{mois}%',)).fetchone()[0] or 0
        except: nb_receptions_mois = 0
        
        try:
            chantier_stats = conn.execute("""SELECT ch.nom, COUNT(DISTINCT bs.id) as nb_sorties,
                COALESCE(SUM(bsl.quantite * a.prix_achat), 0) as cout
                FROM bons_sortie bs
                LEFT JOIN bons_sortie_lignes bsl ON bsl.bon_id=bs.id
                LEFT JOIN chantiers ch ON bs.chantier_id=ch.id
                LEFT JOIN articles a ON bsl.article_id=a.id
                GROUP BY bs.chantier_id, ch.nom ORDER BY cout DESC""").fetchall()
        except: chantier_stats = []
        
    except Exception as e:
        conn.close()
        raise e
    
    conn.close()
    return render_template('analytics.html',
        valeur_totale=valeur_totale, total=total, ruptures=ruptures, critiques=critiques,
        alertes=alertes, familles_list=familles_list, top_sorties=top_sorties,
        urgents=urgents[:15], get_etat=get_etat_stock,
        nb_sorties_mois=nb_sorties_mois, nb_receptions_mois=nb_receptions_mois,
        chantier_stats=chantier_stats)

# ─── FOURNISSEURS ─────────────────────────────────────────────────────────────

@app.route('/fournisseurs')
@login_required
def fournisseurs():
    conn = get_db()
    fours = conn.execute("SELECT * FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    return render_template('fournisseurs.html', fournisseurs=fours)

@app.route('/fournisseurs/ajouter', methods=['POST'])
@login_required
def ajouter_fournisseur():
    conn = get_db()
    last = conn.execute("SELECT id FROM fournisseurs ORDER BY id DESC LIMIT 1").fetchone()
    try: n = int(last['id'].replace('F-',''))+1 if last else 21
    except: n = 21
    new_id = f"F-{n:03d}"
    conn.execute("""INSERT INTO fournisseurs
        (id,nom,contact,telephone,email,adresse,delai,conditions,articles_fournis,commentaires)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",(
        new_id, request.form.get('nom',''), request.form.get('contact',''),
        request.form.get('telephone',''), request.form.get('email',''),
        request.form.get('adresse',''), int(request.form.get('delai',7)),
        request.form.get('conditions','30j net'),
        request.form.get('articles_fournis',''), request.form.get('commentaires',''),
    ))
    conn.commit(); conn.close()
    flash(f'Fournisseur {new_id} ajouté','success')
    return redirect(url_for('fournisseurs'))

@app.route('/fournisseurs/supprimer/<id>', methods=['POST'])
@login_required
def supprimer_fournisseur(id):
    conn = get_db()
    conn.execute("UPDATE fournisseurs SET actif=0 WHERE id=?",(id,))
    conn.commit(); conn.close()
    flash('Fournisseur archivé','success')
    return redirect(url_for('fournisseurs'))

# ─── PARAMETRES ───────────────────────────────────────────────────────────────

@app.route('/parametres')
@login_required
def parametres():
    if session.get('user_role') not in ('admin','responsable'):
        flash('Accès réservé','error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    users = conn.execute("SELECT * FROM utilisateurs WHERE actif=1 ORDER BY role,nom").fetchall()
    stats = {
        'nb_articles': conn.execute("SELECT COUNT(*) FROM articles WHERE actif=1").fetchone()[0],
        'nb_containers': conn.execute("SELECT COUNT(*) FROM containers WHERE actif=1").fetchone()[0],
        'nb_chantiers': conn.execute("SELECT COUNT(*) FROM chantiers WHERE actif=1").fetchone()[0],
        'nb_familles': conn.execute("SELECT COUNT(*) FROM familles WHERE actif=1").fetchone()[0],
        'nb_fournisseurs': conn.execute("SELECT COUNT(*) FROM fournisseurs WHERE actif=1").fetchone()[0],
        'nb_bons_sortie': conn.execute("SELECT COUNT(*) FROM bons_sortie").fetchone()[0],
        'nb_bons_reception': conn.execute("SELECT COUNT(*) FROM bons_reception").fetchone()[0],
        'nb_commandes': conn.execute("SELECT COUNT(*) FROM commandes").fetchone()[0],
        'nb_mouvements': conn.execute("SELECT COUNT(*) FROM mouvements").fetchone()[0],
        'valeur_stock': conn.execute("SELECT SUM(stock*prix_achat) FROM articles WHERE actif=1").fetchone()[0] or 0,
        'nb_ruptures': conn.execute("SELECT COUNT(*) FROM articles WHERE actif=1 AND stock=0").fetchone()[0],
        'nb_critiques': conn.execute("SELECT COUNT(*) FROM articles WHERE actif=1 AND stock>0 AND stock<=stock_min").fetchone()[0],
    }
    conn.close()
    return render_template('parametres.html', users=users, stats=stats)

@app.route('/parametres/utilisateurs/ajouter', methods=['POST'])
@login_required
def ajouter_utilisateur():
    if session.get('user_role') != 'admin':
        flash('Accès refusé','error'); return redirect(url_for('parametres'))
    conn = get_db()
    try:
        conn.execute("INSERT INTO utilisateurs (nom,email,password_hash,role) VALUES (?,?,?,?)",(
            request.form.get('nom',''), request.form.get('email',''),
            hash_pw(request.form.get('password','')), request.form.get('role','stock'),
        ))
        conn.commit(); flash('Utilisateur créé','success')
    except Exception as e:
        flash(f'Erreur : email déjà existant','error')
    conn.close()
    return redirect(url_for('parametres'))

@app.route('/parametres/utilisateurs/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_utilisateur(id):
    if session.get('user_role') != 'admin':
        flash('Accès refusé','error'); return redirect(url_for('parametres'))
    if id == session.get('user_id'):
        flash('Impossible de supprimer votre propre compte','error')
        return redirect(url_for('parametres'))
    conn = get_db()
    conn.execute("UPDATE utilisateurs SET actif=0 WHERE id=?",(id,))
    conn.commit(); conn.close()
    flash('Utilisateur désactivé','success')
    return redirect(url_for('parametres'))


# ─── IMPRESSION & EXPORT ──────────────────────────────────────────────────────

@app.route('/bons-sortie/<int:id>/imprimer')
@login_required
def imprimer_bon_sortie(id):
    return _imprimer_bon_sortie(id, avec_prix=True)

@app.route('/bons-sortie/<int:id>/imprimer-sans-prix')
@login_required
def imprimer_bon_sortie_sans_prix(id):
    return _imprimer_bon_sortie(id, avec_prix=False)

def _imprimer_bon_sortie(id, avec_prix=True):
    conn = get_db()
    bon = conn.execute("""SELECT bs.*, ch.nom as chantier_nom, ch.code as chantier_code,
        ch.adresse as chantier_adresse, u.nom as created_by_nom
        FROM bons_sortie bs
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id
        LEFT JOIN utilisateurs u ON bs.created_by=u.id
        WHERE bs.id=?""",(id,)).fetchone()
    if not bon:
        flash('Bon introuvable','error'); conn.close(); return redirect(url_for('bons_sortie'))
    lignes = conn.execute("""SELECT bsl.*, a.designation, a.unite, a.reference, a.marque, c.nom as container_nom
        FROM bons_sortie_lignes bsl LEFT JOIN articles a ON bsl.article_id=a.id
        LEFT JOIN containers c ON a.container_id=c.id WHERE bsl.bon_id=?""",(id,)).fetchall()
    conn.close()
    return render_template('print_bon_sortie.html', bon=bon, lignes=lignes, avec_prix=avec_prix)

@app.route('/bons-sortie/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_bon_sortie(id):
    conn = get_db()
    bon = conn.execute("SELECT * FROM bons_sortie WHERE id=?",(id,)).fetchone()
    if bon:
        lignes = conn.execute("SELECT * FROM bons_sortie_lignes WHERE bon_id=?",(id,)).fetchall()
        for l in lignes:
            conn.execute("UPDATE articles SET stock=stock+? WHERE id=?",(l['quantite'],l['article_id']))
        conn.execute("DELETE FROM bons_sortie_lignes WHERE bon_id=?",(id,))
        conn.execute("DELETE FROM bons_sortie WHERE id=?",(id,))
        conn.commit()
        flash(f'Bon {bon["numero"]} supprime - stocks restaures','success')
    conn.close()
    return redirect(url_for('bons_sortie'))

@app.route('/bons-reception/<int:id>/imprimer')
@login_required
def imprimer_bon_reception(id):
    conn = get_db()
    bon = conn.execute("""SELECT br.*, a.designation, a.unite, a.reference, a.marque,
        c.nom as container_nom, u.nom as created_by_nom
        FROM bons_reception br
        LEFT JOIN articles a ON br.article_id=a.id
        LEFT JOIN containers c ON a.container_id=c.id
        LEFT JOIN utilisateurs u ON br.created_by=u.id
        WHERE br.id=?""",(id,)).fetchone()
    conn.close()
    if not bon:
        flash('Bon introuvable','error'); return redirect(url_for('bons_reception'))
    return render_template('print_bon_reception.html', bon=bon)

@app.route('/bons-reception/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_bon_reception(id):
    conn = get_db()
    bon = conn.execute("SELECT * FROM bons_reception WHERE id=?",(id,)).fetchone()
    if bon:
        conn.execute("UPDATE articles SET stock=stock-? WHERE id=?",(bon['qte_recue'],bon['article_id']))
        conn.execute("DELETE FROM bons_reception WHERE id=?",(id,))
        conn.commit()
        flash(f'Bon {bon["numero"]} supprime','success')
    conn.close()
    return redirect(url_for('bons_reception'))

@app.route('/containers/<int:id>/imprimer')
@login_required
def imprimer_container(id):
    conn = get_db()
    ct = conn.execute("SELECT * FROM containers WHERE id=?",(id,)).fetchone()
    articles = conn.execute("SELECT * FROM articles WHERE container_id=? AND actif=1 ORDER BY famille, designation",(id,)).fetchall()
    valeur = sum(a['stock']*a['prix_achat'] for a in articles)
    conn.close()
    if not ct:
        flash('Container introuvable','error'); return redirect(url_for('containers'))
    return render_template('print_container.html', ct=ct, articles=articles, valeur=valeur, get_etat=get_etat_stock)

@app.route('/inventaire/<int:id>/imprimer')
@login_required
def imprimer_inventaire(id):
    conn = get_db()
    inv = conn.execute("""SELECT i.*, a.designation, a.unite, c.nom as container_nom
        FROM inventaires i LEFT JOIN articles a ON i.article_id=a.id
        LEFT JOIN containers c ON i.container_id=c.id WHERE i.id=?""",(id,)).fetchone()
    conn.close()
    if not inv:
        flash('Inventaire introuvable','error'); return redirect(url_for('inventaire'))
    return render_template('print_inventaire.html', inv=inv)

@app.route('/export/stock')
@login_required
def export_stock():
    import csv, io
    conn = get_db()
    articles = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.actif=1 ORDER BY a.famille, a.designation""").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID','Famille','Designation','Reference','Marque','Container','Emplacement',
                     'Unite','Prix achat','Fournisseur','Stock','Stock min','Stock alerte',
                     'Stock max','Valeur','Etat','Observations'])
    for a in articles:
        etat = get_etat_stock(a['stock'],a['stock_min'],a['stock_alerte'])
        writer.writerow([a['id'],a['famille'],a['designation'],a['reference'],a['marque'],
                         a['container_nom'] or '',a['emplacement'],a['unite'],
                         str(a['prix_achat']).replace('.',','),a['fournisseur'],
                         a['stock'],a['stock_min'],a['stock_alerte'],a['stock_max'],
                         str(round(a['stock']*a['prix_achat'],2)).replace('.',','),
                         etat,a['observations']])
    from flask import Response
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':f'attachment;filename=stock_{date.today().isoformat()}.csv'})

@app.route('/export/container/<int:id>')
@login_required
def export_container(id):
    import csv, io
    conn = get_db()
    ct = conn.execute("SELECT * FROM containers WHERE id=?",(id,)).fetchone()
    articles = conn.execute("SELECT * FROM articles WHERE container_id=? AND actif=1 ORDER BY famille,designation",(id,)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([f'CONTAINER : {ct["nom"]} ({ct["code"]}) - {date.today().isoformat()}'])
    writer.writerow(['ID','Famille','Designation','Reference','Emplacement','Unite','Prix','Stock','Min','Valeur','Etat'])
    for a in articles:
        etat = get_etat_stock(a['stock'],a['stock_min'],a['stock_alerte'])
        writer.writerow([a['id'],a['famille'],a['designation'],a['reference'],a['emplacement'],
                         a['unite'],str(a['prix_achat']).replace('.',','),a['stock'],a['stock_min'],
                         str(round(a['stock']*a['prix_achat'],2)).replace('.',','),etat])
    from flask import Response
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':f'attachment;filename=container_{ct["code"]}_{date.today().isoformat()}.csv'})

@app.route('/export/bons-sortie')
@login_required
def export_bons_sortie():
    import csv, io
    conn = get_db()
    bons = conn.execute("""SELECT bs.*, a.designation, a.unite, a.prix_achat,
        ch.nom as chantier_nom FROM bons_sortie bs
        LEFT JOIN articles a ON bs.article_id=a.id
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id ORDER BY bs.id DESC""").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['N','Date','Demandeur','Chantier','Article','Designation','Qte','Unite','Prix','Montant','Commentaire'])
    for b in bons:
        writer.writerow([b['numero'],b['date_sortie'],b['demandeur'],b['chantier_nom'] or '',
                         b['article_id'],b['designation'] or '',b['quantite'],b['unite'] or '',
                         str(b['prix_achat'] or 0).replace('.',','),
                         str(round(b['quantite']*(b['prix_achat'] or 0),2)).replace('.',','),
                         b['commentaire'] or ''])
    from flask import Response
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':f'attachment;filename=bons_sortie_{date.today().isoformat()}.csv'})

@app.route('/export/bons-reception')
@login_required
def export_bons_reception():
    import csv, io
    conn = get_db()
    bons = conn.execute("""SELECT br.*, a.designation, a.unite FROM bons_reception br
        LEFT JOIN articles a ON br.article_id=a.id ORDER BY br.id DESC""").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['N','Date','Fournisseur','BL','Article','Designation','Qte cmd','Qte recue','Prix u','Montant','Commentaire'])
    for b in bons:
        writer.writerow([b['numero'],b['date_reception'],b['fournisseur'],b['num_bl'] or '',
                         b['article_id'],b['designation'] or '',b['qte_commandee'],b['qte_recue'],
                         str(b['prix_unitaire']).replace('.',','),
                         str(round(b['qte_recue']*b['prix_unitaire'],2)).replace('.',','),
                         b['commentaire'] or ''])
    from flask import Response
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition':f'attachment;filename=bons_reception_{date.today().isoformat()}.csv'})


@app.route('/parametres/changer-mot-de-passe', methods=['POST'])
@login_required
def changer_mot_de_passe():
    ancien = request.form.get('ancien_password','')
    nouveau = request.form.get('nouveau_password','')
    confirm = request.form.get('confirm_password','')
    conn = get_db()
    user = conn.execute("SELECT * FROM utilisateurs WHERE id=?",(session['user_id'],)).fetchone()
    if user['password_hash'] != hash_pw(ancien):
        flash('Ancien mot de passe incorrect','error')
    elif nouveau != confirm:
        flash('Les mots de passe ne correspondent pas','error')
    elif len(nouveau) < 6:
        flash('Mot de passe trop court (6 caractères minimum)','error')
    else:
        conn.execute("UPDATE utilisateurs SET password_hash=? WHERE id=?",(hash_pw(nouveau),session['user_id']))
        conn.commit()
        flash('Mot de passe modifié avec succès','success')
    conn.close()
    return redirect(url_for('parametres'))

@app.route('/parametres/modifier-utilisateur/<int:id>', methods=['POST'])
@login_required
def modifier_utilisateur(id):
    if session.get('user_role') != 'admin':
        flash('Accès refusé','error'); return redirect(url_for('parametres'))
    conn = get_db()
    conn.execute("UPDATE utilisateurs SET nom=?,role=? WHERE id=?",(
        request.form.get('nom',''), request.form.get('role','magasinier'), id,
    ))
    if request.form.get('nouveau_password'):
        conn.execute("UPDATE utilisateurs SET password_hash=? WHERE id=?",(
            hash_pw(request.form.get('nouveau_password','')), id,
        ))
    conn.commit(); conn.close()
    flash('Utilisateur modifié','success')
    return redirect(url_for('parametres'))

@app.route('/parametres/reset-stock', methods=['POST'])
@login_required
def reset_stock():
    if session.get('user_role') != 'admin':
        flash('Accès refusé — Admin uniquement','error'); return redirect(url_for('parametres'))
    confirm = request.form.get('confirm_reset','')
    if confirm != 'CONFIRMER':
        flash('Tapez CONFIRMER pour valider la réinitialisation','error'); return redirect(url_for('parametres'))
    conn = get_db()
    conn.execute("DELETE FROM bons_sortie_lignes")
    conn.execute("DELETE FROM bons_sortie")
    conn.execute("DELETE FROM bons_reception")
    conn.execute("DELETE FROM commande_lignes")
    conn.execute("DELETE FROM commandes")
    conn.execute("DELETE FROM transferts")
    conn.execute("DELETE FROM inventaires")
    conn.execute("DELETE FROM mouvements")
    conn.commit(); conn.close()
    flash('Historique réinitialisé — articles conservés','success')
    return redirect(url_for('parametres'))

@app.route('/parametres/info')
@login_required
def parametres_info():
    conn = get_db()
    info = {
        'nb_articles': conn.execute("SELECT COUNT(*) FROM articles WHERE actif=1").fetchone()[0],
        'nb_containers': conn.execute("SELECT COUNT(*) FROM containers WHERE actif=1").fetchone()[0],
        'nb_chantiers': conn.execute("SELECT COUNT(*) FROM chantiers WHERE actif=1").fetchone()[0],
        'nb_familles': conn.execute("SELECT COUNT(*) FROM familles WHERE actif=1").fetchone()[0],
        'nb_fournisseurs': conn.execute("SELECT COUNT(*) FROM fournisseurs WHERE actif=1").fetchone()[0],
        'nb_bons_sortie': conn.execute("SELECT COUNT(*) FROM bons_sortie").fetchone()[0],
        'nb_bons_reception': conn.execute("SELECT COUNT(*) FROM bons_reception").fetchone()[0],
        'nb_commandes': conn.execute("SELECT COUNT(*) FROM commandes").fetchone()[0],
        'nb_mouvements': conn.execute("SELECT COUNT(*) FROM mouvements").fetchone()[0],
        'valeur_stock': conn.execute("SELECT SUM(stock*prix_achat) FROM articles WHERE actif=1").fetchone()[0] or 0,
    }
    conn.close()
    from flask import jsonify
    return jsonify(info)

@app.route('/api/recherche-articles')
@login_required
def api_recherche_articles():
    q = request.args.get('q','').strip()
    if len(q) < 2:
        return jsonify([])
    conn = get_db()
    q_lower = q.lower()
    if USE_POSTGRES:
        search_sql = """
            SELECT a.id, a.designation, a.famille, a.stock, a.unite, a.stock_min, a.stock_alerte, c.nom as ct_nom
            FROM articles a LEFT JOIN containers c ON a.container_id=c.id
            WHERE a.actif=1 AND (
                a.designation ILIKE ? OR a.id ILIKE ? OR
                a.reference ILIKE ? OR a.marque ILIKE ? OR
                a.famille ILIKE ? OR a.fournisseur ILIKE ?
            ) ORDER BY a.designation LIMIT 15"""
    else:
        search_sql = """
            SELECT a.id, a.designation, a.famille, a.stock, a.unite, a.stock_min, a.stock_alerte, c.nom as ct_nom
            FROM articles a LEFT JOIN containers c ON a.container_id=c.id
            WHERE a.actif=1 AND (
                LOWER(a.designation) LIKE ? OR LOWER(a.id) LIKE ? OR
                LOWER(a.reference) LIKE ? OR LOWER(a.marque) LIKE ? OR
                LOWER(a.famille) LIKE ? OR LOWER(a.fournisseur) LIKE ?
            ) ORDER BY a.designation LIMIT 15"""
    articles = conn.execute(search_sql, [f'%{q_lower}%']*6).fetchall()
    conn.close()
    result = []
    for a in articles:
        if a['stock'] == 0: etat = 'RUPTURE'
        elif a['stock'] <= a['stock_min']: etat = 'CRITIQUE'
        elif a['stock'] <= a['stock_alerte']: etat = 'ALERTE'
        else: etat = 'OK'
        result.append({
            'id': a['id'], 'designation': a['designation'],
            'famille': a['famille'], 'stock': a['stock'],
            'unite': a['unite'], 'container': a['ct_nom'] or '',
            'etat': etat
        })
    return jsonify(result)



@app.route('/articles/<id>/qrcode')
@login_required
def qrcode_article(id):
    """Page avec QR code imprimable pour un article."""
    conn = get_db()
    article = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.id=?""",(id,)).fetchone()
    conn.close()
    if not article:
        flash('Article introuvable','error')
        return redirect(url_for('catalogue'))
    return render_template('print_qrcode.html', article=article)

@app.route('/articles/qrcodes-container/<int:container_id>')
@login_required  
def qrcodes_container_v1(container_id):
    """Page avec tous les QR codes d un container."""
    conn = get_db()
    ct = conn.execute("SELECT * FROM containers WHERE id=?",(container_id,)).fetchone()
    articles = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.container_id=? AND a.actif=1 ORDER BY a.famille, a.designation""",(container_id,)).fetchall()
    conn.close()
    if not ct:
        flash('Container introuvable','error')
        return redirect(url_for('containers'))
    return render_template('print_qrcodes_container.html', ct=ct, articles=articles)

# ─── MODULE SCAN MOBILE ───────────────────────────────────────────────────────
# Pages légères optimisées téléphone — indépendantes de l'application principale

@app.route('/scan')
@login_required
def scan_mobile():
    """Page d'accueil scan mobile."""
    return render_template('mobile_scan.html')

@app.route('/scan/article/<id>')
@login_required
def scan_article(id):
    """Fiche article après scan QR — vue mobile."""
    conn = get_db()
    article = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.id=? AND a.actif=1""",(id,)).fetchone()
    chantiers = conn.execute("SELECT * FROM chantiers WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    if not article:
        return render_template('mobile_article_not_found.html', id=id)
    return render_template('mobile_article.html', article=article, chantiers=chantiers)

@app.route('/scan/sortie/<id>', methods=['POST'])
@login_required
def scan_sortie(id):
    """Valider une sortie depuis le scan mobile."""
    conn = get_db()
    article = conn.execute("SELECT * FROM articles WHERE id=? AND actif=1",(id,)).fetchone()
    if not article:
        conn.close()
        return render_template('mobile_erreur.html', msg="Article introuvable")
    
    quantite = int(request.form.get('quantite', 1))
    chantier_id = int(request.form.get('chantier_id', 0))
    demandeur = request.form.get('demandeur', session.get('user_nom',''))
    
    if quantite <= 0:
        conn.close()
        return render_template('mobile_erreur.html', msg="Quantité invalide")
    
    if quantite > article['stock']:
        conn.close()
        return render_template('mobile_erreur.html', 
            msg=f"Stock insuffisant — disponible : {article['stock']} {article['unite']}")
    
    from datetime import date as dt
    numero = get_next_numero('bons_sortie','numero','BS-')
    s_avant = article['stock']
    s_apres = s_avant - quantite
    
    conn.execute("""INSERT INTO bons_sortie
        (numero,date_sortie,demandeur,chantier_id,commentaire,created_by)
        VALUES (?,?,?,?,?,?)""",(
        numero, dt.today().isoformat(),
        demandeur, chantier_id, 'Sortie via scan mobile',
        session.get('user_id'),
    ))
    bon_id = conn.execute("SELECT id FROM bons_sortie WHERE numero=?",(numero,)).fetchone()[0]
    conn.execute("INSERT INTO bons_sortie_lignes (bon_id,article_id,quantite,prix_achat) VALUES (?,?,?,?)",
        (bon_id, id, quantite, article['prix_achat']))
    conn.execute("UPDATE articles SET stock=? WHERE id=?",(s_apres, id))
    log_mouvement(conn,'SORTIE',id,quantite,numero,
        s_avant,s_apres,article['container_id'],chantier_id,
        f"Scan mobile — {demandeur}")
    conn.commit()
    conn.close()
    
    return render_template('mobile_succes.html', 
        article=article, quantite=quantite, 
        nouveau_stock=s_apres, numero=numero)

@app.route('/scan/qrcode/<id>')
@login_required
def generer_qrcode(id):
    """Générer et afficher le QR code d un article."""
    conn = get_db()
    article = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.id=? AND a.actif=1""",(id,)).fetchone()
    conn.close()
    if not article:
        flash('Article introuvable','error')
        return redirect(url_for('catalogue'))
    # URL de scan pour cet article
    from flask import request as req
    base_url = req.host_url.rstrip('/')
    scan_url = f"{base_url}/scan/article/{id}"
    return render_template('print_qrcode.html', article=article, scan_url=scan_url)

@app.route('/scan/qrcodes-container/<int:container_id>')
@login_required
def qrcodes_container(container_id):
    """Imprimer tous les QR codes d un container."""
    conn = get_db()
    ct = conn.execute("SELECT * FROM containers WHERE id=?",(container_id,)).fetchone()
    articles = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.container_id=? AND a.actif=1 ORDER BY a.famille, a.designation""",(container_id,)).fetchall()
    conn.close()
    if not ct:
        flash('Container introuvable','error')
        return redirect(url_for('containers'))
    from flask import request as req
    base_url = req.host_url.rstrip('/')
    return render_template('print_qrcodes_container.html', ct=ct, articles=articles, base_url=base_url)

@app.route('/scan/reception/<id>')
@login_required
def scan_reception(id):
    """Fiche réception article après scan QR — vue mobile."""
    conn = get_db()
    article = conn.execute("""SELECT a.*, c.nom as container_nom, c.code as container_code
        FROM articles a LEFT JOIN containers c ON a.container_id=c.id
        WHERE a.id=? AND a.actif=1""",(id,)).fetchone()
    fournisseurs = conn.execute("SELECT nom FROM fournisseurs WHERE actif=1 ORDER BY nom").fetchall()
    conn.close()
    if not article:
        return render_template('mobile_article_not_found.html', id=id)
    return render_template('mobile_reception.html', article=article, fournisseurs=fournisseurs)

@app.route('/scan/valider-reception/<id>', methods=['POST'])
@login_required
def scan_valider_reception(id):
    """Valider une réception depuis le scan mobile."""
    conn = get_db()
    article = conn.execute("SELECT * FROM articles WHERE id=? AND actif=1",(id,)).fetchone()
    if not article:
        conn.close()
        return render_template('mobile_erreur.html', msg="Article introuvable")
    
    quantite = int(request.form.get('quantite', 1))
    fournisseur = request.form.get('fournisseur', '')
    
    if quantite <= 0:
        conn.close()
        return render_template('mobile_erreur.html', msg="Quantité invalide")
    
    from datetime import date as dt
    numero = get_next_numero('bons_reception','numero','BR-')
    s_avant = article['stock']
    s_apres = s_avant + quantite
    
    conn.execute("""INSERT INTO bons_reception
        (numero,date_reception,fournisseur,num_bl,article_id,qte_commandee,
         qte_recue,prix_unitaire,commentaire,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",(
        numero, dt.today().isoformat(),
        fournisseur, '',
        id, 0, quantite, article['prix_achat'],
        'Réception via scan mobile', session.get('user_id'),
    ))
    conn.execute("UPDATE articles SET stock=? WHERE id=?",(s_apres, id))
    log_mouvement(conn,'RECEPTION',id,quantite,numero,
        s_avant,s_apres,article['container_id'],0,
        f"Scan mobile — {fournisseur}")
    conn.commit()
    conn.close()
    
    return render_template('mobile_succes_reception.html',
        article=article, quantite=quantite,
        nouveau_stock=s_apres, numero=numero)
if __name__ == '__main__':
    app.run(debug=False)
