"""
=============================================================================
TRANSFORM — Nettoyage avancé des données DVF
=============================================================================
Ce script:
1. Supprime les doublons restants
2. Filtre les outliers (prix, surface, prix/m²)
3. Standardise les types de biens
4. Calcule le data quality score
5. Sauvegarde les données nettoyées dans une table dédiée

Utilisation:
    python etl/transform.py
    python etl/transform.py --test    # Mode test (aperçu sans modifier la DB)
=============================================================================
"""

import pandas as pd
import psycopg2
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE, DATA_QUALITY

logger = logging.getLogger(__name__)


class DataCleaner:
    """
    Nettoie les données DVF dans PostgreSQL.
    Applique les filtres de qualité, supprime les outliers,
    standardise les types et calcule un score de qualité.
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
        self.thresholds = DATA_QUALITY
        logger.info("DataCleaner connecté à PostgreSQL")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Connexion fermée")

    def _get_count(self, condition=""):
        """Compte le nombre de lignes avec une condition optionnelle."""
        query = f"SELECT COUNT(*) FROM sales {condition}"
        self.cursor.execute(query)
        return self.cursor.fetchone()[0]

    def step1_remove_duplicates(self):
        """
        Étape 1: Supprime les doublons exacts.
        Garde la première occurrence basée sur dvf_id.
        """
        print("\n🔄 ÉTAPE 1: Suppression des doublons")
        print("-" * 50)

        before = self._get_count()

        # Trouver et supprimer les doublons sur les colonnes clés
        self.cursor.execute("""
            DELETE FROM sales a
            USING sales b
            WHERE a.id > b.id
            AND a.date_mutation = b.date_mutation
            AND a.valeur_fonciere = b.valeur_fonciere
            AND a.code_commune = b.code_commune
            AND COALESCE(a.surface_reelle_bati, 0) = COALESCE(b.surface_reelle_bati, 0)
            AND COALESCE(a.type_local, '') = COALESCE(b.type_local, '')
        """)
        removed = self.cursor.rowcount
        self.conn.commit()

        after = self._get_count()
        print(f"  Avant: {before:,}")
        print(f"  Doublons supprimés: {removed:,}")
        print(f"  Après: {after:,}")

        return removed

    def step2_filter_price_outliers(self):
        """
        Étape 2: Filtre les prix aberrants.
        Supprime les ventes avec prix < min ou > max.
        """
        print("\n💰 ÉTAPE 2: Filtrage outliers prix")
        print("-" * 50)

        min_price = self.thresholds["min_price"]
        max_price = self.thresholds["max_price"]

        before = self._get_count()

        # Prix trop bas
        self.cursor.execute(f"""
            DELETE FROM sales
            WHERE valeur_fonciere < {min_price}
        """)
        removed_low = self.cursor.rowcount

        # Prix trop haut
        self.cursor.execute(f"""
            DELETE FROM sales
            WHERE valeur_fonciere > {max_price}
        """)
        removed_high = self.cursor.rowcount

        self.conn.commit()
        after = self._get_count()

        print(f"  Seuils: {min_price:,}€ — {max_price:,}€")
        print(f"  Prix trop bas (<{min_price:,}€): {removed_low:,} supprimées")
        print(f"  Prix trop haut (>{max_price:,}€): {removed_high:,} supprimées")
        print(f"  Restant: {after:,}")

        return removed_low + removed_high

    def step3_filter_surface_outliers(self):
        """
        Étape 3: Filtre les surfaces aberrantes.
        """
        print("\n📐 ÉTAPE 3: Filtrage outliers surface")
        print("-" * 50)

        min_surface = self.thresholds["min_surface"]
        max_surface = self.thresholds["max_surface"]

        before = self._get_count()

        # Surface trop petite (mais garder les NULL)
        self.cursor.execute(f"""
            DELETE FROM sales
            WHERE surface_reelle_bati IS NOT NULL
            AND surface_reelle_bati < {min_surface}
        """)
        removed_small = self.cursor.rowcount

        # Surface trop grande
        self.cursor.execute(f"""
            DELETE FROM sales
            WHERE surface_reelle_bati IS NOT NULL
            AND surface_reelle_bati > {max_surface}
        """)
        removed_big = self.cursor.rowcount

        self.conn.commit()
        after = self._get_count()

        print(f"  Seuils: {min_surface}m² — {max_surface}m²")
        print(f"  Surface trop petite (<{min_surface}m²): {removed_small:,} supprimées")
        print(f"  Surface trop grande (>{max_surface}m²): {removed_big:,} supprimées")
        print(f"  Restant: {after:,}")

        return removed_small + removed_big

    def step4_filter_price_m2_outliers(self):
        """
        Étape 4: Filtre les prix/m² aberrants.
        """
        print("\n📊 ÉTAPE 4: Filtrage outliers prix/m²")
        print("-" * 50)

        min_pm2 = self.thresholds["min_price_m2"]
        max_pm2 = self.thresholds["max_price_m2"]

        before = self._get_count()

        # Recalculer prix_m2 pour être sûr
        self.cursor.execute("""
            UPDATE sales
            SET prix_m2 = valeur_fonciere / NULLIF(surface_reelle_bati, 0)
            WHERE surface_reelle_bati > 0
        """)
        self.conn.commit()

        # Supprimer prix/m² aberrants
        self.cursor.execute(f"""
            DELETE FROM sales
            WHERE prix_m2 IS NOT NULL
            AND (prix_m2 < {min_pm2} OR prix_m2 > {max_pm2})
        """)
        removed = self.cursor.rowcount
        self.conn.commit()

        after = self._get_count()

        print(f"  Seuils: {min_pm2:,}€/m² — {max_pm2:,}€/m²")
        print(f"  Prix/m² aberrants supprimés: {removed:,}")
        print(f"  Restant: {after:,}")

        return removed

    def step5_standardize_types(self):
        """
        Étape 5: Standardise les types de biens.
        """
        print("\n🏠 ÉTAPE 5: Standardisation types de biens")
        print("-" * 50)

        # Mapping des types
        type_mapping = {
            "Appartement": "Appartement",
            "Maison": "Maison",
            "Local industriel. commercial ou assimilé": "Local commercial",
            "Dépendance": "Dépendance",
        }

        for old_type, new_type in type_mapping.items():
            if old_type != new_type:
                self.cursor.execute("""
                    UPDATE sales SET type_local = %s WHERE type_local = %s
                """, (new_type, old_type))

        self.conn.commit()

        # Afficher la distribution
        self.cursor.execute("""
            SELECT type_local, COUNT(*) as nb
            FROM sales
            WHERE type_local IS NOT NULL
            GROUP BY type_local
            ORDER BY nb DESC
        """)
        types = self.cursor.fetchall()

        print(f"  Distribution des types:")
        for type_name, count in types:
            print(f"    {type_name}: {count:,}")

        # Compter les NULL
        self.cursor.execute("SELECT COUNT(*) FROM sales WHERE type_local IS NULL")
        null_count = self.cursor.fetchone()[0]
        if null_count > 0:
            print(f"    (Type inconnu): {null_count:,}")

    def step6_calculate_quality_score(self):
        """
        Étape 6: Calcule un score de qualité pour chaque vente (0-100).
        Plus il y a de champs remplis, plus le score est élevé.
        """
        print("\n⭐ ÉTAPE 6: Calcul score qualité données")
        print("-" * 50)

        self.cursor.execute("""
            UPDATE sales SET data_quality_score =
                -- Score de base
                50
                -- Bonus pour chaque champ rempli
                + CASE WHEN type_local IS NOT NULL THEN 5 ELSE 0 END
                + CASE WHEN surface_reelle_bati IS NOT NULL THEN 10 ELSE 0 END
                + CASE WHEN nb_pieces IS NOT NULL THEN 5 ELSE 0 END
                + CASE WHEN code_postal IS NOT NULL THEN 3 ELSE 0 END
                + CASE WHEN commune_id IS NOT NULL THEN 5 ELSE 0 END
                + CASE WHEN latitude IS NOT NULL THEN 7 ELSE 0 END
                + CASE WHEN prix_m2 IS NOT NULL THEN 10 ELSE 0 END
                + CASE WHEN adresse_nom_voie IS NOT NULL THEN 3 ELSE 0 END
                + CASE WHEN distance_centre_ville IS NOT NULL THEN 2 ELSE 0 END
        """)
        self.conn.commit()

        # Distribution des scores
        self.cursor.execute("""
            SELECT
                CASE
                    WHEN data_quality_score >= 90 THEN 'Excellent (90-100)'
                    WHEN data_quality_score >= 75 THEN 'Bon (75-89)'
                    WHEN data_quality_score >= 60 THEN 'Moyen (60-74)'
                    ELSE 'Faible (<60)'
                END as qualite,
                COUNT(*) as nb
            FROM sales
            GROUP BY 1
            ORDER BY 1
        """)
        distribution = self.cursor.fetchall()

        total = self._get_count()
        print(f"  Distribution qualité:")
        for qualite, nb in distribution:
            pct = nb / total * 100
            bar = "█" * int(pct / 2)
            print(f"    {qualite:<22} {nb:>7,} ({pct:5.1f}%) {bar}")

        # Score moyen
        self.cursor.execute("SELECT AVG(data_quality_score) FROM sales")
        avg_score = self.cursor.fetchone()[0]
        print(f"\n  Score moyen: {avg_score:.1f}/100")

    def step7_final_statistics(self):
        """
        Étape 7: Statistiques finales après nettoyage.
        """
        print("\n📊 ÉTAPE 7: Statistiques finales")
        print("-" * 50)

        self.cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN type_local = 'Appartement' THEN 1 END) as apparts,
                COUNT(CASE WHEN type_local = 'Maison' THEN 1 END) as maisons,
                COUNT(commune_id) as with_commune,
                COUNT(latitude) as with_coords,
                COUNT(prix_m2) as with_prix_m2,
                ROUND(AVG(valeur_fonciere)::numeric, 0) as prix_moyen,
                ROUND(AVG(prix_m2)::numeric, 0) as prix_m2_moyen,
                ROUND(AVG(surface_reelle_bati)::numeric, 1) as surface_moy,
                MIN(date_mutation) as date_min,
                MAX(date_mutation) as date_max
            FROM sales
        """)
        row = self.cursor.fetchone()

        total = row[0]
        print(f"  📊 Total ventes: {total:,}")
        print(f"  🏢 Appartements: {row[1]:,}")
        print(f"  🏠 Maisons: {row[2]:,}")
        print(f"  🏘️ Avec commune: {row[3]:,} ({row[3]/total*100:.1f}%)")
        print(f"  📍 Avec GPS: {row[4]:,} ({row[4]/total*100:.1f}%)")
        print(f"  💰 Avec prix/m²: {row[5]:,} ({row[5]/total*100:.1f}%)")
        print(f"  💶 Prix moyen: {row[6]:,} €")
        print(f"  📐 Prix/m² moyen: {row[7]:,} €/m²")
        print(f"  📏 Surface moyenne: {row[8]} m²")
        print(f"  📅 Période: {row[9]} → {row[10]}")

        # Par département
        self.cursor.execute("""
            SELECT c.departement,
                   COUNT(*) as nb,
                   ROUND(AVG(s.prix_m2)::numeric, 0) as pm2,
                   ROUND(AVG(s.valeur_fonciere)::numeric, 0) as pmoy
            FROM sales s
            JOIN communes c ON s.commune_id = c.id
            WHERE s.prix_m2 IS NOT NULL
            GROUP BY c.departement
            ORDER BY nb DESC
        """)
        depts = self.cursor.fetchall()

        if depts:
            print(f"\n  Par département:")
            print(f"  {'Dept':<6} {'Ventes':>8} {'€/m²':>8} {'Prix moy':>12}")
            print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*12}")
            for dept, nb, pm2, pmoy in depts:
                print(f"  {dept:<6} {nb:>8,} {pm2:>7,}€ {pmoy:>11,}€")

    def run_all(self, test_mode=False):
        """
        Exécute toutes les étapes de nettoyage.
        """
        print(f"\n{'=' * 60}")
        print(f"🧹 NETTOYAGE DES DONNÉES DVF")
        print(f"{'=' * 60}")

        initial_count = self._get_count()
        print(f"\n📋 Données avant nettoyage: {initial_count:,} ventes")

        if test_mode:
            print("\n⚠️ MODE TEST: aperçu des données sans modification")
            self.step7_final_statistics()
            return

        # Exécuter toutes les étapes
        dup = self.step1_remove_duplicates()
        price = self.step2_filter_price_outliers()
        surface = self.step3_filter_surface_outliers()
        pm2 = self.step4_filter_price_m2_outliers()
        self.step5_standardize_types()
        self.step6_calculate_quality_score()
        self.step7_final_statistics()

        # Résumé
        final_count = self._get_count()
        total_removed = initial_count - final_count

        print(f"\n{'=' * 60}")
        print(f"📊 RÉSUMÉ DU NETTOYAGE")
        print(f"{'=' * 60}")
        print(f"  Avant: {initial_count:,} ventes")
        print(f"  Après: {final_count:,} ventes")
        print(f"  Supprimées: {total_removed:,} ({total_removed/initial_count*100:.1f}%)")
        print(f"    - Doublons: {dup:,}")
        print(f"    - Prix aberrants: {price:,}")
        print(f"    - Surfaces aberrantes: {surface:,}")
        print(f"    - Prix/m² aberrants: {pm2:,}")
        print(f"  Taux de conservation: {final_count/initial_count*100:.1f}%")
        print(f"{'=' * 60}")


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nettoyage données DVF")
    parser.add_argument("--test", action="store_true", help="Mode test (aperçu sans modifier)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    cleaner = DataCleaner()

    try:
        cleaner.run_all(test_mode=args.test)
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        logger.error(f"Erreur: {e}", exc_info=True)
    finally:
        cleaner.close()