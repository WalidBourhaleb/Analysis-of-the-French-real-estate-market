"""
=============================================================================
SETTINGS.PY — Configuration Centrale du Projet
=============================================================================
Analyse du Marché Immobilier Français
Auteur: Walid Bourhaleb
=============================================================================

Ce fichier centralise TOUTE la configuration du projet.
Les autres fichiers importent leurs paramètres depuis ici.

Utilisation:
    from config.settings import DATABASE_URL, SCRAPING_CONFIG
=============================================================================
"""

import os
import logging
import logging.config
from pathlib import Path
from dotenv import load_dotenv


# =============================================================================
# CHARGEMENT VARIABLES D'ENVIRONNEMENT (.env)
# =============================================================================
# Charge les variables depuis le fichier .env à la racine du projet
load_dotenv()


# =============================================================================
# CHEMINS DU PROJET
# =============================================================================
# BASE_DIR = racine du projet (là où se trouve README.md)
BASE_DIR = Path(__file__).resolve().parent.parent

# Sous-dossiers principaux
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = BASE_DIR / "models"
LOGS_DIR = BASE_DIR / "logs"
NOTEBOOKS_DIR = BASE_DIR / "notebooks"
DOCS_DIR = BASE_DIR / "docs"

# Créer les dossiers s'ils n'existent pas
for dir_path in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, MODELS_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


# =============================================================================
# BASE DE DONNÉES (PostgreSQL + PostGIS)
# =============================================================================
DATABASE = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "database": os.getenv("DB_NAME", "immobilier_db"),
    "user": os.getenv("DB_USER", "immo_user"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# URL de connexion complète (format SQLAlchemy)
DATABASE_URL = (
    f"postgresql://{DATABASE['user']}:{DATABASE['password']}"
    f"@{DATABASE['host']}:{DATABASE['port']}/{DATABASE['database']}"
)

# URL alternative pour psycopg2 (connexion directe)
DATABASE_DSN = (
    f"host={DATABASE['host']} "
    f"port={DATABASE['port']} "
    f"dbname={DATABASE['database']} "
    f"user={DATABASE['user']} "
    f"password={DATABASE['password']}"
)


# =============================================================================
# API DVF (Demandes de Valeurs Foncières)
# =============================================================================
# Documentation: https://cadastre.data.gouv.fr/dvf
DVF_CONFIG = {
    "api_url": "https://data.economie.gouv.fr/api/records/1.0/search/",
    "dataset": "demandes-de-valeurs-foncieres",
    "api_key": os.getenv("DVF_API_KEY", ""),  # Optionnel, API publique
    "max_records_per_page": 1000,
    "default_cities": [
        ("75", "Paris"),
        ("69", "Lyon"),
        ("13", "Marseille"),
        ("33", "Bordeaux"),
        ("59", "Lille"),
    ],
    "default_start_date": "2022-01-01",
    "default_end_date": "2024-12-31",
    "default_types": ["Appartement", "Maison"],
    "request_delay": 0.5,  # Secondes entre chaque requête API
}


# =============================================================================
# API INSEE
# =============================================================================
# Documentation: https://api.insee.fr/catalogue/
INSEE_CONFIG = {
    "api_base_url": "https://api.insee.fr/donnees-locales/V0.1",
    "api_key": os.getenv("INSEE_API_KEY", ""),
    "request_delay": 1.0,  # 1 seconde entre chaque requête
}


# =============================================================================
# GEOCODING (Nominatim / Google Maps)
# =============================================================================
# Service par défaut: Nominatim (gratuit, pas besoin de clé)
GEOCODING_CONFIG = {
    "service": os.getenv("GEOCODING_SERVICE", "nominatim"),
    "nominatim_url": "https://nominatim.openstreetmap.org/search",
    "nominatim_user_agent": "immobilier-analysis-app",
    "nominatim_delay": 1.0,  # OBLIGATOIRE: 1 req/sec max
    "google_api_key": os.getenv("GOOGLE_MAPS_API_KEY", ""),
}


# =============================================================================
# WEB SCRAPING
# =============================================================================
SCRAPING_CONFIG = {
    # Paramètres généraux
    "delay_min": int(os.getenv("SCRAPING_DELAY_MIN", 3)),
    "delay_max": int(os.getenv("SCRAPING_DELAY_MAX", 7)),
    "max_pages_per_search": int(os.getenv("MAX_PAGES_PER_SEARCH", 5)),
    "max_listings_per_day": int(os.getenv("MAX_LISTINGS_PER_DAY", 30)),
    "user_agent": os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "retry_max_attempts": 3,
    "retry_backoff_factor": 2,

    # Configuration PAP.fr
    "pap": {
        "base_url": "https://www.pap.fr",
        "search_url": "https://www.pap.fr/annonce/vente-immobilier-{city}",
    },

    # Configuration Bienici.com
    "bienici": {
        "base_url": "https://www.bienici.com",
        "api_url": "https://www.bienici.com/realEstateAds.json",
    },

    # Proxies (optionnel)
    "proxy_url": os.getenv("PROXY_URL", ""),
    "proxy_username": os.getenv("PROXY_USERNAME", ""),
    "proxy_password": os.getenv("PROXY_PASSWORD", ""),
}


# =============================================================================
# DATA QUALITY (seuils de validation)
# =============================================================================
DATA_QUALITY = {
    # Prix acceptables (en €)
    "min_price": int(os.getenv("MIN_PRICE", 10000)),
    "max_price": int(os.getenv("MAX_PRICE", 10000000)),

    # Surfaces acceptables (en m²)
    "min_surface": int(os.getenv("MIN_SURFACE", 9)),
    "max_surface": int(os.getenv("MAX_SURFACE", 1000)),

    # Prix au m² acceptables (en €/m²)
    "min_price_m2": int(os.getenv("MIN_PRICE_M2", 500)),
    "max_price_m2": int(os.getenv("MAX_PRICE_M2", 20000)),

    # Nombre de pièces
    "min_rooms": 1,
    "max_rooms": 20,

    # Année de construction
    "min_year": 1800,
    "max_year": 2025,
}


# =============================================================================
# MACHINE LEARNING
# =============================================================================
ML_CONFIG = {
    # Version du modèle
    "model_version": os.getenv("MODEL_VERSION", "v1.0"),

    # Fichier du modèle sauvegardé
    "model_path": MODELS_DIR / "price_predictor_v1.pkl",

    # Paramètres d'entraînement
    "test_size": float(os.getenv("TEST_SIZE", 0.2)),
    "random_state": int(os.getenv("RANDOM_SEED", 42)),

    # Paramètres XGBoost
    "xgboost": {
        "n_estimators": int(os.getenv("ML_N_ESTIMATORS", 200)),
        "max_depth": int(os.getenv("ML_MAX_DEPTH", 15)),
        "learning_rate": float(os.getenv("ML_LEARNING_RATE", 0.05)),
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "gamma": 0.1,
    },

    # Cross-validation
    "cv_folds": 5,

    # Features à utiliser pour le modèle
    "features": [
        "surface_reelle_bati",
        "nb_pieces",
        "type_local_encoded",
        "commune_prix_m2_mean",
        "distance_centre_ville",
        "annee",
        "mois",
        "trimestre",
        "m2_par_piece",
        "grande_surface",
    ],

    # Feature cible (ce qu'on prédit)
    "target": "valeur_fonciere",
}


# =============================================================================
# STREAMLIT DASHBOARD
# =============================================================================
DASHBOARD_CONFIG = {
    "title": "🏠 Analyse du Marché Immobilier Français",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
    "cache_ttl": int(os.getenv("CACHE_TTL", 3600)),  # Cache 1 heure

    # Pages du dashboard
    "pages": [
        {"name": "🏠 Overview", "file": "1_🏠_Overview.py"},
        {"name": "🗺️ Carte", "file": "2_🗺️_Map.py"},
        {"name": "📈 Tendances", "file": "3_📈_Trends.py"},
        {"name": "🏘️ Quartiers", "file": "4_🏘️_Quartiers.py"},
        {"name": "🤖 Prédiction", "file": "5_🤖_Prediction.py"},
        {"name": "💎 Opportunités", "file": "6_💎_Opportunities.py"},
    ],

    # Thème
    "theme": {
        "base": os.getenv("STREAMLIT_THEME_BASE", "light"),
        "primary_color": os.getenv("STREAMLIT_THEME_PRIMARY_COLOR", "#FF4B4B"),
    },
}


# =============================================================================
# LOGGING (Journalisation)
# =============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "app.log"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    # Format des messages de log
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "detailed": {
            "format": (
                "%(asctime)s [%(levelname)s] %(name)s "
                "(%(filename)s:%(lineno)d): %(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },

    # Où envoyer les logs
    "handlers": {
        # Afficher dans le terminal
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        # Écrire dans un fichier (rotation à 10 MB)
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 10485760,  # 10 MB
            "backupCount": 5,
            "formatter": "detailed",
        },
    },

    # Configuration par défaut
    "loggers": {
        "": {  # Root logger
            "handlers": ["console", "file"],
            "level": LOG_LEVEL,
            "propagate": True,
        },
    },
}


# =============================================================================
# APPLICATION GÉNÉRALE
# =============================================================================
APP_CONFIG = {
    "environment": os.getenv("ENVIRONMENT", "development"),
    "debug": os.getenv("DEBUG", "True").lower() == "true",
    "version": "1.0.0",
    "author": "Walid Bourhaleb",
    "github": "https://github.com/WalidBourhaleb/Analysis-of-the-French-real-estate-market",
}


# =============================================================================
# INITIALISATION DU LOGGING
# =============================================================================
def setup_logging():
    """
    Configure le système de logging pour tout le projet.

    Utilisation:
        from config.settings import setup_logging
        setup_logging()

        # Puis dans n'importe quel fichier:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Mon message")
    """
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configuré (niveau: {LOG_LEVEL})")
    logger.info(f"Environnement: {APP_CONFIG['environment']}")
    logger.info(f"Base de données: {DATABASE['host']}:{DATABASE['port']}/{DATABASE['database']}")
    return logger


# =============================================================================
# VÉRIFICATION DE LA CONFIGURATION
# =============================================================================
def check_config():
    """
    Vérifie que la configuration est correcte.
    À exécuter au démarrage du projet.

    Utilisation:
        from config.settings import check_config
        check_config()
    """
    errors = []

    # Vérifier que les dossiers existent
    for dir_name, dir_path in [
        ("DATA_DIR", DATA_DIR),
        ("RAW_DATA_DIR", RAW_DATA_DIR),
        ("PROCESSED_DATA_DIR", PROCESSED_DATA_DIR),
        ("MODELS_DIR", MODELS_DIR),
        ("LOGS_DIR", LOGS_DIR),
    ]:
        if not dir_path.exists():
            errors.append(f"Dossier manquant: {dir_name} ({dir_path})")

    # Vérifier la configuration DB
    if not DATABASE["password"]:
        errors.append(
            "DB_PASSWORD non défini dans .env "
            "(copier .env.example vers .env et remplir)"
        )

    # Vérifier les seuils de qualité
    if DATA_QUALITY["min_price"] >= DATA_QUALITY["max_price"]:
        errors.append("min_price doit être inférieur à max_price")

    if DATA_QUALITY["min_surface"] >= DATA_QUALITY["max_surface"]:
        errors.append("min_surface doit être inférieur à max_surface")

    # Afficher les résultats
    if errors:
        print("\n⚠️  PROBLÈMES DE CONFIGURATION:")
        for error in errors:
            print(f"  ❌ {error}")
        print()
        return False
    else:
        print("✅ Configuration OK")
        return True


# =============================================================================
# AFFICHAGE DE LA CONFIGURATION (pour debug)
# =============================================================================
def print_config():
    """
    Affiche un résumé de la configuration actuelle.
    Utile pour le debug.

    Utilisation:
        from config.settings import print_config
        print_config()
    """
    print("\n" + "=" * 60)
    print("📋 CONFIGURATION DU PROJET")
    print("=" * 60)

    print(f"\n🔧 Environnement: {APP_CONFIG['environment']}")
    print(f"🐛 Debug: {APP_CONFIG['debug']}")
    print(f"📂 Dossier projet: {BASE_DIR}")

    print(f"\n🗄️  Base de données:")
    print(f"   Host: {DATABASE['host']}:{DATABASE['port']}")
    print(f"   Database: {DATABASE['database']}")
    print(f"   User: {DATABASE['user']}")
    print(f"   Password: {'***' if DATABASE['password'] else '❌ NON DÉFINI'}")

    print(f"\n🕷️  Scraping:")
    print(f"   Délai: {SCRAPING_CONFIG['delay_min']}-{SCRAPING_CONFIG['delay_max']}s")
    print(f"   Max pages: {SCRAPING_CONFIG['max_pages_per_search']}")
    print(f"   Max listings/jour: {SCRAPING_CONFIG['max_listings_per_day']}")

    print(f"\n🤖 Machine Learning:")
    print(f"   Modèle: {ML_CONFIG['model_version']}")
    print(f"   XGBoost: n_est={ML_CONFIG['xgboost']['n_estimators']}, "
          f"depth={ML_CONFIG['xgboost']['max_depth']}")
    print(f"   Test size: {ML_CONFIG['test_size']}")

    print(f"\n📊 Qualité données:")
    print(f"   Prix: {DATA_QUALITY['min_price']:,}€ - {DATA_QUALITY['max_price']:,}€")
    print(f"   Surface: {DATA_QUALITY['min_surface']}m² - {DATA_QUALITY['max_surface']}m²")
    print(f"   Prix/m²: {DATA_QUALITY['min_price_m2']:,}€ - {DATA_QUALITY['max_price_m2']:,}€")

    print(f"\n🔑 APIs:")
    print(f"   DVF: {'✅ Clé définie' if DVF_CONFIG['api_key'] else '✅ Publique (pas besoin)'}")
    print(f"   INSEE: {'✅ Clé définie' if INSEE_CONFIG['api_key'] else '⚠️ Non définie'}")
    print(f"   Google Maps: {'✅ Clé définie' if GEOCODING_CONFIG['google_api_key'] else '✅ Nominatim (gratuit)'}")
    print(f"   Geocoding: {GEOCODING_CONFIG['service']}")

    print("\n" + "=" * 60)


# =============================================================================
# EXÉCUTION DIRECTE (pour tester la configuration)
# =============================================================================
if __name__ == "__main__":
    """
    Exécuter directement pour tester:
        python config/settings.py
    """
    print_config()
    check_config()