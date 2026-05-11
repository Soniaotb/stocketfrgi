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
        article_id TEXT NOT NULL, quantite INTEGER NOT NULL, commentaire TEXT DEFAULT '',
        statut TEXT DEFAULT 'VALIDE', created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        ('EPI','🧤','#dc2626'),('VETEMENTS','🦺','#d97706'),('OUTILLAGE MANUEL','🔧','#16a34a'),
        ('ELECTROPORTATIF','⚡','#2563eb'),('ECLAIRAGE','💡','#f59e0b'),('BATTERIES','🔋','#7c3aed'),
        ('ABRASIFS','🔨','#db2777'),('LUBRIFIANTS','💧','#0891b2'),('CONDITIONNEMENT','📦','#65a30d'),
        ('NETTOYAGE','🧹','#0d9488'),('MESURE','📏','#6366f1'),('FIXATIONS','🔩','#9333ea'),
        ('FERROVIAIRE','⛏️','#1a1a2e'),('SPECIAUX','⚙️','#E8661A'),
    ]
    for f in familles:
        c.execute("INSERT OR IGNORE INTO familles (nom,icone,couleur) VALUES (?,?,?)", f)

    # Containers
    containers = [
        ('Container BLEU','BLEU','C-001','Container principal EPI et outillage','Base arrière',0,'ACTIF'),
        ('Container C5','C5','C-002','Container combinaisons et vetements','Base arrière',0,'ACTIF'),
        ('Container ROUGE','ROUGE','C-003','Container materiel ferroviaire','Chantier A',0,'ACTIF'),
        ('Container VERT','VERT','C-004','Container consommables','Base arrière',0,'ACTIF'),
        ('Container JAUNE','JAUNE','C-005','Container electrique','En deplacement',0,'EN DEPLACEMENT'),
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

    # 147 articles
    articles = [
        ('ART-001','EPI','Gants anticoupure taille 10','WE23-5313G','Honeywell',1,'A1','PAQUET',10,8.5,'Wurth',34,5,10,60,''),
        ('ART-002','EPI','Gants anticoupure taille 9','WE23-5113G','Honeywell',1,'A1','PAQUET',10,8.5,'Wurth',15,5,10,60,''),
        ('ART-003','EPI','Gants jetables EN ISO 374-1 XL','','Wurth',1,'A1','PAQUET',50,3.2,'Wurth',2,2,4,20,''),
        ('ART-004','EPI','Gants jetables EN ISO 374-1 L','','Wurth',1,'A1','PAQUET',50,3.2,'Wurth',1,2,4,20,'STOCK BAS'),
        ('ART-005','EPI','Gants soudeur taille 9','W-110','',1,'A1','PAIRE',1,12.0,'Prolians',4,2,5,20,''),
        ('ART-006','EPI','Gants soudeur taille 10','W-110','',1,'A1','PAIRE',1,12.0,'Prolians',15,2,5,20,''),
        ('ART-007','EPI','Gants cuir blanc T11','','',1,'A1','PAQUET',10,9.0,'',13,2,5,30,''),
        ('ART-008','EPI','Gant soudeur Blue Welder','P702LYQ','Prolians',1,'A1','UNITE',1,18.0,'Prolians',5,2,4,15,''),
        ('ART-009','EPI','Gants protection chimique','','',1,'A1','UNITE',1,22.0,'',2,1,2,10,''),
        ('ART-010','EPI','Gants hiver Ninja T10','','',1,'A2','PAQUET',5,14.0,'',28,3,8,40,''),
        ('ART-011','EPI',"Bouchons d oreille 4 paires",'0899300338','',1,'A2','PAQUET',4,1.5,'Wurth',91,10,20,120,''),
        ('ART-012','EPI',"Masque pret emploi ABEK1P3RD",'','Opsial',1,'A2','UNITE',1,8.5,'Opsial',8,5,10,30,''),
        ('ART-013','EPI','Masque Air Fit FFP3 jetable','','Opsial',1,'A2','BOITE',10,12.0,'Opsial',17,3,6,30,''),
        ('ART-014','EPI','Filtre remplacement SPR316ODUA','','Opsial',1,'A2','BOITE',10,9.5,'Opsial',5,2,4,20,''),
        ('ART-015','EPI','Lunettes tronconnage jaunes SPECTN12W','','Bolle',1,'A1','BOITE',5,18.0,'Bolle',6,1,3,15,''),
        ('ART-016','EPI','Lunettes tronconnage bleues BLAPSI','','Bolle',1,'A1','BOITE',5,18.0,'Bolle',1,1,2,10,'STOCK BAS'),
        ('ART-017','EPI','Lunettes securite blanches RUSHPPSI','RUSHPPSI','Bolle',1,'A1','BOITE',10,22.0,'Bolle',45,5,10,60,''),
        ('ART-018','EPI','Lunettes securite solaires RUSHPPSF','RUSHPPSF','Bolle',1,'A1','BOITE',10,22.0,'Bolle',8,2,5,20,''),
        ('ART-019','EPI','Lunettes sur casque EVOSPEC JSP','','JSP',1,'A1','UNITE',1,14.0,'JSP',26,5,10,40,''),
        ('ART-020','EPI','Casque anti-bruit VS100DH','','Honeywell',1,'A3','UNITE',1,32.0,'Honeywell',37,10,20,60,''),
        ('ART-021','EPI','Guetres tronconnage cuir TSV00008','TSV00008','',1,'A3','PAIRE',1,28.0,'',0,2,5,15,'A COMMANDER'),
        ('ART-022','VETEMENTS','Gilets HV 3XL encadrant','','',1,'B1','UNITE',1,15.0,'',2,1,2,10,''),
        ('ART-023','VETEMENTS','Gilets HV XL','','',1,'B1','UNITE',1,12.0,'',3,2,4,20,''),
        ('ART-024','VETEMENTS','Gilets HV L','','',1,'B1','UNITE',1,12.0,'',10,3,5,20,''),
        ('ART-025','VETEMENTS','Gilets HV M','','',1,'B1','UNITE',1,12.0,'',1,2,4,20,'STOCK BAS'),
        ('ART-026','VETEMENTS','Gilets HV S','','',1,'B1','UNITE',1,12.0,'',5,1,3,15,''),
        ('ART-027','VETEMENTS','Combinaison protection LG orange','','',1,'B1','UNITE',1,18.0,'',1,2,4,15,'STOCK BAS'),
        ('ART-028','VETEMENTS','Combinaison protection MD orange','','',1,'B1','UNITE',1,18.0,'',10,2,4,20,''),
        ('ART-029','VETEMENTS','Combinaison protection XL orange','','',1,'B1','UNITE',1,18.0,'',5,2,4,15,''),
        ('ART-030','VETEMENTS','Combinaison protection 3XL orange','','',1,'B1','UNITE',1,18.0,'',2,1,2,10,''),
        ('ART-031','VETEMENTS','Combinaison LG blanche','','',1,'B1','UNITE',1,16.0,'',22,5,10,40,''),
        ('ART-032','VETEMENTS','Combinaison LG blanche C5','','',2,'A3','UNITE',1,16.0,'',8,2,4,20,''),
        ('ART-033','VETEMENTS','Ensemble de pluie XL','','Opsial',1,'B1','UNITE',1,24.0,'Opsial',2,1,2,8,''),
        ('ART-034','OUTILLAGE MANUEL','Massette 1,25 kg Xhander','68600693','Xhander',1,'C1','UNITE',1,28.0,'Xhander',6,2,4,12,''),
        ('ART-035','OUTILLAGE MANUEL','Massette sans rebond Facom 40mm','','Facom',1,'C1','UNITE',1,45.0,'Facom',2,1,2,6,''),
        ('ART-036','OUTILLAGE MANUEL','Marteau Expert 40mm 1020g','','Expert',1,'C1','UNITE',1,22.0,'',1,1,2,5,''),
        ('ART-037','OUTILLAGE MANUEL','Taloche macon 270x180','','PV Vinmer',1,'C1','UNITE',1,8.0,'',7,2,4,15,''),
        ('ART-038','OUTILLAGE MANUEL','Pelle ronde a lame','','',1,'C1','UNITE',1,18.0,'',4,2,4,10,''),
        ('ART-039','OUTILLAGE MANUEL','Pelle carree a lame','','',1,'C1','UNITE',1,18.0,'',3,2,4,10,''),
        ('ART-040','OUTILLAGE MANUEL','Pioche manche bois','','',1,'C1','UNITE',1,22.0,'',2,1,2,8,''),
        ('ART-041','OUTILLAGE MANUEL','Barre a mine 1,5m','','',1,'C2','UNITE',1,35.0,'',3,1,2,6,''),
        ('ART-042','OUTILLAGE MANUEL','Serre-joint 400mm','','',1,'C2','UNITE',1,12.0,'',8,2,4,15,''),
        ('ART-043','OUTILLAGE MANUEL','Cle a molette 300mm','','Facom',1,'C2','UNITE',1,28.0,'Facom',5,2,4,10,''),
        ('ART-044','OUTILLAGE MANUEL','Cle a molette 250mm','','Facom',1,'C2','UNITE',1,22.0,'Facom',4,2,4,10,''),
        ('ART-045','OUTILLAGE MANUEL','Pince multiprise 200mm','','Knipex',1,'C2','UNITE',1,18.0,'',6,2,4,12,''),
        ('ART-046','OUTILLAGE MANUEL','Elingue sangle 2T 1m','','',1,'C2','UNITE',1,25.0,'Mabeo',3,1,2,8,''),
        ('ART-047','OUTILLAGE MANUEL','Elingue chaine 2T','','',1,'C2','UNITE',1,45.0,'Mabeo',2,1,2,5,''),
        ('ART-048','OUTILLAGE MANUEL','Manille 2T droite','','',1,'C2','UNITE',1,8.0,'',12,3,6,20,''),
        ('ART-049','OUTILLAGE MANUEL','Crochet de levage 1T','','',1,'C2','UNITE',1,15.0,'',4,1,2,8,''),
        ('ART-050','OUTILLAGE MANUEL','Cisaille coupe cable 300mm','','',1,'C2','UNITE',1,35.0,'',3,1,2,6,''),
        ('ART-051','OUTILLAGE MANUEL','Coupe-boulon 600mm','','',1,'C3','UNITE',1,55.0,'',2,1,2,4,''),
        ('ART-052','OUTILLAGE MANUEL','Tire-fort 3T sangle','','',1,'C3','UNITE',1,65.0,'',2,1,2,4,''),
        ('ART-053','OUTILLAGE MANUEL','Cle dynamometrique 40-200Nm','','Facom',1,'C3','UNITE',1,85.0,'Facom',2,1,2,4,''),
        ('ART-054','OUTILLAGE MANUEL','Niveau a bulle 60cm','','',1,'C3','UNITE',1,18.0,'',5,2,4,10,''),
        ('ART-055','OUTILLAGE MANUEL','Pied de biche 600mm','','',1,'C3','UNITE',1,22.0,'',4,2,4,8,''),
        ('ART-056','OUTILLAGE MANUEL','Raclette professionnelle','','',1,'C3','UNITE',1,12.0,'',6,2,4,12,''),
        ('ART-057','OUTILLAGE MANUEL','Pinceau enduit 10cm','','',1,'C3','UNITE',1,4.0,'',15,5,10,30,''),
        ('ART-058','OUTILLAGE MANUEL','Rouleau peinture 18cm','','',1,'C3','UNITE',1,5.0,'',10,4,8,25,''),
        ('ART-059','OUTILLAGE MANUEL','Bac a peinture','','',1,'C3','UNITE',1,3.0,'',8,3,6,20,''),
        ('ART-060','OUTILLAGE MANUEL','Couteau universel + lames','','Stanley',1,'C3','UNITE',1,8.0,'',12,4,8,20,''),
        ('ART-061','ELECTROPORTATIF','Perforateur SDS+ 900W','','Hilti',1,'D1','UNITE',1,450.0,'Hilti',3,1,2,5,''),
        ('ART-062','ELECTROPORTATIF','Percuteur 18V Milwaukee','','Milwaukee',1,'D1','UNITE',1,280.0,'Milwaukee',8,2,4,10,''),
        ('ART-063','ELECTROPORTATIF','Visseuse a choc 18V Milwaukee','','Milwaukee',1,'D1','UNITE',1,260.0,'Milwaukee',5,2,4,8,''),
        ('ART-064','ELECTROPORTATIF','Meuleuse 125mm 1400W','','',1,'D1','UNITE',1,95.0,'',6,2,4,10,''),
        ('ART-065','ELECTROPORTATIF','Meuleuse 230mm 2200W','','',1,'D1','UNITE',1,145.0,'',3,1,2,6,''),
        ('ART-066','ELECTROPORTATIF','Tronconneuse thermique Stihl MS261','','Stihl',1,'D2','UNITE',1,680.0,'Stihl',2,1,2,4,''),
        ('ART-067','ELECTROPORTATIF','Scie circulaire 190mm','','',1,'D2','UNITE',1,185.0,'',2,1,2,4,''),
        ('ART-068','ELECTROPORTATIF','Ponceuse excentrique 125mm','','',1,'D2','UNITE',1,95.0,'',2,1,2,4,''),
        ('ART-069','ELECTROPORTATIF','Aspirateur industriel 30L','','',1,'D2','UNITE',1,195.0,'',2,1,2,3,''),
        ('ART-070','ELECTROPORTATIF','Compresseur 24L portable','','',1,'D2','UNITE',1,245.0,'',1,1,1,2,''),
        ('ART-071','ECLAIRAGE','Lampe frontale LED 500lm','','',1,'E1','UNITE',1,18.0,'',25,5,10,40,''),
        ('ART-072','ECLAIRAGE','Lampe frontale rechargeable 1000lm','','',1,'E1','UNITE',1,32.0,'',12,3,6,20,''),
        ('ART-073','ECLAIRAGE','Projecteur LED chantier 50W','','',1,'E1','UNITE',1,65.0,'',8,2,4,12,''),
        ('ART-074','ECLAIRAGE','Projecteur LED 100W sur pied','','',1,'E1','UNITE',1,95.0,'',4,1,2,8,''),
        ('ART-075','ECLAIRAGE','Guirlande LED chantier 10m','','',1,'E1','UNITE',1,35.0,'',6,2,4,10,''),
        ('ART-076','BATTERIES','Piles AA Varta boite 10','','Varta',1,'E2','BOITE',10,3.5,'Varta',45,10,20,100,''),
        ('ART-077','BATTERIES','Piles AAA Varta boite 10','','Varta',1,'E2','BOITE',10,3.5,'Varta',30,8,15,80,''),
        ('ART-078','BATTERIES','Piles 9V Varta boite 6','','Varta',1,'E2','BOITE',6,6.0,'Varta',15,4,8,30,''),
        ('ART-079','BATTERIES','Batterie Milwaukee 18V 5Ah','','Milwaukee',1,'E2','UNITE',1,95.0,'Milwaukee',8,2,4,12,''),
        ('ART-080','BATTERIES','Chargeur rapide Milwaukee','','Milwaukee',1,'E2','UNITE',1,65.0,'Milwaukee',4,1,2,6,''),
        ('ART-081','ABRASIFS','Disque tronconnage acier 125mm','','Pferd',1,'F1','BOITE',25,18.0,'Xhander',85,15,30,150,''),
        ('ART-082','ABRASIFS','Disque tronconnage acier 230mm','','Pferd',1,'F1','BOITE',25,22.0,'Xhander',40,10,20,80,''),
        ('ART-083','ABRASIFS','Disque meulage acier 125mm','','Pferd',1,'F1','BOITE',25,18.0,'Xhander',60,10,20,100,''),
        ('ART-084','ABRASIFS','Disque meulage acier 230mm','','Pferd',1,'F1','BOITE',25,22.0,'Xhander',30,8,15,60,''),
        ('ART-085','ABRASIFS','Disque lamelles 125mm G40','','',1,'F1','BOITE',10,16.0,'',25,5,10,50,''),
        ('ART-086','ABRASIFS','Disque lamelles 125mm G60','','',1,'F1','BOITE',10,16.0,'',20,5,10,50,''),
        ('ART-087','ABRASIFS','Disque lamelles 125mm G80','','',1,'F1','BOITE',10,16.0,'',15,4,8,40,''),
        ('ART-088','ABRASIFS','Toile emeri 115x280mm G60','','',1,'F2','BOITE',50,8.0,'',20,5,10,60,''),
        ('ART-089','ABRASIFS','Brosse metallique ronde fils acier','','',1,'F2','UNITE',1,4.5,'',30,8,15,50,''),
        ('ART-090','ABRASIFS','Feutre de polissage 125mm','','',1,'F2','UNITE',1,3.5,'',0,2,5,20,'A COMMANDER'),
        ('ART-091','LUBRIFIANTS','Huile multi-usages WD40 500ml','','WD40',1,'G1','UNITE',1,8.5,'KF Lubricants',11,3,6,20,''),
        ('ART-092','LUBRIFIANTS','Graisse multi-usages 500g','','',1,'G1','UNITE',1,12.0,'',8,2,4,15,''),
        ('ART-093','LUBRIFIANTS','Huile de coupe 1L','','',1,'G1','UNITE',1,15.0,'KF Lubricants',6,2,4,12,''),
        ('ART-094','LUBRIFIANTS','Lubrifiant chaine tronconneuse 1L','','Stihl',1,'G1','UNITE',1,12.0,'Stihl',8,2,4,15,''),
        ('ART-095','LUBRIFIANTS','Graisse ferroviaire speciale 1kg','','',1,'G1','UNITE',1,28.0,'Geismar',4,1,2,8,''),
        ('ART-096','CONDITIONNEMENT','Palette bois 1200x800','','',1,'H1','UNITE',1,8.0,'',20,5,10,40,''),
        ('ART-097','CONDITIONNEMENT','Film etirable 23mu 500m','','',1,'H1','ROULEAU',1,12.0,'',15,3,6,30,''),
        ('ART-098','CONDITIONNEMENT','Sangles arrimage 5T lot 2','','',1,'H1','LOT',2,18.0,'',8,2,4,15,''),
        ('ART-099','CONDITIONNEMENT','Bache protection 4x5m','','',1,'H1','UNITE',1,25.0,'',6,2,4,10,''),
        ('ART-100','CONDITIONNEMENT','Sac poubelle 100L rouleau 10','','',1,'H2','ROULEAU',10,4.0,'',25,8,15,50,''),
        ('ART-101','NETTOYAGE','Savon mains industriel 5L','','',1,'I1','BIDON',1,12.0,'Haleco',6,2,4,10,''),
        ('ART-102','NETTOYAGE','Lingettes degraissantes boite 80','','',1,'I1','BOITE',80,8.0,'',12,3,6,25,''),
        ('ART-103','NETTOYAGE','Degraissant industriel aerosol 500ml','','',1,'I1','UNITE',1,6.5,'Haleco',15,4,8,30,''),
        ('ART-104','NETTOYAGE','Solvant nettoyant rail 5L','','',1,'I1','BIDON',1,22.0,'Haleco',4,1,2,8,''),
        ('ART-105','NETTOYAGE','Balai brosse rigide','','',1,'I2','UNITE',1,8.0,'',8,2,4,15,''),
        ('ART-106','NETTOYAGE','Brosse metal decapante','','',1,'I2','UNITE',1,3.5,'',20,5,10,35,''),
        ('ART-107','MESURE','Metre ruban 5m','','Stanley',1,'J1','UNITE',1,8.0,'',15,4,8,25,''),
        ('ART-108','MESURE','Metre ruban 10m','','Stanley',1,'J1','UNITE',1,14.0,'',8,2,4,15,''),
        ('ART-109','MESURE','Telemetre laser 40m','','',1,'J1','UNITE',1,65.0,'',3,1,2,5,''),
        ('ART-110','MESURE','Detecteur de metaux cables','','',1,'J1','UNITE',1,85.0,'',2,1,2,3,''),
        ('ART-111','MESURE','Thermometre infrarouge','','',1,'J1','UNITE',1,45.0,'',3,1,2,5,''),
        ('ART-112','MESURE','Jauge epaisseur 0-10mm','','',1,'J1','UNITE',1,35.0,'',4,1,2,6,''),
        ('ART-113','FIXATIONS','Boulons HM M16x50 boite 25','','Bossard',1,'K1','BOITE',25,14.0,'Bossard',18,4,8,30,''),
        ('ART-114','FIXATIONS','Boulons HM M20x60 boite 10','','Bossard',1,'K1','BOITE',10,18.0,'Bossard',12,3,6,20,''),
        ('ART-115','FIXATIONS','Ecrous HM M16 boite 50','','Bossard',1,'K1','BOITE',50,8.0,'Bossard',25,5,10,50,''),
        ('ART-116','FIXATIONS','Ecrous HM M20 boite 25','','Bossard',1,'K1','BOITE',25,10.0,'Bossard',15,4,8,30,''),
        ('ART-117','FIXATIONS','Rondelles plates M16 boite 100','','Bossard',1,'K2','BOITE',100,4.0,'Bossard',30,8,15,60,''),
        ('ART-118','FIXATIONS','Rondelles Grower M16 boite 100','','Bossard',1,'K2','BOITE',100,5.0,'Bossard',25,6,12,50,''),
        ('ART-119','FIXATIONS','Cheville a expansion M12 boite 20','','Hilti',1,'K2','BOITE',20,22.0,'Hilti',15,3,6,25,''),
        ('ART-120','FIXATIONS','Cheville chimique resine 300ml','','Hilti',1,'K2','UNITE',1,18.0,'Hilti',20,5,10,35,''),
        ('ART-121','FIXATIONS','Tire-fond 8x80 inox boite 50','','',1,'K2','BOITE',50,12.0,'',12,3,6,25,''),
        ('ART-122','FIXATIONS','Plaquette rail type K boite 20','','Bossard',1,'K3','BOITE',20,14.0,'Bossard',17,4,8,30,''),
        ('ART-123','FIXATIONS','Boulon crampon rail M24 lot 10','','Pandrol',1,'K3','LOT',10,35.0,'Pandrol',8,2,4,15,''),
        ('ART-124','FIXATIONS','Rondelle epaisse rail M24 boite 50','','',1,'K3','BOITE',50,8.0,'',20,5,10,40,''),
        ('ART-125','FERROVIAIRE','Chasse-goupille rail','','Geismar',3,'L1','UNITE',1,45.0,'Geismar',5,1,2,8,''),
        ('ART-126','FERROVIAIRE','Pince pose rail Geismar','','Geismar',3,'L1','UNITE',1,185.0,'Geismar',2,1,2,4,''),
        ('ART-127','FERROVIAIRE','Cle rail a rochet','','Robel',3,'L1','UNITE',1,125.0,'Robel',3,1,2,5,''),
        ('ART-128','FERROVIAIRE','Tire-fond rail M24 court boite 10','','Bossard',3,'L1','BOITE',10,8.0,'Bossard',0,4,8,25,'A COMMANDER'),
        ('ART-129','FERROVIAIRE','Attache elastique Pandrol lot 20','','Pandrol',3,'L2','LOT',20,28.0,'Pandrol',12,3,6,20,''),
        ('ART-130','FERROVIAIRE','Selle de rail isolante lot 10','','',3,'L2','LOT',10,22.0,'Pandrol',8,2,4,15,''),
        ('ART-131','FERROVIAIRE','Semelle sous rail 150x150 lot 10','','',3,'L2','LOT',10,18.0,'',10,2,4,20,''),
        ('ART-132','FERROVIAIRE','Plaque eclissage 50kg paire','','',3,'L2','PAIRE',1,85.0,'',4,1,2,8,''),
        ('ART-133','FERROVIAIRE','Boulon eclisse M24x140 lot 8','','Bossard',3,'L3','LOT',8,22.0,'Bossard',6,1,2,12,''),
        ('ART-134','FERROVIAIRE','Jauge de profil rail 60E1','','Robel',3,'L3','UNITE',1,95.0,'Robel',2,1,1,3,''),
        ('ART-135','FERROVIAIRE','Thermite de soudure rail kit','','',3,'L3','KIT',1,145.0,'RMS Ferroviaire',4,1,2,8,''),
        ('ART-136','FERROVIAIRE','Meule rail 180mm','','Tyrolit',3,'L3','UNITE',1,28.0,'Tyrolit',8,2,4,15,''),
        ('ART-137','SPECIAUX','Kit reparation tuyau hydraulique','','',1,'M1','KIT',1,45.0,'',3,1,2,6,''),
        ('ART-138','SPECIAUX','Goupille de securite M10 lot 10','','',1,'M1','LOT',10,8.0,'',12,3,6,20,''),
        ('ART-139','SPECIAUX','Couronne percage beton 68mm Hilti','','Hilti',1,'M1','UNITE',1,89.0,'Hilti',2,1,2,4,''),
        ('ART-140','SPECIAUX','Couronne percage beton 82mm Hilti','','Hilti',1,'M1','UNITE',1,95.0,'Hilti',1,1,1,3,''),
        ('ART-141','SPECIAUX','Meche SDS+ beton 16x200mm','','Hilti',1,'M1','UNITE',1,8.5,'Hilti',15,4,8,25,''),
        ('ART-142','SPECIAUX','Meche SDS+ beton 20x200mm','','Hilti',1,'M1','UNITE',1,9.5,'Hilti',10,3,6,20,''),
        ('ART-143','SPECIAUX','Ruban de marquage jaune 50m','','',1,'M2','ROULEAU',1,4.0,'',20,5,10,40,''),
        ('ART-144','SPECIAUX','Ruban de marquage rouge 50m','','',1,'M2','ROULEAU',1,4.0,'',15,4,8,30,''),
        ('ART-145','SPECIAUX','Peinture marquage sol blanc 500ml','','',1,'M2','UNITE',1,6.5,'',12,4,8,25,''),
        ('ART-146','SPECIAUX','Peinture marquage sol jaune 500ml','','',1,'M2','UNITE',1,6.5,'',10,3,6,20,''),
        ('ART-147','SPECIAUX','Peinture marquage sol rouge 500ml','','',1,'M2','UNITE',1,6.5,'',8,3,6,20,''),
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
        ('BS-001','2025-01-15','Martin J.',1,'ART-011',10,'Distribution initiale'),
        ('BS-002','2025-02-03','Dupont P.',2,'ART-081',15,'Tronconnage rail km 42'),
        ('BS-003','2025-02-10','Bernard L.',3,'ART-076',40,'Lampes frontales'),
        ('BS-004','2025-02-15','Martin J.',1,'ART-012',3,'EPI equipe A'),
        ('BS-005','2025-03-01','Dupont P.',4,'ART-046',2,'Levage'),
        ('BS-006','2025-03-05','Bernard L.',1,'ART-050',5,'Decoupe cables'),
        ('BS-007','2025-03-10','Martin J.',3,'ART-091',2,'Entretien'),
        ('BS-008','2025-03-12','Dupont P.',1,'ART-017',1,'Percage'),
        ('BS-009','2025-03-14','Bernard L.',4,'ART-013',2,'Protection poussiere'),
        ('BS-010','2025-03-15','Martin J.',3,'ART-086',10,'Meulage rail'),
    ]
    for bs in bons_s:
        c.execute("""INSERT OR IGNORE INTO bons_sortie
            (numero,date_sortie,demandeur,chantier_id,article_id,quantite,commentaire)
            VALUES (?,?,?,?,?,?,?)""", bs)

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
    bons_s = conn.execute("""SELECT bs.*, a.designation, ch.nom as chantier_nom
        FROM bons_sortie bs LEFT JOIN articles a ON bs.article_id=a.id
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id ORDER BY bs.id DESC LIMIT 8""").fetchall()
    cmds = conn.execute("""SELECT c.*, a.designation FROM commandes c
        LEFT JOIN articles a ON c.article_id=a.id
        WHERE c.statut IN ('EN ATTENTE','EN COURS','VALIDEE') ORDER BY c.id DESC LIMIT 6""").fetchall()
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
        nb_cmds_attente=len([c for c in cmds if c['statut']=='EN ATTENTE']))

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
        cout = conn.execute("""SELECT SUM(bs.quantite * a.prix_achat) FROM bons_sortie bs
            LEFT JOIN articles a ON bs.article_id=a.id WHERE bs.chantier_id=?""",(ch['id'],)).fetchone()[0] or 0
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
    bons = conn.execute("""SELECT bs.*, a.designation, a.unite, a.prix_achat, ch.nom as chantier_nom
        FROM bons_sortie bs LEFT JOIN articles a ON bs.article_id=a.id
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id ORDER BY bs.id DESC""").fetchall()
    conn.close()
    return render_template('bons_sortie.html', bons=bons)

@app.route('/bons-sortie/nouveau', methods=['GET','POST'])
@login_required
def nouveau_bon_sortie():
    if request.method == 'POST':
        article_id = request.form.get('article_id','').strip()
        quantite = int(request.form.get('quantite',0))
        conn = get_db()
        article = conn.execute("SELECT * FROM articles WHERE id=?",(article_id,)).fetchone()
        if not article:
            flash('Article introuvable','error'); conn.close()
            return redirect(url_for('nouveau_bon_sortie'))
        if quantite > article['stock']:
            flash(f'Stock insuffisant : {article["stock"]} {article["unite"]} disponible','error')
            conn.close(); return redirect(url_for('nouveau_bon_sortie'))
        numero = get_next_numero('bons_sortie','numero','BS-')
        s_avant = article['stock']; s_apres = s_avant - quantite
        chantier_id = int(request.form.get('chantier_id',0))
        conn.execute("""INSERT INTO bons_sortie
            (numero,date_sortie,demandeur,chantier_id,article_id,quantite,commentaire,created_by)
            VALUES (?,?,?,?,?,?,?,?)""",(
            numero, request.form.get('date_sortie',date.today().isoformat()),
            request.form.get('demandeur',''), chantier_id,
            article_id, quantite, request.form.get('commentaire',''), session.get('user_id'),
        ))
        conn.execute("UPDATE articles SET stock=? WHERE id=?",(s_apres,article_id))
        conn.execute("""INSERT INTO mouvements (date_mouvement,type_mouvement,article_id,
            quantite,reference_doc,stock_avant,stock_apres,container_id,chantier_id)
            VALUES (?,?,?,?,?,?,?,?,?)""",(
            date.today().isoformat(),'SORTIE',article_id,quantite,numero,
            s_avant,s_apres,article['container_id'],chantier_id
        ))
        conn.commit(); conn.close()
        flash(f'Bon {numero} créé — Nouveau stock : {s_apres} {article["unite"]}','success')
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
    top_sorties = conn.execute("""SELECT article_id, a.designation, SUM(quantite) as total_sorti,
        a.unite, MAX(date_sortie) as derniere_sortie
        FROM bons_sortie bs LEFT JOIN articles a ON bs.article_id=a.id
        GROUP BY article_id ORDER BY total_sorti DESC LIMIT 10""").fetchall()
    urgents = sorted([a for a in articles if a['stock']<=a['stock_min']], key=lambda x:x['stock'])
    mois = date.today().strftime('%Y-%m')
    nb_sorties_mois = conn.execute("SELECT COUNT(*) FROM bons_sortie WHERE date_sortie LIKE ?",(f'{mois}%',)).fetchone()[0]
    nb_receptions_mois = conn.execute("SELECT COUNT(*) FROM bons_reception WHERE date_reception LIKE ?",(f'{mois}%',)).fetchone()[0]
    # Stats par chantier
    chantier_stats = conn.execute("""SELECT ch.nom, COUNT(bs.id) as nb_sorties,
        SUM(bs.quantite * a.prix_achat) as cout
        FROM bons_sortie bs LEFT JOIN chantiers ch ON bs.chantier_id=ch.id
        LEFT JOIN articles a ON bs.article_id=a.id
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
    users = conn.execute("SELECT * FROM utilisateurs WHERE actif=1").fetchall()
    conn.close()
    return render_template('parametres.html', users=users)

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
    bon = conn.execute("""SELECT bs.*, a.designation, a.unite, a.reference, a.marque,
        a.prix_achat, ch.nom as chantier_nom, ch.code as chantier_code, ch.adresse as chantier_adresse,
        c.nom as container_nom, u.nom as created_by_nom
        FROM bons_sortie bs
        LEFT JOIN articles a ON bs.article_id=a.id
        LEFT JOIN chantiers ch ON bs.chantier_id=ch.id
        LEFT JOIN containers c ON a.container_id=c.id
        LEFT JOIN utilisateurs u ON bs.created_by=u.id
        WHERE bs.id=?""",(id,)).fetchone()
    conn.close()
    if not bon:
        flash('Bon introuvable','error'); return redirect(url_for('bons_sortie'))
    return render_template('print_bon_sortie.html', bon=bon)

@app.route('/bons-sortie/<int:id>/supprimer', methods=['POST'])
@login_required
def supprimer_bon_sortie(id):
    conn = get_db()
    bon = conn.execute("SELECT * FROM bons_sortie WHERE id=?",(id,)).fetchone()
    if bon:
        conn.execute("UPDATE articles SET stock=stock+? WHERE id=?",(bon['quantite'],bon['article_id']))
        conn.execute("DELETE FROM bons_sortie WHERE id=?",(id,))
        conn.commit()
        flash(f'Bon {bon["numero"]} supprime - stock restaure','success')
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

if __name__ == '__main__':
    app.run(debug=False)
