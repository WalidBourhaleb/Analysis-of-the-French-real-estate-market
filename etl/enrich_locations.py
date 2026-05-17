"""
=============================================================================
ENRICH LOCATIONS — Enrichissement géographique des ventes
=============================================================================
Ce script:
1. Ajoute les coordonnées GPS aux ventes via les communes
2. Rattache les ventes non-liées aux communes (fuzzy matching)
3. Calcule la distance au centre-ville
4. Compte les POI à proximité (si disponible)

Utilisation:
    python etl/enrich_locations.py
    python etl/enrich_locations.py --test    # Mode test (100 ventes)
=============================================================================
"""

import psycopg2
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE

logger = logging.getLogger(__name__)


class LocationEnricher:
    """
    Enrichit les ventes avec des données géographiques:
    - Coordonnées GPS (depuis la table communes)
    - Distance au centre-ville
    - Rattachement des ventes orphelines
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
        logger.info("LocationEnricher connecté à PostgreSQL")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Connexion fermée")

    def _get_stats(self):
        """Récupère les statistiques actuelles."""
        stats = {}

        self.cursor.execute("SELECT COUNT(*) FROM sales")
        stats["total_sales"] = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sales WHERE commune_id IS NOT NULL")
        stats["linked_sales"] = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sales WHERE latitude IS NOT NULL")
        stats["geocoded_sales"] = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM communes")
        stats["total_communes"] = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM communes WHERE latitude IS NOT NULL")
        stats["geocoded_communes"] = self.cursor.fetchone()[0]

        return stats

    def step1_link_remaining_sales(self):
        """
        Étape 1: Rattacher les ventes non-liées aux communes.
        Essaie plusieurs méthodes de matching.
        """
        print("\n📌 ÉTAPE 1: Rattachement des ventes aux communes")
        print("-" * 50)

        # 1a. Match exact par code_commune
        self.cursor.execute("""
            UPDATE sales s
            SET commune_id = c.id
            FROM communes c
            WHERE s.code_commune = c.code_commune
            AND s.commune_id IS NULL
        """)
        linked_exact = self.cursor.rowcount
        self.conn.commit()
        print(f"  ✅ Match exact code_commune: {linked_exact:,} ventes rattachées")

        # 1b. Match par code_commune sans le zéro initial
        self.cursor.execute("""
            UPDATE sales s
            SET commune_id = c.id
            FROM communes c
            WHERE LTRIM(s.code_commune, '0') = LTRIM(c.code_commune, '0')
            AND s.commune_id IS NULL
        """)
        linked_ltrim = self.cursor.rowcount
        self.conn.commit()
        print(f"  ✅ Match sans zéro initial: {linked_ltrim:,} ventes rattachées")

        # 1c. Match par code_postal → code_commune
        self.cursor.execute("""
            UPDATE sales s
            SET commune_id = c.id
            FROM communes c
            WHERE s.code_postal = c.code_postal
            AND s.commune_id IS NULL
            AND c.code_postal IS NOT NULL
        """)
        linked_cp = self.cursor.rowcount
        self.conn.commit()
        print(f"  ✅ Match par code postal: {linked_cp:,} ventes rattachées")

        total_linked = linked_exact + linked_ltrim + linked_cp
        print(f"  📊 Total nouvelles liaisons: {total_linked:,}")

        return total_linked

    def step2_add_coordinates(self):
        """
        Étape 2: Ajouter les coordonnées GPS aux ventes
        depuis la table communes.
        """
        print("\n📍 ÉTAPE 2: Ajout coordonnées GPS aux ventes")
        print("-" * 50)

        # Copier lat/lon depuis la commune liée
        self.cursor.execute("""
            UPDATE sales s
            SET
                latitude = c.latitude,
                longitude = c.longitude
            FROM communes c
            WHERE s.commune_id = c.id
            AND s.latitude IS NULL
            AND c.latitude IS NOT NULL
        """)
        geocoded = self.cursor.rowcount
        self.conn.commit()
        print(f"  ✅ {geocoded:,} ventes géocodées (coordonnées ajoutées)")

        return geocoded

    def step3_calculate_distance_center(self):
        """
        Étape 3: Calculer la distance entre chaque vente et le centre
        de sa commune (en km).
        Utilise PostGIS si les geometries sont disponibles.
        """
        print("\n📏 ÉTAPE 3: Calcul distance au centre-ville")
        print("-" * 50)

        # Vérifier si PostGIS est disponible et si les geometries existent
        try:
            self.cursor.execute("""
                SELECT COUNT(*)
                FROM sales
                WHERE geometry IS NOT NULL
            """)
            sales_with_geom = self.cursor.fetchone()[0]

            self.cursor.execute("""
                SELECT COUNT(*)
                FROM communes
                WHERE geometry IS NOT NULL
            """)
            communes_with_geom = self.cursor.fetchone()[0]

            print(f"  Ventes avec geometry: {sales_with_geom:,}")
            print(f"  Communes avec geometry: {communes_with_geom:,}")

            if sales_with_geom > 0 and communes_with_geom > 0:
                # Calcul via PostGIS (précis)
                self.cursor.execute("""
                    UPDATE sales s
                    SET distance_centre_ville = ST_Distance(
                        s.geometry::geography,
                        c.geometry::geography
                    ) / 1000.0
                    FROM communes c
                    WHERE s.commune_id = c.id
                    AND s.geometry IS NOT NULL
                    AND c.geometry IS NOT NULL
                    AND s.distance_centre_ville IS NULL
                """)
                calculated = self.cursor.rowcount
                self.conn.commit()
                print(f"  ✅ {calculated:,} distances calculées (PostGIS)")
            else:
                # Calcul via lat/lon (approximatif mais suffisant)
                self.cursor.execute("""
                    UPDATE sales s
                    SET distance_centre_ville = (
                        6371 * ACOS(
                            LEAST(1.0,
                                COS(RADIANS(s.latitude)) * COS(RADIANS(c.latitude)) *
                                COS(RADIANS(c.longitude) - RADIANS(s.longitude)) +
                                SIN(RADIANS(s.latitude)) * SIN(RADIANS(c.latitude))
                            )
                        )
                    )
                    FROM communes c
                    WHERE s.commune_id = c.id
                    AND s.latitude IS NOT NULL
                    AND c.latitude IS NOT NULL
                    AND s.distance_centre_ville IS NULL
                """)
                calculated = self.cursor.rowcount
                self.conn.commit()
                print(f"  ✅ {calculated:,} distances calculées (Haversine)")

            return calculated

        except Exception as e:
            logger.warning(f"  ⚠️ Erreur calcul distances: {e}")
            self.conn.rollback()
            return 0

    def step4_enrich_with_commune_data(self):
        """
        Étape 4: Ajouter des statistiques communales aux ventes.
        Prix moyen par commune, nombre de ventes, etc.
        """
        print("\n📊 ÉTAPE 4: Enrichissement avec données communales")
        print("-" * 50)

        # Calculer le prix moyen au m² par commune
        try:
            self.cursor.execute("""
                CREATE TEMP TABLE IF NOT EXISTS commune_stats AS
                SELECT
                    commune_id,
                    COUNT(*) as nb_ventes,
                    AVG(prix_m2) as prix_m2_moyen,
                    AVG(valeur_fonciere) as prix_moyen,
                    AVG(surface_reelle_bati) as surface_moyenne
                FROM sales
                WHERE commune_id IS NOT NULL
                AND prix_m2 IS NOT NULL
                AND prix_m2 > 0
                GROUP BY commune_id
            """)
            self.conn.commit()

            self.cursor.execute("SELECT COUNT(*) FROM commune_stats")
            nb_communes_stats = self.cursor.fetchone()[0]
            print(f"  ✅ Statistiques calculées pour {nb_communes_stats:,} communes")

            # Afficher le top 10
            self.cursor.execute("""
                SELECT c.nom_commune, c.departement, cs.nb_ventes,
                       ROUND(cs.prix_m2_moyen::numeric, 0) as prix_m2,
                       ROUND(cs.prix_moyen::numeric, 0) as prix_moy
                FROM commune_stats cs
                JOIN communes c ON cs.commune_id = c.id
                ORDER BY cs.nb_ventes DESC
                LIMIT 10
            """)
            top = self.cursor.fetchall()

            if top:
                print(f"\n  Top 10 communes par nombre de ventes:")
                print(f"  {'Commune':<25} {'Dept':<5} {'Ventes':>7} {'€/m²':>8} {'Prix moy':>12}")
                print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*8} {'-'*12}")
                for nom, dept, nb, pm2, pmoy in top:
                    pm2_str = f"{pm2:,.0f}" if pm2 else "N/A"
                    pmoy_str = f"{pmoy:,.0f} €" if pmoy else "N/A"
                    print(f"  {nom:<25} {dept:<5} {nb:>7,} {pm2_str:>8} {pmoy_str:>12}")

            # Nettoyer
            self.cursor.execute("DROP TABLE IF EXISTS commune_stats")
            self.conn.commit()

            return nb_communes_stats

        except Exception as e:
            logger.warning(f"  ⚠️ Erreur stats communes: {e}")
            self.conn.rollback()
            return 0

    def step5_verify_data_quality(self):
        """
        Étape 5: Vérification de la qualité des données enrichies.
        """
        print("\n🔍 ÉTAPE 5: Vérification qualité des données")
        print("-" * 50)

        # Stats générales
        self.cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(commune_id) as with_commune,
                COUNT(latitude) as with_coords,
                COUNT(prix_m2) as with_prix_m2,
                COUNT(distance_centre_ville) as with_distance,
                COUNT(CASE WHEN type_local = 'Appartement' THEN 1 END) as appartements,
                COUNT(CASE WHEN type_local = 'Maison' THEN 1 END) as maisons,
                MIN(date_mutation) as date_min,
                MAX(date_mutation) as date_max,
                AVG(valeur_fonciere) as prix_moyen,
                AVG(prix_m2) as prix_m2_moyen,
                AVG(surface_reelle_bati) as surface_moyenne
            FROM sales
        """)
        row = self.cursor.fetchone()

        total = row[0]
        print(f"  📊 Total ventes: {total:,}")
        print(f"  🏘️ Avec commune: {row[1]:,} ({row[1]/total*100:.1f}%)")
        print(f"  📍 Avec coordonnées: {row[2]:,} ({row[2]/total*100:.1f}%)")
        print(f"  💰 Avec prix/m²: {row[3]:,} ({row[3]/total*100:.1f}%)")
        print(f"  📏 Avec distance: {row[4]:,} ({row[4]/total*100:.1f}%)")
        print(f"  🏢 Appartements: {row[5]:,}")
        print(f"  🏠 Maisons: {row[6]:,}")
        print(f"  📅 Période: {row[7]} → {row[8]}")

        if row[9]:
            print(f"  💶 Prix moyen: {row[9]:,.0f} €")
        if row[10]:
            print(f"  📐 Prix/m² moyen: {row[10]:,.0f} €/m²")
        if row[11]:
            print(f"  📏 Surface moyenne: {row[11]:,.0f} m²")

        # Répartition par département
        self.cursor.execute("""
            SELECT c.departement, COUNT(*) as nb,
                   ROUND(AVG(s.prix_m2)::numeric, 0) as prix_m2_moy
            FROM sales s
            JOIN communes c ON s.commune_id = c.id
            WHERE s.prix_m2 IS NOT NULL
            GROUP BY c.departement
            ORDER BY nb DESC
        """)
        depts = self.cursor.fetchall()

        if depts:
            print(f"\n  Par département:")
            for dept, nb, pm2 in depts:
                pm2_str = f"{pm2:,.0f} €/m²" if pm2 else "N/A"
                print(f"    Dept {dept}: {nb:,} ventes — {pm2_str}")

    def run_all(self, test_mode=False):
        """
        Exécute toutes les étapes d'enrichissement.
        """
        print(f"\n{'=' * 60}")
        print(f"🗺️  ENRICHISSEMENT GÉOGRAPHIQUE DES VENTES")
        print(f"{'=' * 60}")

        # Stats avant
        stats_before = self._get_stats()
        print(f"\n📋 État avant enrichissement:")
        print(f"  Ventes totales: {stats_before['total_sales']:,}")
        print(f"  Ventes liées: {stats_before['linked_sales']:,}")
        print(f"  Ventes géocodées: {stats_before['geocoded_sales']:,}")
        print(f"  Communes: {stats_before['total_communes']:,}")

        # Exécuter les étapes
        self.step1_link_remaining_sales()
        self.step2_add_coordinates()
        self.step3_calculate_distance_center()
        self.step4_enrich_with_commune_data()
        self.step5_verify_data_quality()

        # Stats après
        stats_after = self._get_stats()

        print(f"\n{'=' * 60}")
        print(f"📊 RÉSUMÉ ENRICHISSEMENT")
        print(f"{'=' * 60}")
        print(f"  Ventes liées: {stats_before['linked_sales']:,} → {stats_after['linked_sales']:,} (+{stats_after['linked_sales']-stats_before['linked_sales']:,})")
        print(f"  Ventes géocodées: {stats_before['geocoded_sales']:,} → {stats_after['geocoded_sales']:,} (+{stats_after['geocoded_sales']-stats_before['geocoded_sales']:,})")
        print(f"  Taux liaison: {stats_after['linked_sales']/stats_after['total_sales']*100:.1f}%")
        print(f"  Taux géocodage: {stats_after['geocoded_sales']/stats_after['total_sales']*100:.1f}%")
        print(f"{'=' * 60}")


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enrichissement géographique")
    parser.add_argument("--test", action="store_true", help="Mode test")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    enricher = LocationEnricher()

    try:
        enricher.run_all(test_mode=args.test)
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        logger.error(f"Erreur: {e}", exc_info=True)
    finally:
        enricher.close()