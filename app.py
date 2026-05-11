from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3, os, hashlib
from datetime import datetime, date

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'stocketf2026CN')
DATABASE = os.environ.get('DATABASE_PATH', 'stocketf.db')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_etat_stock(stock, stock_min, stock_alerte):
    if stock == 0: return 'RUPTURE'
    elif stock <= stock_min: return 'CRITIQUE'
    elif stock <= stock_alerte: return 'ALERTE'
    else: return 'OK'

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
        chantier_id INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        c.execute("INSERT OR IGNORE INTO utilisateurs (nom,email,password_hash,role) VALUES (?,?,?,?)", u)

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
    ]
    for f in familles:
        c.execute("INSERT OR IGNORE INTO familles (nom,icone,couleur) VALUES (?,?,?)", f)

    # Containers
    containers = [
        ('Container BLEU','BLEU','C-001','EPI, Protection individuelle, Outillage','Base arrière',0,'ACTIF'),
        ('Container 5','C5','C-002','Abrasifs, Disques, Éclairage','Base arrière',0,'ACTIF'),
        ('Container 3','C3','C-003','Fixations, Visserie, Ferroviaire','Base arrière',0,'ACTIF'),
        ('Container 9','C9','C-004','Matériaux, Géotextiles, Produits','Base arrière',0,'ACTIF'),
        ('Container Fabrice','FABRICE','C-005','Outillage Manuel, Sangles','Base arrière',0,'ACTIF'),
    ]
    for ct in containers:
        c.execute("INSERT OR IGNORE INTO containers (nom,code,numero,description,emplacement,chantier_id,statut) VALUES (?,?,?,?,?,?,?)", ct)

    # Chantiers
    chantiers = [
        ('Chantier A - Zone 1','CH-001','Zone industrielle Nord','Martin J.','2025-01-01','2025-12-31','ACTIF',50000),
        ('Chantier A - Zone 2','CH-002','Zone industrielle Nord','Dupont P.','2025-02-01','2025-12-31','ACTIF',35000),
        ('Chantier B','CH-003','Gare centrale','Bernard L.','2025-01-15','2025-10-31','ACTIF',80000),
        ('Chantier C','CH-004','Voie ferrée km 42','Martin J.','2025-03-01','2025-09-30','ACTIF',60000),
        ('Base arrière','CH-005','Dépôt principal','Admin','2025-01-01','2026-12-31','ACTIF',0),
    ]
    for ch in chantiers:
        c.execute("INSERT OR IGNORE INTO chantiers (nom,code,adresse,chef,date_debut,date_fin,statut,budget) VALUES (?,?,?,?,?,?,?,?)", ch)

    # 348 articles réels — 5 containers
    articles = [
        ('ART-001','Protection Individuelle','Gants anticoupure taille 10','WE23-5313G','Honeywell',1,'','PAQUET',1,0.0,'',34,5,10,0,''),
        ('ART-002','Protection Individuelle','Gants anticoupure taille 9','WE23-5113G','Honeywell',1,'','PAQUET',1,0.0,'',15,5,10,0,''),
        ('ART-003','Protection Individuelle','Gants anticoupure 13G taille 10','WE23-5313G-10','Honeywell Workeasy',1,'','UNITE',1,0.0,'',25,5,10,0,''),
        ('ART-004','Protection Individuelle','Gants anticoupure 13G taille 9','WE23-5313G-9','Honeywell Workeasy',1,'','UNITE',1,0.0,'',21,5,10,0,''),
        ('ART-005','Protection Individuelle','Gant jetable EN ISO 374-1 taille XL','','Würth',1,'','PAQUET',1,0.0,'',2,2,4,0,''),
        ('ART-006','Protection Individuelle','Gant jetable EN ISO 374-1 taille L','','',1,'','PAQUET',1,0.0,'',1,2,3,0,''),
        ('ART-007','Protection Individuelle','Gants de soudeur taille 9','W-110 EN 388/407/12477A','',1,'','PAIRE',1,0.0,'',4,2,5,0,''),
        ('ART-008','Protection Individuelle','Gants de soudeur taille 10','W-110 EN 388/407/12477A','',1,'','PAIRE',1,0.0,'',15,2,5,0,''),
        ('ART-009','Protection Individuelle','Gants jetables orange/noir L','899470122','',1,'','UNITE',1,0.0,'',4,2,5,0,''),
        ('ART-010','Protection Individuelle','Gants cuir blanc T11','','',1,'','PAQUET',1,0.0,'',13,2,5,0,''),
        ('ART-011','Protection Individuelle','Gant soudeur Blue Welder','P702LYQ / 66581276','Prolians',1,'','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-012','Protection Individuelle','Gants protection chimique','','',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-013','Protection Individuelle','Gants hiver Ninja T10','','',1,'','PAQUET',1,0.0,'',28,3,8,0,''),
        ('ART-014','Protection Individuelle','Casque anti-bruit VeriShield VS 100DH','','Honeywell',1,'','UNITE',1,0.0,'',37,10,20,0,''),
        ('ART-015','Protection Individuelle','Casque anti-bruit ancien modèle','Earline 31020','',1,'','UNITE',1,0.0,'',1,0,1,0,'Ancien stock'),
        ('ART-016','Protection Individuelle','Bouchons d`oreille','0899 300 338','',1,'','PAQUET',1,0.0,'',91,10,20,0,''),
        ('ART-017','Protection Individuelle','Masque prêt à l`emploi ABEK1P3RD','','Opsial',1,'','UNITE',1,0.0,'',8,5,10,0,''),
        ('ART-018','Protection Individuelle','Masque Air Fit jetable FFP3','','Opsial',1,'','BOITE',1,0.0,'',17,3,6,0,''),
        ('ART-019','Protection Individuelle','Filtre de remplacement SPR316ODUA','','Opsial',1,'','BOITE',1,0.0,'',5,2,4,0,''),
        ('ART-020','Protection Individuelle','Lunettes de tronçonnage jaunes SPECTN12W','','Bollé',1,'','BOITE',1,0.0,'',6,1,3,0,''),
        ('ART-021','Protection Individuelle','Lunettes de tronçonnage bleues BLAPSI','','Bollé',1,'','BOITE',1,0.0,'',1,1,2,0,''),
        ('ART-022','Protection Individuelle','Lunettes sécurité RUSHPPSI blanches','','Bollé',1,'','BOITE',1,0.0,'',45,5,10,0,''),
        ('ART-023','Protection Individuelle','Lunettes sécurité RUSHPPSF solaires','','Bollé',1,'','BOITE',1,0.0,'',8,2,5,0,''),
        ('ART-024','Protection Individuelle','Lunettes sur casque EVOSPEC','','JSP',1,'','UNITE',1,0.0,'',26,5,10,0,''),
        ('ART-025','Protection Individuelle','Lunettes sécurité ancien stock','','Bollé / Opsial',1,'','UNITE',1,0.0,'',29,0,0,0,'Ancien stock non utilisé'),
        ('ART-026','Protection Individuelle','Guêtres de tronçonnage cuir','TSV00008','',1,'','PAIRE',1,0.0,'',0,2,5,0,'À COMMANDER'),
        ('ART-027','Vêtements de travail','Gilets 3XL encadrant','','',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-028','Vêtements de travail','Gilets XL','','',1,'','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-029','Vêtements de travail','Gilets L','','',1,'','UNITE',1,0.0,'',10,3,5,0,''),
        ('ART-030','Vêtements de travail','Gilets M','','',1,'','UNITE',1,0.0,'',1,2,4,0,''),
        ('ART-031','Vêtements de travail','Gilets S','','',1,'','UNITE',1,0.0,'',5,1,3,0,''),
        ('ART-032','Vêtements de travail','Combinaison protection LG orange','','',1,'','UNITE',1,0.0,'',1,2,4,0,''),
        ('ART-033','Vêtements de travail','Combinaison protection MD orange','','',1,'','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-034','Vêtements de travail','Combinaison protection XL orange','','',1,'','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-035','Vêtements de travail','Combinaison protection 3XL orange','','',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-036','Vêtements de travail','Combinaison protection LG blanche','','',1,'','UNITE',1,0.0,'',22,5,10,0,'Stock aussi dans autre conteneur'),
        ('ART-037','Vêtements de travail','Ensemble de pluie XL','','Opsial',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-038','Vêtements de travail','Chauffrettes à main','Handwormer','',1,'','UNITE',1,0.0,'',2,2,4,0,''),
        ('ART-039','Abrasifs & Disques','Disque tronçonneuse 150x2x22,23 acier','','Rhodius',1,'','BOITE',1,0.0,'',4,2,5,0,''),
        ('ART-040','Abrasifs & Disques','Disque 125x1,6x22,23 métal','','Tyrolit',1,'','BOITE',1,0.0,'',3,2,5,0,''),
        ('ART-041','Abrasifs & Disques','Disque à lamelle 125x22,23 métal','','Tyrolit',1,'','BOITE',1,0.0,'',4,2,4,0,''),
        ('ART-042','Abrasifs & Disques','Disque acier/inox 125x6,4x22,23','113309633','Opsial',1,'','BOITE',1,0.0,'',1,1,3,0,''),
        ('ART-043','Abrasifs & Disques','Disque 115x1,6x22,23 métal','','Tyrolit',1,'','BOITE',1,0.0,'',4,2,5,0,''),
        ('ART-044','Abrasifs & Disques','Disque 125x6,4x22,2','69025145','Xhander',1,'','BOITE',1,0.0,'',9,2,5,0,''),
        ('ART-045','Abrasifs & Disques','Rouleau de ponçage 40x25mm 25M','','Rhodius',1,'','BOITE',1,0.0,'',1,1,2,0,''),
        ('ART-046','Abrasifs & Disques','Lames de scie métal/bois 4mm 32145','','Erko',1,'','PAQUET',1,0.0,'',10,3,6,0,''),
        ('ART-047','Abrasifs & Disques','Lame de scie bi-métal 300mm 24T','','Starrett',1,'','UNITE',1,0.0,'',8,3,6,0,''),
        ('ART-048','Abrasifs & Disques','Bâche de soudure anti-feu 200x200cm','','Thetis',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-049','Outillage Manuel','Massette 1,25 kg','68600693','Xhander',1,'','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-050','Outillage Manuel','Massette sans rebond 40mm','','Facom',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-051','Outillage Manuel','Marteau Expert 40mm 1020g','','Expert',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-052','Outillage Manuel','Taloche de maçon 270x180','','PV Vinmer',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-053','Outillage Manuel','Truelle 22cm','','',1,'','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-054','Outillage Manuel','Truelle petite','0993943163','',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-055','Outillage Manuel','Truelle 20cm','','',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-056','Outillage Manuel','Lame cutter SECUMAX Blade 3550','','Martor',1,'','UNITE',1,0.0,'',15,5,10,0,''),
        ('ART-057','Outillage Manuel','Lame cutter 0715 66 02','','',1,'','UNITE',1,0.0,'',5,3,6,0,''),
        ('ART-058','Outillage Manuel','Cutter à bec de perroquet SECUMAX 350','','Martor',1,'','UNITE',1,0.0,'',15,3,6,0,''),
        ('ART-059','Outillage Manuel','Cutter Facom','','Facom',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-060','Outillage Manuel','Pinceau d`angle 40x24x15','40 24 15','',1,'','UNITE',1,0.0,'',12,2,5,0,''),
        ('ART-061','Outillage Manuel','Brosse métallique 5252','5252','',1,'','UNITE',1,0.0,'',30,5,10,0,''),
        ('ART-062','Outillage Manuel','Brosse métallique Würth','071555900','Würth',1,'','UNITE',1,0.0,'',18,5,10,0,''),
        ('ART-063','Outillage Manuel','Brosse métallique MEC&Rail','21.402','MEC&Rail',1,'','UNITE',1,0.0,'',6,3,6,0,''),
        ('ART-064','Outillage Manuel','Tenaille 220mm','OPS38325698','Opsial',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-065','Outillage Manuel','Burin mécanicien','0714 630 05','Würth',1,'','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-066','Outillage Manuel','Écouvillon métallique HIT-RB 18','#336551','Hilti',1,'','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-067','Outillage Manuel','Écouvillon métallique HIT-RB 16','#336550','Hilti',1,'','UNITE',1,0.0,'',1,1,3,0,''),
        ('ART-068','Outillage Manuel','Écouvillon métallique HIT-RB 14','#336549','Hilti',1,'','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-069','Outillage Manuel','Écouvillon métallique HIT-RB 12','#336548','Hilti',1,'','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-070','Outillage Manuel','Coffret tournevis','','',1,'','UNITE',1,0.0,'',1,1,1,0,'Partiellement remplie'),
        ('ART-071','Outillage Manuel','Tournevis précisions/divers','','',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-072','Outillage Manuel','Règle 20cm SAM 781-2','','SAM',1,'','UNITE',1,0.0,'',6,2,3,0,''),
        ('ART-073','Outillage Manuel','Règle 15cm','','',1,'','UNITE',1,0.0,'',10,2,3,0,''),
        ('ART-074','Outillage Manuel','Clé 13 Opsial','','Opsial',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-075','Outillage Manuel','Clé 13 SAM','','SAM',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-076','Outillage Manuel','Clé 13 Facom','','Facom',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-077','Outillage Manuel','Clé 13 MOB','','MOB',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-078','Outillage Manuel','Clé 16 à pipe SAM','','SAM',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-079','Outillage Manuel','Clé 17 Xhander','','Xhander',1,'','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-080','Outillage Manuel','Clé 17 Facom','','Facom',1,'','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-081','Outillage Manuel','Clé 17 à pipe SAM','','SAM',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-082','Outillage Manuel','Clé 19 plate Zebra','','Zebra',1,'','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-083','Outillage Manuel','Clé 19 à cliquer Xhander','','Xhander',1,'','UNITE',1,0.0,'',16,2,4,0,''),
        ('ART-084','Outillage Manuel','Clé à molette 250mm','','SAM',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-085','Outillage Manuel','Clé 21 plate SAM','','SAM',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-086','Outillage Manuel','Clé 22 plate SAM','','SAM',1,'','UNITE',1,0.0,'',5,1,2,0,''),
        ('ART-087','Outillage Manuel','Clé 22 plate Zebra','','Zebra',1,'','UNITE',1,0.0,'',6,1,2,0,''),
        ('ART-088','Outillage Manuel','Clé 24 plate Opsial','','Opsial',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-089','Outillage Manuel','Clé 26 plate SAM','','SAM',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-090','Outillage Manuel','Clé 28 plate SAM','','SAM',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-091','Outillage Manuel','Clé à molette 15` Würth','','Würth',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-092','Outillage Manuel','Clé 30 plate SAM','','SAM',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-093','Outillage Manuel','Clé 32 plate SAM/Zebra','','SAM / Zebra',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-094','Outillage Manuel','Clé 36 plate Zebra','','Zebra',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-095','Outillage Manuel','Clé 41 plate SAM','','SAM',1,'','UNITE',1,0.0,'',5,1,2,0,''),
        ('ART-096','Outillage Manuel','Clé à ergo','','',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-097','Outillage Manuel','Flexible graisse M10x100 300mm','07400300','Algi',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-098','Outillage Manuel','Douille 23','N00087','',1,'','UNITE',1,0.0,'',6,1,2,0,''),
        ('ART-099','Outillage Manuel','Douille 30 Facom','','Facom',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-100','Outillage Manuel','Douille 16 Xhander','','Xhander',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-101','Outillage Manuel','Douille 13 SI-S 1/2`','2070389','',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-102','Outillage Manuel','Pointeaux PP1','PP1 6001131','',1,'','UNITE',1,0.0,'',0,1,3,0,'À vérifier'),
        ('ART-103','Outillage Manuel','Pointeaux PPL1','PPL1','',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-104','Outillage Manuel','Pointeaux PPL2','PPL2','',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-105','Outillage Manuel','Elingue 4M 2T','0713 50 28','Würth',1,'','UNITE',1,0.0,'',11,3,6,0,''),
        ('ART-106','Outillage Manuel','Elingue 2M 3T','0713 50 34','Würth',1,'','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-107','Outillage Manuel','Elingue 3M 4T','0713 50 411','Würth',1,'','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-108','Outillage Manuel','Chaîne 25M 6mm','050 407','',1,'','BOITE',1,0.0,'',2,1,2,0,''),
        ('ART-109','Outillage Manuel','Crochet de sécurité en M/W','','',1,'','UNITE',1,0.0,'',11,3,6,0,''),
        ('ART-110','Outillage Électroportatif','Tronçonneuse à rail MTZ modèle 350AS/400AS','','',1,'','UNITE',1,0.0,'',3,1,2,0,'Avec guide'),
        ('ART-111','Outillage Électroportatif','Tronçonneuse Stihl TS440','','Stihl',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-112','Outillage Électroportatif','Meuleuse d`angle électrique 230mm EWS 24-230-T','','Würth',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-113','Outillage Électroportatif','Meuleuse d`angle Milwaukee M18 FLAG230XPDB','','Milwaukee',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-114','Outillage Électroportatif','Boulonneuse FIW2F12-0X','','Milwaukee',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-115','Outillage Électroportatif','Visseuse Makita DDF453','','Makita',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-116','Outillage Électroportatif','Perforateur TE 30-ATC/AVR','','Hilti',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-117','Outillage Électroportatif','Pince d`injection sans fil HDE 500-022','','Hilti',1,'','UNITE',1,0.0,'',4,1,2,0,'Sur batterie'),
        ('ART-118','Outillage Électroportatif','Pince à injection manuelle Hilti MD 2500','','Hilti',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-119','Outillage Électroportatif','Outil hydraulique de sertissage','','Cembre',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-120','Outillage Électroportatif','Percuteur HS-SC-3000','HS-SC-3000','Hilti',1,'','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-121','Outillage Électroportatif','Guide chaîne Stihl 3003-000-5213','','Stihl',1,'','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-122','Outillage Électroportatif','Guide chaîne Stihl 3003-000-9431','','Stihl',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-123','Outillage Électroportatif','Chaîne 3/8 1,6mm 60M Rapid Micro','','',1,'','UNITE',1,0.0,'',10,3,5,0,''),
        ('ART-124','Outillage Électroportatif','Enrouleur air comprimé 15M','','Prevost',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-125','Outillage Électroportatif','Enrouleur électrique 40M','','Opsial',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-126','Outillage Électroportatif','Souffleur à batterie Milwaukee','','Milwaukee',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-127','Outillage Électroportatif','Pompe soufflante #60579','AUSBLASP-UMPE','',1,'','UNITE',1,0.0,'',5,1,2,0,''),
        ('ART-128','Outillage Électroportatif','Mélangeur HIT-RE-M','#337111','Hilti',1,'','UNITE',1,0.0,'',52,5,10,0,''),
        ('ART-129','Outillage Électroportatif','Porte-cartouche HIT-CR 500','#2007059','Hilti',1,'','UNITE',1,0.0,'',4,2,3,0,''),
        ('ART-130','Batteries & Piles','Batterie M18 FB8 Milwaukee','4932 4921 31','Milwaukee',1,'','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-131','Batteries & Piles','Batterie Cembre LIHD 36V 8Ah','','Cembre',1,'','UNITE',1,0.0,'',5,2,3,0,'Rechargeable'),
        ('ART-132','Batteries & Piles','Batterie Hilti B144/2,6 14,4V LI-ION','9857536','Hilti',1,'','UNITE',1,0.0,'',2,2,3,0,''),
        ('ART-133','Batteries & Piles','Batterie Hilti B 22-55 LI-ION','','Hilti',1,'','UNITE',1,0.0,'',3,2,3,0,''),
        ('ART-134','Batteries & Piles','Batterie 6V Varta 435/4LR25-2','','Varta',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-135','Batteries & Piles','Chargeur batterie Hilti C4/36-90','','Hilti',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-136','Batteries & Piles','Chargeur batterie Hilti C4/36-350','','Hilti',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-137','Batteries & Piles','Pile AAA LR3 Würth','','Würth',1,'','PAQUET',1,0.0,'',22,3,6,0,''),
        ('ART-138','Batteries & Piles','Pile LR06 Procel','','Procel',1,'','UNITE',1,0.0,'',15,10,20,0,''),
        ('ART-139','Batteries & Piles','Pile AAA LR3 Varta','','Varta',1,'','UNITE',1,0.0,'',360,50,100,0,''),
        ('ART-140','Batteries & Piles','Pile GLR20 6LR20 Cecasa SNCF','0.816.8652','Cecasa',1,'','UNITE',1,0.0,'',3,2,4,0,'Pour lanternes'),
        ('ART-141','Batteries & Piles','Pile PCFF-200 lanterne de queue','0.816.8651','MFI',1,'','UNITE',1,0.0,'',2,2,4,0,'Pour lanternes'),
        ('ART-142','Éclairage & Électricité','Projecteur LED 10 000lm','','Xhander',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-143','Éclairage & Électricité','Projecteur LED magnétique Sydney','LWK0033','LED Work',1,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-144','Éclairage & Électricité','Projecteur batterie 6V Varta BL40','','Varta',1,'','UNITE',1,0.0,'',4,1,2,0,'2 unités x2'),
        ('ART-145','Éclairage & Électricité','Projecteur électrique Airstar','6530044','Airstar',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-146','Éclairage & Électricité','Lampe frontale H7R Core','','Ledlenser',1,'','UNITE',1,0.0,'',16,5,10,0,''),
        ('ART-147','Éclairage & Électricité','Lampe frontale Xlander','','Xhander',1,'','UNITE',1,0.0,'',4,2,5,0,''),
        ('ART-148','Éclairage & Électricité','Visilité LED lumineux AHV 860','AHV 860 000 800','JSP',1,'','UNITE',1,0.0,'',8,3,6,0,''),
        ('ART-149','Éclairage & Électricité','Clips crochets lampe (sac de 4)','E04350','',1,'','SAC',1,0.0,'',44,5,10,0,''),
        ('ART-150','Éclairage & Électricité','Rallonge 10M avec 4 prises','','',1,'','UNITE',1,0.0,'',4,2,3,0,''),
        ('ART-151','Éclairage & Électricité','Contacteur Legrand','4.125.45','Legrand',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-152','Éclairage & Électricité','Ampoule Osram 60W 230V','','Osram',1,'','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-153','Éclairage & Électricité','Chauffage portable 3kW','','',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-154','Mesure & Traçage','Mètre 3M Xhander','','Xhander',1,'','UNITE',1,0.0,'',39,10,15,0,''),
        ('ART-155','Mesure & Traçage','Mètre 5M Xhander','','Xhander',1,'','UNITE',1,0.0,'',40,10,15,0,''),
        ('ART-156','Mesure & Traçage','Mètre 8M Stanley','','Stanley',1,'','UNITE',1,0.0,'',15,5,8,0,''),
        ('ART-157','Mesure & Traçage','Mètre 8M Xhander','','Xhander',1,'','UNITE',1,0.0,'',31,5,8,0,''),
        ('ART-158','Mesure & Traçage','Mètre 10M Stanley','','Stanley',1,'','UNITE',1,0.0,'',7,3,5,0,''),
        ('ART-159','Mesure & Traçage','Décamètre 30M','0714 641 653','',1,'','BOITE',1,0.0,'',3,1,2,0,''),
        ('ART-160','Mesure & Traçage','Jauge de précision N°071351 42','071351 42','',1,'','UNITE',1,0.0,'',0,1,1,0,'À COMMANDER'),
        ('ART-161','Mesure & Traçage','Thermomètre à rail 310.014','310.014','',1,'','UNITE',1,0.0,'',9,2,4,0,''),
        ('ART-162','Mesure & Traçage','Support pour laser rotatif','','',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-163','Mesure & Traçage','Marqueur blanc','967910303','',1,'','UNITE',1,0.0,'',8,3,6,0,''),
        ('ART-164','Mesure & Traçage','Ruban à mesurer 30M','0714 641 653','',1,'','BOITE',1,0.0,'',3,1,2,0,''),
        ('ART-165','Nettoyage & Hygiène','Lingette nettoyante mains (seau 72)','','Scrubs',1,'','BOITE',1,0.0,'',11,3,5,0,''),
        ('ART-166','Nettoyage & Hygiène','Lingette imprégnée universelle','0893 936 70','',1,'','BOITE',1,0.0,'',11,3,5,0,''),
        ('ART-167','Nettoyage & Hygiène','Crème lavante 4L Arma','','Arma',1,'','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-168','Nettoyage & Hygiène','Nettoyant lubrifiant spécial contact','','KF',1,'','UNITE',1,0.0,'',22,5,10,0,''),
        ('ART-169','Conditionnement & Rangement','Raccords express cannelé 19mm','P019','Boutte / Würth',1,'','UNITE',1,0.0,'',17,5,10,0,''),
        ('ART-170','Conditionnement & Rangement','Rubalise','','',1,'','ROULEAU',1,0.0,'',21,5,10,0,''),
        ('ART-171','Conditionnement & Rangement','Porte affiche','','',1,'','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-172','Conditionnement & Rangement','Jerrican métallique 10L vert','','',1,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-173','Conditionnement & Rangement','Scotch gris','','',1,'','UNITE',1,0.0,'',1,2,4,0,''),
        ('ART-174','Conditionnement & Rangement','Papier blanc format A3','','',1,'','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-175','Équipements Spéciaux','Résine époxy HIT-RE 500 V4','A5','Hilti',1,'','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-176','Équipements Spéciaux','Gabarit perçage rail APED135/165','APED135/165','',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-177','Équipements Spéciaux','Gabarit perçage SPA/1 U60/U50','','',1,'','BOITE',1,0.0,'',1,1,1,0,''),
        ('ART-178','Équipements Spéciaux','Gabarit perçage SPA-UIC60-U50-3','','',1,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-179','Équipements Spéciaux','Presse hydraulique d`extrusion HTEPF-EX','T.391.0269','',1,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-180','Équipements Spéciaux','Extrudeurs OG10.5','OG10.5','',1,'','UNITE',1,0.0,'',13,3,6,0,''),
        ('ART-181','Équipements Spéciaux','Bride thermique TH034','6001994','',1,'','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-182','Équipements Spéciaux','Cadenas à code Abus 145/40','','Abus',1,'','UNITE',1,0.0,'',0,2,4,0,'À COMMANDER'),
        ('ART-183','Équipements Spéciaux','Cadenas à code Abus Nautic 180','','Abus',1,'','UNITE',1,0.0,'',0,2,4,0,'À COMMANDER'),
        ('ART-184','Abrasifs & Disques','Disque 230x3,2 meule tronc déport A30S','00573841','Xhander',2,'A2','BOITE',1,0.0,'',6,2,4,0,''),
        ('ART-185','Abrasifs & Disques','Disque à tronçonner 360mm','','',2,'A3','BOITE',1,0.0,'',138,10,20,0,''),
        ('ART-186','Abrasifs & Disques','Disque 300mm Pferd','','Pferd',2,'A3','BOITE',1,0.0,'',9,3,6,0,''),
        ('ART-187','Abrasifs & Disques','Disque Makita 300x3,5x20mm','','Makita',2,'A3','BOITE',1,0.0,'',0,2,5,0,'À COMMANDER'),
        ('ART-188','Abrasifs & Disques','Disque 320x3,2x22 Xhander','','Xhander',2,'A3','BOITE',1,0.0,'',0,2,4,0,'À COMMANDER'),
        ('ART-189','Abrasifs & Disques','Disque 230x2,5x22,3 Tyrolit','','Tyrolit',2,'A2','BOITE',1,0.0,'',2,2,4,0,''),
        ('ART-190','Lubrifiants & Produits','Nettoyant freins 5L','0890 108 715','',2,'A3','BIDON',1,0.0,'',0,1,2,0,'Rupture'),
        ('ART-191','Lubrifiants & Produits','Nettoyant freins 20L','0890 108 720','',2,'AU SOL','BIDON',1,0.0,'',1,1,2,0,''),
        ('ART-192','Lubrifiants & Produits','Nettoyant freins aérosol','0890 108 7','',2,'A2','UNITE',1,0.0,'',38,5,10,0,''),
        ('ART-193','Lubrifiants & Produits','Solvant vert détergent dégraissant 5L','','Haleco',2,'A3','BIDON',1,0.0,'',2,1,2,0,''),
        ('ART-194','Lubrifiants & Produits','Huile filante pour chaîne 5L','','',2,'A3','BIDON',1,0.0,'',0,1,2,0,'Rupture'),
        ('ART-195','Lubrifiants & Produits','Huile de coupe soluble NG 5L','0893 120 105','',2,'A3','BIDON',1,0.0,'',1,1,2,0,''),
        ('ART-196','Lubrifiants & Produits','Huile de coupe à diluer LUB21 5L','','KF',2,'A3','BIDON',1,0.0,'',11,2,4,0,''),
        ('ART-197','Lubrifiants & Produits','Huile de coupe KF LUB COUP II 5L','','KF',2,'A4','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-198','Lubrifiants & Produits','Huile chaîne 5L Würth','089305005','Würth',2,'','BIDON',1,0.0,'',5,2,4,0,''),
        ('ART-199','Lubrifiants & Produits','Huile 15W40 Rubia Works 20L','','',2,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-200','Lubrifiants & Produits','Liquide de refroidissement LR21','8172308','',2,'AU SOL','UNITE',1,0.0,'',0,1,1,0,'Stock bas'),
        ('ART-201','Lubrifiants & Produits','Graisse multifonction Berrulub ECO Super 2','','',2,'A4','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-202','Lubrifiants & Produits','Lubrifiant multifonction Stralub 30L','','Siprotec',2,'AU SOL','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-203','Lubrifiants & Produits','Dégrippant 20L','0890 3001','',2,'AU SOL','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-204','Lubrifiants & Produits','Nettoyant pour sol garage industriel 20L','','Natura Sol',2,'AU SOL','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-205','Lubrifiants & Produits','Kit absorbant','0899 900 300','',2,'A3','UNITE',1,0.0,'',11,3,5,0,''),
        ('ART-206','Lubrifiants & Produits','Sable absorbant 10kg','0890 61','',2,'A4','SAC',1,0.0,'',12,3,6,0,''),
        ('ART-207','Lubrifiants & Produits','Gel hydroalcoolique Bactimains','','Garcin Bactinyl',2,'A4','UNITE',1,0.0,'',0,1,2,0,'Stock bas'),
        ('ART-208','Conditionnement & Rangement','Pulvérisateur 18L','','Mesto',2,'A1','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-209','Conditionnement & Rangement','Pulvérisateur 5L','','Xhander',2,'A2','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-210','Conditionnement & Rangement','Pompe de transvasement à levier','891621','',2,'A2','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-211','Conditionnement & Rangement','Sac poubelle noir 100L','','',2,'A2','ROULEAU',1,0.0,'',10,3,5,0,''),
        ('ART-212','Conditionnement & Rangement','Sac poubelle transparent 110L','','',2,'A2','ROULEAU',1,0.0,'',8,2,4,0,''),
        ('ART-213','Conditionnement & Rangement','Chiffons','','',2,'A2','SAC',1,0.0,'',7,2,4,0,''),
        ('ART-214','Conditionnement & Rangement','Chiffon absorbant multi-usage','0899 700 450','',2,'A2','PAQUET',1,0.0,'',3,2,4,0,''),
        ('ART-215','Conditionnement & Rangement','Sac à gravat 50L Opsial','0899 910 911','Opsial',2,'A2','UNITE',1,0.0,'',150,20,50,0,''),
        ('ART-216','Conditionnement & Rangement','Sac de prélèvement 500x800','','G.Cogné & Fils',2,'','UNITE',1,0.0,'',300,50,100,0,''),
        ('ART-217','Conditionnement & Rangement','Essuie-main','','',2,'A2 + AU SOL','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-218','Conditionnement & Rangement','Big Bag 90x90x90','','',2,'AU SOL','UNITE',1,0.0,'',41,5,10,0,''),
        ('ART-219','Conditionnement & Rangement','Big Bag 90x90x110','','',2,'AU SOL','UNITE',1,0.0,'',40,5,10,0,''),
        ('ART-220','Conditionnement & Rangement','Film transparent','','',2,'A2','ROULEAU',1,0.0,'',0,2,4,0,'À COMMANDER'),
        ('ART-221','Conditionnement & Rangement','Cosse à connection Bariot','79520895','Bariot',2,'','BOITE',1,0.0,'',11,2,4,0,''),
        ('ART-222','Vêtements de travail','Combinaison blanche taille LG','','',2,'A3','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-223','Équipements Spéciaux','Appareil de passage à niveau mod. 01122300','01122300','',2,'AU SOL','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-224','Conditionnement & Rangement','Câble électrique','','',2,'AU SOL','ROULEAU',1,0.0,'',1,1,1,0,''),
        ('ART-225','Conditionnement & Rangement','Fourreaux transparents','','',2,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-226','Conditionnement & Rangement','Panneaux STOP','','',2,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-227','Conditionnement & Rangement','Poubelle de bureau','','',2,'AU SOL','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-228','Conditionnement & Rangement','Croix signalisation','','',2,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-229','Lubrifiants & Produits','Graisse 4T sur palette (6 bidons/carton)','','',2,'SUR PALETTE','UNITE',1,0.0,'',24,5,10,0,''),
        ('ART-230','Lubrifiants & Produits','Graisse 2T sur palette (6 bidons/carton)','','',2,'SUR PALETTE','UNITE',1,0.0,'',21,5,10,0,''),
        ('ART-231','Outillage Électroportatif','Souffleur à batterie Milwaukee','','Milwaukee',2,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-232','Fixations & Visserie','Douille 13,5 liaison électrique rail AR66','AR 66','Cembre',3,'A1','UNITE',1,0.0,'',19,10,20,0,''),
        ('ART-233','Fixations & Visserie','Olive KIT AR266D-16,5-12','KIT AR266D-16,5-12','Cembre',3,'A2','BOITE',1,0.0,'',10,3,5,0,''),
        ('ART-234','Fixations & Visserie','Boulon M10x70 Würth','0057 91070','Würth',3,'A2','BOITE',1,0.0,'',4,2,4,0,''),
        ('ART-235','Fixations & Visserie','Boulon M10x60 Würth','0057 910 60','Würth',3,'A4','BOITE',1,0.0,'',8,3,6,0,''),
        ('ART-236','Fixations & Visserie','Boulon M10x60 Norme','','Norme',3,'A4','BOITE',1,0.0,'',3,2,4,0,''),
        ('ART-237','Fixations & Visserie','Boulon M10x60 Bossard','','Bossard',3,'A4','BOITE',1,0.0,'',17,3,6,0,''),
        ('ART-238','Fixations & Visserie','Boulon M16x45 Würth','0083 16 45','Würth',3,'A2','UNITE',1,0.0,'',80,20,40,0,''),
        ('ART-239','Fixations & Visserie','Boulon M10x60 Norme BN21200','BN21200','Bossards',3,'A2','UNITE',1,0.0,'',0,10,20,0,'À commander'),
        ('ART-240','Fixations & Visserie','Boulon M14x50','','',3,'','UNITE',1,0.0,'',19,5,10,0,''),
        ('ART-241','Fixations & Visserie','Vis BTR M16x2,2','','',3,'A2','UNITE',1,0.0,'',0,5,10,0,'À commander'),
        ('ART-242','Fixations & Visserie','Vis BTR 20x140 clé 17','','',3,'A2','UNITE',1,0.0,'',0,5,10,0,'À commander'),
        ('ART-243','Fixations & Visserie','Vis 6x60/37mm','17736060','Würth',3,'A2','BOITE',1,0.0,'',2,1,3,0,''),
        ('ART-244','Fixations & Visserie','Vis 5,5x60/24 TX25','','',3,'A2','BOITE',1,0.0,'',5,1,3,0,''),
        ('ART-245','Fixations & Visserie','Vis M10x60','005791060','Würth',3,'A3','BOITE',1,0.0,'',0,3,6,0,'À commander'),
        ('ART-246','Fixations & Visserie','Vis entretoise M10x70','','Index',3,'B3','UNITE',1,0.0,'',15,3,6,0,'À trappe'),
        ('ART-247','Fixations & Visserie','Vis + mèche','','',3,'B3','UNITE',1,0.0,'',90,10,20,0,''),
        ('ART-248','Fixations & Visserie','Écrou M10x150 Lanfranco','ERM100150ZHST02','J.Lanfranco',3,'A2','BOITE',1,0.0,'',0,3,6,0,'À commander'),
        ('ART-249','Fixations & Visserie','Écrou zingué M10 Bossard','','Bossard',3,'A2','BOITE',1,0.0,'',40,5,10,0,''),
        ('ART-250','Fixations & Visserie','Écrou autofreiné M10 Würth','0391 10','Würth',3,'A2','UNITE',1,0.0,'',34,10,20,0,''),
        ('ART-251','Fixations & Visserie','Écrou M14 Würth','','Würth',3,'','UNITE',1,0.0,'',19,5,10,0,''),
        ('ART-252','Fixations & Visserie','Écrou hexagonal combiné M10 Bossards','14F45000009','Bossards',3,'A2','BOITE',1,0.0,'',0,5,10,0,'À commander'),
        ('ART-253','Fixations & Visserie','Vis M16x2,0 PX55','','Würth',3,'','UNITE',1,0.0,'',50,10,20,0,''),
        ('ART-254','Fixations & Visserie','Rondelle M10','D902110','Index',3,'A2','BOITE',1,0.0,'',2,2,4,0,''),
        ('ART-255','Fixations & Visserie','Pointe acier 8x18 5kg','','',3,'A2','BOITE',1,0.0,'',1,1,2,0,''),
        ('ART-256','Fixations & Visserie','Feuillard / cerclage','','Prolian',3,'B2','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-257','Fixations & Visserie','Boucle de serrage (2 petit + 2 grand)','','',3,'B2','BOITE',1,0.0,'',4,1,2,0,''),
        ('ART-258','Fixations & Visserie','Kit cerclage feuillard avec 200 boucles','','Prolian',3,'B2','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-259','Outillage Électroportatif','Couronne forage rapide SP-H B30/430','#2216079','Hilti',3,'A2','UNITE',1,0.0,'',16,3,6,0,''),
        ('ART-260','Outillage Électroportatif','Couronne forage SPX-L BR-F 30/320','2374741','Hilti',3,'A4','BOITE',1,0.0,'',15,3,6,0,''),
        ('ART-261','Outillage Électroportatif','Couronne forage SPX-L BR-F 28/320','2374740','Hilti',3,'A4','BOITE',1,0.0,'',5,2,4,0,''),
        ('ART-262','Outillage Électroportatif','Couronne forage SPX-L B47/320','2374765','Hilti',3,'A2','UNITE',1,0.0,'',3,1,3,0,''),
        ('ART-263','Outillage Électroportatif','Couronne forage diamant BR32/320 SPX-L','2159404','Hilti',3,'A2','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-264','Outillage Électroportatif','Mèche TE-CX 10/17 MP32 SDS Plus','2022052','Hilti',3,'A4','BOITE',1,0.0,'',23,3,6,0,''),
        ('ART-265','Outillage Électroportatif','Fraise 13,5 CY132','CY132','Cembre',3,'A2','UNITE',1,0.0,'',28,10,50,0,''),
        ('ART-266','Outillage Électroportatif','Fraise 23 TCT Rail RAPTR230','RAPTR230/SCRWC23','Doga',3,'A2','UNITE',1,0.0,'',0,10,50,0,'À commander'),
        ('ART-267','Abrasifs & Disques','Brosse décalamineuse diam 203x25,4','','Geismar',3,'B1','UNITE',1,0.0,'',80,10,20,0,''),
        ('ART-268','Abrasifs & Disques','Brosse métallique cylindrique 6000 RPM','','',3,'B1','UNITE',1,0.0,'',18,5,10,0,''),
        ('ART-269','Abrasifs & Disques','Disque centré MSFS 3600 RPM','','',3,'B1','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-270','Abrasifs & Disques','Roue à lamelle 165x50x30 RPM5200 KX310','','Flexovit',3,'B1','UNITE',1,0.0,'',56,10,20,0,''),
        ('ART-271','Abrasifs & Disques','Disque métal 300x3,8x20','','Masterpro',3,'','BOITE',1,0.0,'',0,2,4,0,'À commander'),
        ('ART-272','Abrasifs & Disques','Disque métal 300x3,5x21 Tyrolit','','Tyrolit',3,'A3','BOITE',1,0.0,'',0,2,4,0,'À commander'),
        ('ART-273','Outillage Ferroviaire','Bar écartement Robel','','Robel',3,'B4','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-274','Outillage Ferroviaire','Cric hydraulique Geismar','','Geismar',3,'B4','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-275','Outillage Ferroviaire','Cric manuel Strail','','Strail',3,'B4','UNITE',1,0.0,'',0,1,2,0,'À commander'),
        ('ART-276','Outillage Ferroviaire','Tenaille rail manuel Robel','','Robel',3,'B4','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-277','Outillage Ferroviaire','Pince à rail galet Robel','','Robel',3,'B4','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-278','Outillage Ferroviaire','Tenaille rail manuel (AU SOL)','','',3,'AU SOL','UNITE',1,0.0,'',12,3,6,0,''),
        ('ART-279','Outillage Ferroviaire','Barre à mine lourde','','',3,'AU SOL','UNITE',1,0.0,'',3,1,3,0,''),
        ('ART-280','Outillage Ferroviaire','Barre blanche Fastclip','AE16180/FR','Pandrol',3,'AU SOL','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-281','Outillage Ferroviaire','Barre jaune Fastclip','AE17122/FR','Pandrol',3,'AU SOL','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-282','Outillage Ferroviaire','Maillet Mecarail code 21 266','21 266','Mecarail',3,'AU SOL','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-283','Outillage Ferroviaire','Maillet blanc Halder Supercraft D80/4kg','','Prolian',3,'AU SOL','UNITE',1,0.0,'',10,3,10,0,''),
        ('ART-284','Outillage Ferroviaire','Masse 4kg Xhander','68600731','Xhander / Prolian',3,'AU SOL','UNITE',1,0.0,'',7,2,4,0,''),
        ('ART-285','Outillage Ferroviaire','Pioche','','',3,'AU SOL','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-286','Outillage Ferroviaire','Pince en C','','',3,'AU SOL','UNITE',1,0.0,'',4,2,4,0,''),
        ('ART-287','Outillage Ferroviaire','Pince à talon lourde','','',3,'AU SOL','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-288','Outillage Ferroviaire','Barre à mine Leborgne','','Leborgne',3,'AU SOL','UNITE',1,0.0,'',10,2,5,0,''),
        ('ART-289','Outillage Ferroviaire','Elingue 10T textile 6M','','Mabeo',3,'B3','UNITE',1,0.0,'',10,2,4,0,''),
        ('ART-290','Outillage Ferroviaire','Charrue à ballast 1UCB000','1UCB000','RMS',3,'AU SOL','UNITE',1,0.0,'',5,1,5,0,''),
        ('ART-291','Outillage Ferroviaire','Bras de lorry','','',3,'AU SOL','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-292','Outillage Ferroviaire','Clé à serre','','',3,'AU SOL','UNITE',1,0.0,'',8,2,4,0,''),
        ('ART-293','Outillage Ferroviaire','Mire topographie','','',3,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-294','Outillage Ferroviaire','Règle ripage','','',3,'AU SOL','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-295','Outillage Ferroviaire','Chevalet soudeur Rail Tech','','Rail Tech',3,'AU SOL','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-296','Outillage Ferroviaire','Protège fourche grand','','Newtechnik',3,'AU SOL','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-297','Outillage Ferroviaire','Protège fourche petit','','Ops',3,'B3','PAIRE',1,0.0,'',1,1,2,0,''),
        ('ART-298','Outillage Ferroviaire','Dammeur','','',3,'','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-299','Nettoyage & Hygiène','Fourche à cailloux avec manche','0695943855','Würth',3,'AU SOL','UNITE',1,0.0,'',15,3,6,0,''),
        ('ART-300','Nettoyage & Hygiène','Râteaux avec manche','','',3,'AU SOL','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-301','Nettoyage & Hygiène','Balai industriel 60cm bois','','',3,'B3','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-302','Nettoyage & Hygiène','Balai atelier 55cm bois','','Prolian',3,'B3','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-303','Nettoyage & Hygiène','Balayette 30cm manche 450x30','','Xhander/Prolian',3,'B3','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-304','Nettoyage & Hygiène','Pelle ronde 29cm sans manche','069590229','Würth',3,'B2','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-305','Nettoyage & Hygiène','Pelle carré 23cm','069590223','Würth',3,'B2','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-306','Nettoyage & Hygiène','Micro-onde Samsung','','Samsung',3,'B2','UNITE',1,0.0,'',2,1,1,0,''),
        ('ART-307','Mesure & Traçage','Traceur de chantier blanc','0893 175 1','Würth',3,'A3','UNITE',1,0.0,'',13,5,20,0,''),
        ('ART-308','Mesure & Traçage','Traceur de chantier rouge','0892 175 3','Würth',3,'A3','UNITE',1,0.0,'',5,5,20,0,''),
        ('ART-309','Mesure & Traçage','Traceur de chantier jaune','0892 175 5','Würth',3,'A3','UNITE',1,0.0,'',6,5,20,0,''),
        ('ART-310','Mesure & Traçage','Traceur de chantier bleu','0892 175 2','Würth',3,'A3','UNITE',1,0.0,'',12,5,20,0,''),
        ('ART-311','Équipements Spéciaux','Bombe de peinture jaune','','Rust-Oleum',3,'A1','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-312','Équipements Spéciaux','Bombe de peinture noir','','Rust-Oleum',3,'A1','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-313','Équipements Spéciaux','Bombe de peinture rouge','','Rust-Oleum',3,'A1','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-314','Équipements Spéciaux','Mastic acrylique Xhander','','Prolian',3,'A2','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-315','Équipements Spéciaux','Mastic et colle Sika Pro-11 FC','','Sika',3,'A4','UNITE',1,0.0,'',15,3,6,0,''),
        ('ART-316','Équipements Spéciaux','Boîte électrique résistante dérivation','','',3,'B2','UNITE',1,0.0,'',6,1,3,0,''),
        ('ART-317','Équipements Spéciaux','Raccord symétrique pompier','','',3,'B2','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-318','Équipements Spéciaux','Tuyau pompier','','',3,'B2','UNITE',1,0.0,'',2,1,2,0,''),
        ('ART-319','Équipements Spéciaux','Corde lash traverses 105 32M','','',3,'B3','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-320','Équipements Spéciaux','Barrière extensible 4M','','',3,'B2','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-321','Équipements Spéciaux','Touret câble rigide internet C6','','',3,'B3','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-322','Nettoyage & Hygiène','Manche pioche plastique','532900','Leborgne',3,'B2','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-323','Nettoyage & Hygiène','Manche pioche bois','OPS43087312','Opsial/Prolian',3,'B2','UNITE',1,0.0,'',1,1,2,0,''),
        ('ART-324','Nettoyage & Hygiène','Manche masse bois Picard','00990010','Picard',3,'B2','UNITE',1,0.0,'',5,2,4,0,''),
        ('ART-325','Nettoyage & Hygiène','Manche pelle bois','','',3,'B2','UNITE',1,0.0,'',6,2,4,0,''),
        ('ART-326','Nettoyage & Hygiène','Râteaux sans manche','0695943581','Würth',3,'B2','UNITE',1,0.0,'',3,2,4,0,''),
        ('ART-327','Éclairage & Électricité','Projecteur électrique','','',3,'B1','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-328','Équipements Spéciaux','Réservoir d`alimentation d`eau','','',3,'','UNITE',1,0.0,'',1,1,1,0,''),
        ('ART-329','Matériaux & Géotextiles','Sikatop 122 FR bidon 5L','BIDON 5L','Sika',4,'SUR PALETTE','UNITE',1,0.0,'',12,3,5,0,''),
        ('ART-330','Matériaux & Géotextiles','Sikatop 122 FR sac 30kg','SAC 30 KG','Sika',4,'SUR PALETTE','UNITE',1,0.0,'',11,3,5,0,''),
        ('ART-331','Matériaux & Géotextiles','Fourreaux rouge 50M','FAMALEX ROUGE 63','',4,'','UNITE',1,0.0,'',5,1,2,0,''),
        ('ART-332','Matériaux & Géotextiles','Bidim noir 25M','TERRAM','Terram',4,'','UNITE',1,0.0,'',30,5,10,0,''),
        ('ART-333','Matériaux & Géotextiles','Bidim gris 50M','50M','',4,'','UNITE',1,0.0,'',9,2,5,0,''),
        ('ART-334','Matériaux & Géotextiles','Bidim Teram bleu','TERAM BLEU','Teram',4,'','UNITE',1,0.0,'',8,2,5,0,''),
        ('ART-335','Matériaux & Géotextiles','Bidim noir gravel','','',4,'','UNITE',1,0.0,'',9,2,5,0,''),
        ('ART-336','Matériaux & Géotextiles','Tapis rouge','','',4,'','UNITE',1,0.0,'',0,1,2,0,''),
        ('ART-337','Matériaux & Géotextiles','Film polyéthylène','','',4,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-338','Outillage Ferroviaire','Eclisse Tanconi','PAIRE','',4,'','PAIRE',1,0.0,'',0,2,4,0,''),
        ('ART-339','Outillage Ferroviaire','SAM (1 jaune+1 bleu+1 orange)','1 JAUNE+1 BLEU+1 ORANGE','',4,'','UNITE',1,0.0,'',3,1,2,0,''),
        ('ART-340','Outillage Ferroviaire','Chaîne + crochet (pelle)','','',4,'','UNITE',1,0.0,'',0,1,2,0,''),
        ('ART-341','Outillage Ferroviaire','Piquet porte lanterne','','',4,'','UNITE',1,0.0,'',55,10,20,0,''),
        ('ART-342','Nettoyage & Hygiène','Absorbant','','',4,'','UNITE',1,0.0,'',0,2,4,0,''),
        ('ART-343','Conditionnement & Rangement','Enrobé à froid noir 25kg','25KG','',4,'','BIDON',1,0.0,'',8,2,4,0,''),
        ('ART-344','Conditionnement & Rangement','Sac écrou+rondelle+boulon','SAC DE 12','',4,'','SAC',1,0.0,'',42,5,10,0,''),
        ('ART-345','Outillage Manuel','Filtre','','',5,'','UNITE',1,0.0,'',4,1,2,0,''),
        ('ART-346','Outillage Manuel','Sangle petite','','',5,'','UNITE',1,0.0,'',38,5,10,0,''),
        ('ART-347','Outillage Manuel','Sangle grande','','',5,'','UNITE',1,0.0,'',120,10,20,0,''),
        ('ART-348','Outillage Manuel','MPR connexion','','',5,'','UNITE',1,0.0,'',50,5,10,0,''),
    ]
    for a in articles:
        c.execute("""INSERT OR IGNORE INTO articles
            (id,famille,designation,reference,marque,container_id,emplacement,unite,colisage,
             prix_achat,fournisseur,stock,stock_min,stock_alerte,stock_max,observations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", a)

    # Fournisseurs
    fournisseurs = [
        ('F-001','Wurth France SAS','Service commercial','01 XX XX XX XX','commercial@wurth.fr','Zone Ind. Nord',5,'30j net','EPI, Cles, Fixations',''),
        ('F-002','Hilti France','Responsable compte','01 XX XX XX XX','compte@hilti.fr','Paris',7,'30j net','Perfo, Couronnes',''),
        ('F-003','Bossard France','Appro','01 XX XX XX XX','appro@bossard.fr','Lyon',10,'45j net','Boulons, Visserie',''),
        ('F-004','Opsial Prolians','','01 XX XX XX XX','','',5,'30j net','EPI, Combinaisons',''),
        ('F-005','Honeywell Safety','','01 XX XX XX XX','','',14,'45j net','Gants, Casques',''),
        ('F-006','Milwaukee Tool','','01 XX XX XX XX','','',10,'30j net','Batteries, Outils',''),
        ('F-007','Tyrolit France','','01 XX XX XX XX','','',7,'30j net','Disques, Abrasifs',''),
        ('F-008','Bolle Safety','','01 XX XX XX XX','','',5,'30j net','Lunettes',''),
        ('F-009','KF Lubricants','','01 XX XX XX XX','','',10,'45j net','Huiles, Lubrifiants',''),
        ('F-010','Geismar','','01 XX XX XX XX','','',14,'45j net','Outillage ferroviaire',''),
        ('F-011','Robel','','','','',21,'45j net','Outillage ferroviaire',''),
        ('F-012','Pandrol','','01 XX XX XX XX','','',30,'60j net','Fixations rail',''),
        ('F-013','Stihl France','','01 XX XX XX XX','','',14,'30j net','Tronconneuses',''),
        ('F-014','Xhander Prolians','','01 XX XX XX XX','','',5,'30j net','Disques, Outils',''),
        ('F-015','Cembre','','01 XX XX XX XX','','',14,'45j net','Batteries electrique',''),
        ('F-016','Varta','','01 XX XX XX XX','','',7,'30j net','Piles, Batteries',''),
        ('F-017','Mabeo Industrie','','01 XX XX XX XX','','',10,'30j net','Elingues, Levage',''),
        ('F-018','Opsial','','01 XX XX XX XX','','',5,'30j net','Masques, EPI',''),
        ('F-019','Haleco','','01 XX XX XX XX','','',7,'30j net','Solvants, Nettoyants',''),
        ('F-020','RMS Ferroviaire','','01 XX XX XX XX','','',21,'60j net','Materiel voie',''),
    ]
    for f in fournisseurs:
        c.execute("""INSERT OR IGNORE INTO fournisseurs
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
        c.execute("""INSERT OR IGNORE INTO bons_sortie
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
        c.execute("INSERT OR IGNORE INTO bons_sortie_lignes (bon_id,article_id,quantite) VALUES (?,?,?)", bl)

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
        c.execute("""INSERT OR IGNORE INTO bons_reception
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
        c.execute("""INSERT OR IGNORE INTO commandes
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
        c.execute("INSERT OR IGNORE INTO commande_lignes (commande_id,article_id,quantite,prix_unitaire) VALUES (?,?,?,?)", cl)

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
        conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
            quantite,reference_doc,stock_avant,stock_apres,container_id)
            VALUES (?,?,?,?,?,?,?,?)""",(
            date.today().isoformat(),'TRANSFERT',article_id,qte,numero,
            article['stock'],article['stock'],dst
        ))
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
             prix_achat,fournisseur,stock,stock_min,stock_alerte,stock_max,observations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            new_id, request.form.get('famille',''), request.form.get('designation',''),
            request.form.get('reference',''), request.form.get('marque',''),
            int(request.form.get('container_id',1)), request.form.get('emplacement',''),
            request.form.get('unite','UNITE'), int(request.form.get('colisage',1)),
            float(request.form.get('prix_achat',0)), request.form.get('fournisseur',''),
            int(request.form.get('stock',0)), int(request.form.get('stock_min',0)),
            int(request.form.get('stock_alerte',0)), int(request.form.get('stock_max',0)),
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
            stock_min=?,stock_alerte=?,stock_max=?,observations=? WHERE id=?""",(
            request.form.get('famille',''), request.form.get('designation',''),
            request.form.get('reference',''), request.form.get('marque',''),
            int(request.form.get('container_id',1)), request.form.get('emplacement',''),
            request.form.get('unite','UNITE'), int(request.form.get('colisage',1)),
            float(request.form.get('prix_achat',0)), request.form.get('fournisseur',''),
            int(request.form.get('stock_min',0)), int(request.form.get('stock_alerte',0)),
            int(request.form.get('stock_max',0)), request.form.get('observations',''), id,
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
        conn.execute("""INSERT INTO commandes
            (numero,date_demande,fournisseur,statut,livraison_prevue,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?)""",(
            numero,
            request.form.get('date_demande',date.today().isoformat()),
            request.form.get('fournisseur',''),
            'EN ATTENTE',
            request.form.get('livraison_prevue',''),
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
            conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
                quantite,reference_doc,stock_avant,stock_apres,container_id)
                VALUES (?,?,?,?,?,?,?,?)""",(
                date.today().isoformat(),'INVENTAIRE',article_id,abs(ecart),numero,
                stock_theorique,stock_reel,article['container_id']
            ))
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
    mvts = conn.execute("""SELECT m.*, a.designation, c.nom as container_nom,
        ch.nom as chantier_nom FROM mouvements m
        LEFT JOIN articles a ON m.article_id=a.id
        LEFT JOIN containers c ON m.container_id=c.id
        LEFT JOIN chantiers ch ON m.chantier_id=ch.id
        ORDER BY m.id DESC LIMIT 200""").fetchall()
    conn.close()
    return render_template('mouvements.html', mouvements=mvts)

# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@app.route('/analytics')
@login_required
def analytics():
    conn = get_db()
    articles = conn.execute("SELECT * FROM articles WHERE actif=1").fetchall()
    valeur_totale = sum(a['stock']*a['prix_achat'] for a in articles)
    total = len(articles)
    ruptures = sum(1 for a in articles if a['stock']==0)
    critiques = sum(1 for a in articles if 0<a['stock']<=a['stock_min'])
    alertes = sum(1 for a in articles if a['stock_min']<a['stock']<=a['stock_alerte'])
    familles_stats = {}
    for a in articles:
        f = a['famille']
        if f not in familles_stats:
            familles_stats[f] = {'nb':0,'valeur':0,'ruptures':0,'alertes':0}
        familles_stats[f]['nb'] += 1
        familles_stats[f]['valeur'] += a['stock']*a['prix_achat']
        etat = get_etat_stock(a['stock'],a['stock_min'],a['stock_alerte'])
        if etat == 'RUPTURE': familles_stats[f]['ruptures'] += 1
        elif etat in ('CRITIQUE','ALERTE'): familles_stats[f]['alertes'] += 1
    familles_list = sorted(familles_stats.items(), key=lambda x:x[1]['valeur'], reverse=True)
    top_sorties = conn.execute("""SELECT bsl.article_id, a.designation, SUM(bsl.quantite) as total_sorti,
        a.unite, MAX(bs.date_sortie) as derniere_sortie
        FROM bons_sortie_lignes bsl LEFT JOIN articles a ON bsl.article_id=a.id
        LEFT JOIN bons_sortie bs ON bsl.bon_id=bs.id
        GROUP BY bsl.article_id ORDER BY total_sorti DESC LIMIT 10""").fetchall()
    urgents = sorted([a for a in articles if a['stock']<=a['stock_min']], key=lambda x:x['stock'])
    mois = date.today().strftime('%Y-%m')
    nb_sorties_mois = conn.execute("SELECT COUNT(DISTINCT bon_id) FROM bons_sortie_lignes bsl LEFT JOIN bons_sortie bs ON bsl.bon_id=bs.id WHERE bs.date_sortie LIKE ?",(f'{mois}%',)).fetchone()[0]
    nb_receptions_mois = conn.execute("SELECT COUNT(*) FROM bons_reception WHERE date_reception LIKE ?",(f'{mois}%',)).fetchone()[0]
    # Stats par chantier
    chantier_stats = conn.execute("""SELECT ch.nom, COUNT(DISTINCT bs.id) as nb_sorties,
        SUM(bsl.quantite * a.prix_achat) as cout
        FROM bons_sortie bs
        LEFT JOIN bons_sortie_lignes bsl ON bsl.bon_id=bs.id
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id
        LEFT JOIN articles a ON bsl.article_id=a.id
        GROUP BY bs.chantier_id ORDER BY cout DESC""").fetchall()
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
    return render_template('print_bon_sortie.html', bon=bon, lignes=lignes)

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
if __name__ == '__main__':
    app.run(debug=False)
