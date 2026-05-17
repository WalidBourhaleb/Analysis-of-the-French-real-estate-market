"""
=============================================================================
FEATURE ENGINEERING — Création de features pour le Machine Learning
=============================================================================
Crée 25+ features à partir des données nettoyées:
- Features temporelles (saison, jour semaine)
- Features géographiques (distance, densité)
- Features prix (prix/m², ratio)
- Features communales (population, revenu)
- Encodage des catégories

Utilisation:
    python etl/feature_engineering.py
=============================================================================
"""

import psycopg2
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """
    Crée des features avancées pour le modèle ML
    directement dans PostgreSQL (plus efficace que Pandas).
    """

    def __init__(self):
        self.conn = psycopg2.connect(
            host=DATABASE["host"],
            port=DATABASE["port"],
            dbname=DATABASE["database"],
            user=DATABASE["user"],
            password=DATABASE["password"],
        )
        self.conn.autocommit = False
        self.cursor = self.conn.cursor()
        logger.info("FeatureEngineer connecté à PostgreSQL")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def step1_temporal_features(self):
        """
        Étape 1: Features temporelles extraites de date_mutation.
        - annee, mois, trimestre, jour_semaine (déjà via trigger)
        - saison (Hiver/Printemps/Été/Automne)
        - is_weekend
        - jour_dans_annee
        """
        print("\n📅 ÉTAPE 1: Features temporelles")
        print("-" * 50)

        # Vérifier que les features basiques existent (via triggers)
        self.cursor.execute("""
            SELECT COUNT(*) FROM sales WHERE annee IS NULL AND date_mutation IS NOT NULL
        """)
        missing = self.cursor.fetchone()[0]

        if missing > 0:
            print(f"  🔄 {missing:,} lignes sans features temporelles, calcul...")
            self.cursor.execute("""
                UPDATE sales SET
                    annee = EXTRACT(YEAR FROM date_mutation),
                    mois = EXTRACT(MONTH FROM date_mutation),
                    trimestre = EXTRACT(QUARTER FROM date_mutation),
                    jour_semaine = EXTRACT(DOW FROM date_mutation)
                WHERE annee IS NULL AND date_mutation IS NOT NULL
            """)
            self.conn.commit()
            print(f"  ✅ Features basiques calculées")

        # Ajouter colonne saison si n'existe pas
        try:
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS saison VARCHAR(10)")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS is_weekend BOOLEAN")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS jour_annee INT")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.debug(f"Colonnes existent déjà: {e}")

        # Calculer saison
        self.cursor.execute("""
            UPDATE sales SET saison = CASE
                WHEN mois IN (12, 1, 2) THEN 'Hiver'
                WHEN mois IN (3, 4, 5) THEN 'Printemps'
                WHEN mois IN (6, 7, 8) THEN 'Été'
                WHEN mois IN (9, 10, 11) THEN 'Automne'
            END
            WHERE saison IS NULL AND mois IS NOT NULL
        """)
        self.conn.commit()

        # Calculer is_weekend
        self.cursor.execute("""
            UPDATE sales SET is_weekend = (jour_semaine IN (0, 6))
            WHERE is_weekend IS NULL AND jour_semaine IS NOT NULL
        """)
        self.conn.commit()

        # Calculer jour dans l'année
        self.cursor.execute("""
            UPDATE sales SET jour_annee = EXTRACT(DOY FROM date_mutation)
            WHERE jour_annee IS NULL AND date_mutation IS NOT NULL
        """)
        self.conn.commit()

        # Stats
        self.cursor.execute("""
            SELECT saison, COUNT(*) FROM sales
            WHERE saison IS NOT NULL GROUP BY saison ORDER BY COUNT(*) DESC
        """)
        for saison, count in self.cursor.fetchall():
            print(f"  {saison}: {count:,}")

        self.cursor.execute("""
            SELECT is_weekend, COUNT(*) FROM sales
            WHERE is_weekend IS NOT NULL GROUP BY is_weekend
        """)
        for weekend, count in self.cursor.fetchall():
            label = "Weekend" if weekend else "Semaine"
            print(f"  {label}: {count:,}")

    def step2_price_features(self):
        """
        Étape 2: Features de prix.
        - prix_m2 (déjà calculé via trigger)
        - prix_par_piece
        - grande_surface (>100m²)
        - prix_eleve (>75e percentile)
        - categorie_prix (bas/moyen/élevé/luxe)
        """
        print("\n💰 ÉTAPE 2: Features de prix")
        print("-" * 50)

        # Ajouter colonnes
        try:
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS prix_par_piece DECIMAL(10,2)")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS m2_par_piece DECIMAL(10,2)")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS grande_surface BOOLEAN")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS categorie_prix VARCHAR(20)")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.debug(f"Colonnes existent déjà: {e}")

        # Prix par pièce
        self.cursor.execute("""
            UPDATE sales SET prix_par_piece = valeur_fonciere / NULLIF(nb_pieces, 0)
            WHERE nb_pieces > 0
        """)
        self.conn.commit()
        print(f"  ✅ prix_par_piece calculé")

        # m² par pièce
        self.cursor.execute("""
            UPDATE sales SET m2_par_piece = surface_reelle_bati / NULLIF(nb_pieces, 0)
            WHERE nb_pieces > 0 AND surface_reelle_bati > 0
        """)
        self.conn.commit()
        print(f"  ✅ m2_par_piece calculé")

        # Grande surface
        self.cursor.execute("""
            UPDATE sales SET grande_surface = (surface_reelle_bati > 100)
            WHERE surface_reelle_bati IS NOT NULL
        """)
        self.conn.commit()
        print(f"  ✅ grande_surface calculé")

        # Catégorie prix basée sur les percentiles
        self.cursor.execute("""
            WITH percentiles AS (
                SELECT
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY valeur_fonciere) as p25,
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY valeur_fonciere) as p50,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY valeur_fonciere) as p75,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY valeur_fonciere) as p90
                FROM sales
            )
            UPDATE sales SET categorie_prix = CASE
                WHEN valeur_fonciere <= (SELECT p25 FROM percentiles) THEN 'Bas'
                WHEN valeur_fonciere <= (SELECT p50 FROM percentiles) THEN 'Moyen'
                WHEN valeur_fonciere <= (SELECT p75 FROM percentiles) THEN 'Élevé'
                WHEN valeur_fonciere <= (SELECT p90 FROM percentiles) THEN 'Premium'
                ELSE 'Luxe'
            END
        """)
        self.conn.commit()
        print(f"  ✅ categorie_prix calculé")

        # Stats
        self.cursor.execute("""
            SELECT categorie_prix, COUNT(*),
                   ROUND(AVG(valeur_fonciere)::numeric, 0),
                   ROUND(AVG(prix_m2)::numeric, 0)
            FROM sales
            WHERE categorie_prix IS NOT NULL
            GROUP BY categorie_prix
            ORDER BY AVG(valeur_fonciere)
        """)
        print(f"\n  {'Catégorie':<12} {'Ventes':>8} {'Prix moy':>12} {'€/m²':>8}")
        print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*8}")
        for cat, nb, pmoy, pm2 in self.cursor.fetchall():
            print(f"  {cat:<12} {nb:>8,} {pmoy:>11,}€ {pm2:>7,}€")

    def step3_geographic_features(self):
        """
        Étape 3: Features géographiques.
        - proche_centre (<2km)
        - commune_prix_m2_moyen (prix moyen de la commune)
        - commune_nb_ventes
        - commune_population
        - commune_densite
        """
        print("\n🗺️ ÉTAPE 3: Features géographiques")
        print("-" * 50)

        # Ajouter colonnes
        try:
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS proche_centre BOOLEAN")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS commune_prix_m2_moyen DECIMAL(10,2)")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS commune_nb_ventes INT")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS commune_population INT")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS commune_densite DECIMAL(10,2)")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.debug(f"Colonnes existent déjà: {e}")

        # Proche centre (<2km)
        self.cursor.execute("""
            UPDATE sales SET proche_centre = (distance_centre_ville < 2)
            WHERE distance_centre_ville IS NOT NULL
        """)
        self.conn.commit()
        print(f"  ✅ proche_centre calculé")

        # Prix moyen par commune
        self.cursor.execute("""
            WITH commune_avg AS (
                SELECT commune_id, AVG(prix_m2) as avg_pm2, COUNT(*) as nb
                FROM sales
                WHERE commune_id IS NOT NULL AND prix_m2 IS NOT NULL
                GROUP BY commune_id
            )
            UPDATE sales s SET
                commune_prix_m2_moyen = ca.avg_pm2,
                commune_nb_ventes = ca.nb
            FROM commune_avg ca
            WHERE s.commune_id = ca.commune_id
        """)
        self.conn.commit()
        print(f"  ✅ commune_prix_m2_moyen calculé")

        # Population et densité depuis table communes
        self.cursor.execute("""
            UPDATE sales s SET
                commune_population = c.population,
                commune_densite = c.densite_pop
            FROM communes c
            WHERE s.commune_id = c.id
        """)
        self.conn.commit()
        print(f"  ✅ commune_population et commune_densite ajoutés")

        # Stats
        self.cursor.execute("""
            SELECT proche_centre, COUNT(*),
                   ROUND(AVG(prix_m2)::numeric, 0)
            FROM sales
            WHERE proche_centre IS NOT NULL AND prix_m2 IS NOT NULL
            GROUP BY proche_centre
        """)
        for proche, nb, pm2 in self.cursor.fetchall():
            label = "Centre (<2km)" if proche else "Périphérie (>2km)"
            print(f"  {label}: {nb:,} ventes — {pm2:,} €/m²")

    def step4_property_features(self):
        """
        Étape 4: Features liées au bien immobilier.
        - type_local_encoded (numérique)
        - taille_categorie (Studio/Petit/Moyen/Grand/Très grand)
        """
        print("\n🏠 ÉTAPE 4: Features bien immobilier")
        print("-" * 50)

        try:
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS type_local_encoded INT")
            self.cursor.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS taille_categorie VARCHAR(20)")
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()

        # Encoder type_local
        self.cursor.execute("""
            UPDATE sales SET type_local_encoded = CASE
                WHEN type_local = 'Appartement' THEN 1
                WHEN type_local = 'Maison' THEN 2
                WHEN type_local = 'Local commercial' THEN 3
                WHEN type_local = 'Dépendance' THEN 4
                ELSE 0
            END
        """)
        self.conn.commit()
        print(f"  ✅ type_local_encoded calculé")

        # Catégorie taille
        self.cursor.execute("""
            UPDATE sales SET taille_categorie = CASE
                WHEN surface_reelle_bati <= 25 THEN 'Studio'
                WHEN surface_reelle_bati <= 45 THEN 'Petit'
                WHEN surface_reelle_bati <= 75 THEN 'Moyen'
                WHEN surface_reelle_bati <= 120 THEN 'Grand'
                ELSE 'Très grand'
            END
            WHERE surface_reelle_bati IS NOT NULL
        """)
        self.conn.commit()
        print(f"  ✅ taille_categorie calculé")

        # Stats
        self.cursor.execute("""
            SELECT taille_categorie, COUNT(*),
                   ROUND(AVG(prix_m2)::numeric, 0)
            FROM sales
            WHERE taille_categorie IS NOT NULL AND prix_m2 IS NOT NULL
            GROUP BY taille_categorie
            ORDER BY AVG(surface_reelle_bati)
        """)
        print(f"\n  {'Taille':<15} {'Ventes':>8} {'€/m²':>8}")
        print(f"  {'-'*15} {'-'*8} {'-'*8}")
        for cat, nb, pm2 in self.cursor.fetchall():
            print(f"  {cat:<15} {nb:>8,} {pm2:>7,}€")

    def step5_summary(self):
        """
        Étape 5: Résumé de toutes les features créées.
        """
        print("\n📋 ÉTAPE 5: Résumé des features")
        print("-" * 50)

        # Compter les colonnes
        self.cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'sales'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in self.cursor.fetchall()]

        print(f"  Total colonnes dans sales: {len(columns)}")
        print(f"\n  Features créées:")

        feature_groups = {
            "Temporelles": ["annee", "mois", "trimestre", "jour_semaine", "saison", "is_weekend", "jour_annee"],
            "Prix": ["prix_m2", "prix_par_piece", "m2_par_piece", "grande_surface", "categorie_prix"],
            "Géographiques": ["latitude", "longitude", "distance_centre_ville", "proche_centre",
                            "commune_prix_m2_moyen", "commune_nb_ventes", "commune_population", "commune_densite"],
            "Bien immobilier": ["type_local_encoded", "taille_categorie"],
            "Qualité": ["data_quality_score"],
        }

        total_features = 0
        for group, features in feature_groups.items():
            existing = [f for f in features if f in columns]
            total_features += len(existing)
            print(f"\n  {group} ({len(existing)}):")
            for f in existing:
                # Compter non-null
                self.cursor.execute(f"SELECT COUNT(*) FROM sales WHERE {f} IS NOT NULL")
                count = self.cursor.fetchone()[0]
                self.cursor.execute("SELECT COUNT(*) FROM sales")
                total = self.cursor.fetchone()[0]
                pct = count / total * 100 if total > 0 else 0
                print(f"    ✅ {f} — {count:,} ({pct:.0f}%)")

        print(f"\n  📊 Total features créées: {total_features}")

    def run_all(self):
        """Exécute toutes les étapes de feature engineering."""
        print(f"\n{'=' * 60}")
        print(f"🔧 FEATURE ENGINEERING")
        print(f"{'=' * 60}")

        self.step1_temporal_features()
        self.step2_price_features()
        self.step3_geographic_features()
        self.step4_property_features()
        self.step5_summary()

        print(f"\n{'=' * 60}")
        print(f"✅ FEATURE ENGINEERING TERMINÉ !")
        print(f"{'=' * 60}")


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    engineer = FeatureEngineer()

    try:
        engineer.run_all()
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        logger.error(f"Erreur: {e}", exc_info=True)
    finally:
        engineer.close()