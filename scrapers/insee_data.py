"""
=============================================================================
INSEE DATA — Récupération données socio-économiques par commune
=============================================================================
Source: API geo.api.gouv.fr (gratuit, pas besoin de clé API)

Données récupérées: population, code postal, département, région,
coordonnées GPS (latitude/longitude)

Utilisation:
    python scrapers/insee_data.py
=============================================================================
"""

import requests
import pandas as pd
import psycopg2
import logging
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE

logger = logging.getLogger(__name__)


class INSEEDataFetcher:
    """
    Récupère les données communales depuis l'API geo.api.gouv.fr.
    API gratuite, pas besoin de clé, très fiable.
    """

    def __init__(self):
        self.api_url = "https://geo.api.gouv.fr"
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "ImmobilierAnalysis/1.0",
        })

        self.conn = psycopg2.connect(
            host=DATABASE["host"],
            port=DATABASE["port"],
            dbname=DATABASE["database"],
            user=DATABASE["user"],
            password=DATABASE["password"],
        )
        self.conn.autocommit = False
        self.cursor = self.conn.cursor()

        logger.info("INSEEDataFetcher initialisé")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def fetch_commune_info(self, code_commune: str) -> dict:
        """
        Récupère les infos d'une commune par son code INSEE.

        Args:
            code_commune: Code INSEE (ex: "75056" pour Paris)

        Returns:
            Dict avec les infos de la commune
        """
        url = f"{self.api_url}/communes/{code_commune}"
        params = {
            "fields": "nom,code,codesPostaux,codeDepartement,codeRegion,population,surface,centre",
            "format": "json",
        }

        try:
            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return {
                    "code_commune": data.get("code", ""),
                    "nom_commune": data.get("nom", ""),
                    "code_postal": data.get("codesPostaux", [None])[0],
                    "departement": data.get("codeDepartement", ""),
                    "region": data.get("codeRegion", ""),
                    "population": data.get("population"),
                    "superficie_km2": data.get("surface", 0) / 100 if data.get("surface") else None,
                    "latitude": data.get("centre", {}).get("coordinates", [None, None])[1],
                    "longitude": data.get("centre", {}).get("coordinates", [None, None])[0],
                }
            else:
                logger.warning(f"  ⚠️ HTTP {response.status_code} pour commune {code_commune}")
                return None

        except Exception as e:
            logger.warning(f"  ⚠️ Erreur commune {code_commune}: {e}")
            return None

    def fetch_department_communes(self, departement: str) -> list:
        """
        Récupère toutes les communes d'un département.

        Args:
            departement: Code département (ex: "75", "69")

        Returns:
            Liste de dicts avec les infos des communes
        """
        url = f"{self.api_url}/departements/{departement}/communes"
        params = {
            "fields": "nom,code,codesPostaux,codeDepartement,codeRegion,population,surface,centre",
            "format": "json",
        }

        try:
            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                communes = []

                for item in data:
                    commune = {
                        "code_commune": item.get("code", ""),
                        "nom_commune": item.get("nom", ""),
                        "code_postal": item.get("codesPostaux", [None])[0],
                        "departement": item.get("codeDepartement", ""),
                        "region": item.get("codeRegion", ""),
                        "population": item.get("population"),
                        "superficie_km2": item.get("surface", 0) / 100 if item.get("surface") else None,
                        "latitude": item.get("centre", {}).get("coordinates", [None, None])[1],
                        "longitude": item.get("centre", {}).get("coordinates", [None, None])[0],
                    }
                    communes.append(commune)

                return communes
            else:
                logger.warning(f"  ⚠️ HTTP {response.status_code} pour dept {departement}")
                return []

        except Exception as e:
            logger.error(f"  ❌ Erreur dept {departement}: {e}")
            return []

    def update_communes_in_db(self, departements: list = None):
        """
        Met à jour la table communes dans PostgreSQL avec les données de l'API.

        Args:
            departements: Liste codes dept (ex: ["75", "69", "13"])
                         Si None, utilise les départements des ventes en base
        """
        if departements is None:
            # Récupérer les départements présents dans les ventes
            self.cursor.execute("""
                SELECT DISTINCT LEFT(code_commune, 2) as dept
                FROM sales
                WHERE code_commune IS NOT NULL
                ORDER BY dept
            """)
            departements = [row[0] for row in self.cursor.fetchall()]

            # Aussi chercher les départements à 3 chiffres (DOM-TOM style "2A", "2B")
            self.cursor.execute("""
                SELECT DISTINCT LEFT(code_commune, 3) as dept
                FROM sales
                WHERE code_commune IS NOT NULL
                AND LEFT(code_commune, 2) IN ('97', '2A', '2B')
            """)
            departements += [row[0] for row in self.cursor.fetchall()]

        if not departements:
            print("❌ Aucun département trouvé dans les ventes")
            return

        print(f"\n📊 Mise à jour communes pour {len(departements)} départements:")
        print(f"   Départements: {', '.join(departements)}")

        total_inserted = 0
        total_updated = 0

        for dept in departements:
            print(f"\n  📍 Département {dept}...")
            communes = self.fetch_department_communes(dept)

            if not communes:
                print(f"    ⚠️ Aucune commune trouvée")
                continue

            print(f"    📄 {len(communes)} communes récupérées")

            for commune in communes:
                try:
                    # UPSERT: insert ou update si existe déjà
                    self.cursor.execute("""
                        INSERT INTO communes (
                            code_commune, nom_commune, code_postal,
                            departement, region, population,
                            superficie_km2, latitude, longitude
                        ) VALUES (
                            %(code_commune)s, %(nom_commune)s, %(code_postal)s,
                            %(departement)s, %(region)s, %(population)s,
                            %(superficie_km2)s, %(latitude)s, %(longitude)s
                        )
                        ON CONFLICT (code_commune) DO UPDATE SET
                            nom_commune = EXCLUDED.nom_commune,
                            code_postal = EXCLUDED.code_postal,
                            departement = EXCLUDED.departement,
                            region = EXCLUDED.region,
                            population = EXCLUDED.population,
                            superficie_km2 = EXCLUDED.superficie_km2,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            updated_at = CURRENT_TIMESTAMP
                    """, commune)

                    if self.cursor.statusmessage == "INSERT 0 1":
                        total_inserted += 1
                    else:
                        total_updated += 1

                except Exception as e:
                    logger.warning(f"    ⚠️ Erreur commune {commune['code_commune']}: {e}")
                    self.conn.rollback()
                    continue

            self.conn.commit()
            print(f"    ✅ Communes sauvegardées")
            time.sleep(0.5)

        # Rattacher les ventes aux communes
        print(f"\n  🔗 Rattachement des ventes aux communes...")
        self.cursor.execute("""
            UPDATE sales s
            SET commune_id = c.id
            FROM communes c
            WHERE s.code_commune = c.code_commune
            AND s.commune_id IS NULL
        """)
        linked = self.cursor.rowcount
        self.conn.commit()

        # Calculer densité population
        print(f"  📊 Calcul densité population...")
        self.cursor.execute("""
            UPDATE communes
            SET densite_pop = population / NULLIF(superficie_km2, 0)
            WHERE population IS NOT NULL
            AND superficie_km2 IS NOT NULL
            AND superficie_km2 > 0
        """)
        self.conn.commit()

        # Résumé
        self.cursor.execute("SELECT COUNT(*) FROM communes")
        total_communes = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sales WHERE commune_id IS NOT NULL")
        total_linked = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sales")
        total_sales = self.cursor.fetchone()[0]

        print(f"\n{'=' * 50}")
        print(f"📊 RÉSUMÉ ENRICHISSEMENT COMMUNES")
        print(f"{'=' * 50}")
        print(f"  Communes en base: {total_communes:,}")
        print(f"  Nouvelles: {total_inserted:,}")
        print(f"  Mises à jour: {total_updated:,}")
        print(f"  Ventes rattachées: {total_linked:,}/{total_sales:,}")
        print(f"  Ventes liées cette fois: {linked:,}")

        # Top communes par population
        self.cursor.execute("""
            SELECT nom_commune, departement, population, latitude, longitude
            FROM communes
            WHERE population IS NOT NULL
            ORDER BY population DESC
            LIMIT 10
        """)
        top = self.cursor.fetchall()
        if top:
            print(f"\n  Top 10 communes par population:")
            for nom, dept, pop, lat, lon in top:
                coords = f"({lat:.4f}, {lon:.4f})" if lat else "(pas de coords)"
                print(f"    {nom} ({dept}): {pop:,} hab {coords}")

        print(f"{'=' * 50}")


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("\n🏘️ ENRICHISSEMENT DONNÉES COMMUNES (INSEE)")
    print("=" * 50)

    fetcher = INSEEDataFetcher()

    try:
        fetcher.update_communes_in_db()
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        logger.error(f"Erreur: {e}", exc_info=True)
    finally:
        fetcher.close()