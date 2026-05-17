"""
=============================================================================
DVF CLIENT — Récupération des données DVF (Demandes de Valeurs Foncières)
=============================================================================
Source: data.gouv.fr (Open Data officiel)

Ce module récupère les transactions immobilières officielles en France.
- 5M+ transactions disponibles (2018-2024)
- 100% gratuit et légal

Utilisation:
    from scrapers.dvf_client import DVFClient

    client = DVFClient()
    df = client.fetch_sales(departement="75", date_debut="2023-01-01")
=============================================================================
"""

import requests
import pandas as pd
import logging
import time
import os
import sys
import io
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DVF_CONFIG, RAW_DATA_DIR

logger = logging.getLogger(__name__)


# URLs des fichiers DVF annuels sur data.gouv.fr
DVF_ANNUAL_URLS = {
    "2024": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20241010-093302/valeursfoncieres-2024.txt",
    "2023": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20231010-093302/valeursfoncieres-2023.txt",
    "2022": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20221010-093302/valeursfoncieres-2022.txt",
}


class DVFClient:
    """
    Client pour récupérer les données DVF (Demandes de Valeurs Foncières).
    Télécharge les fichiers annuels depuis data.gouv.fr et filtre par département/date.
    """

    def __init__(self):
        """Initialise le client DVF."""
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9",
        })

        self.total_requests = 0
        self.total_records = 0
        self._cache = {}  # Cache pour éviter de re-télécharger

        logger.info("DVFClient initialisé")

    def _download_year(self, year: str) -> pd.DataFrame:
        """
        Télécharge le fichier DVF d'une année complète.
        Utilise un cache pour ne pas re-télécharger.
        """
        # Vérifier le cache
        if year in self._cache:
            logger.info(f"  Cache hit pour {year}")
            return self._cache[year]

        # Vérifier si fichier déjà téléchargé localement
        local_file = RAW_DATA_DIR / f"dvf_france_{year}.csv"
        if local_file.exists():
            print(f"  📂 Fichier local trouvé: {local_file.name}")
            df = pd.read_csv(local_file, low_memory=False)
            self._cache[year] = df
            return df

        # Télécharger depuis data.gouv.fr
        url = DVF_ANNUAL_URLS.get(year)
        if not url:
            logger.warning(f"  ⚠️ Pas d'URL connue pour {year}")
            return pd.DataFrame()

        try:
            print(f"  📥 Téléchargement DVF {year} (peut prendre 1-2 min)...")
            response = self.session.get(url, timeout=300)
            self.total_requests += 1

            if response.status_code != 200:
                logger.warning(f"  ⚠️ HTTP {response.status_code} pour {year}")
                return pd.DataFrame()

            # Lire le fichier TXT (séparateur |)
            print(f"  📖 Lecture du fichier {year}...")
            content = response.content.decode("utf-8", errors="replace")
            df = pd.read_csv(io.StringIO(content), sep="|", low_memory=False)

            print(f"  ✅ {year}: {len(df):,} lignes chargées")

            # Sauvegarder localement (pour ne pas re-télécharger)
            df.to_csv(local_file, index=False, encoding="utf-8-sig")
            print(f"  💾 Sauvegardé localement: {local_file.name}")

            # Mettre en cache
            self._cache[year] = df

            return df

        except Exception as e:
            logger.error(f"  ❌ Erreur téléchargement {year}: {e}")
            return pd.DataFrame()

    def fetch_sales(
        self,
        departement: Optional[str] = None,
        commune: Optional[str] = None,
        date_debut: Optional[str] = None,
        date_fin: Optional[str] = None,
        type_local: Optional[List[str]] = None,
        max_records: int = 10000,
    ) -> pd.DataFrame:
        """
        Récupère les ventes immobilières depuis les fichiers DVF.

        Args:
            departement: Code département (ex: "75" pour Paris)
            commune:     Code commune INSEE
            date_debut:  Date début "YYYY-MM-DD"
            date_fin:    Date fin "YYYY-MM-DD"
            type_local:  Types de bien (ex: ["Appartement", "Maison"])
            max_records: Nombre max de records

        Returns:
            DataFrame avec les transactions
        """
        logger.info(
            f"Fetch DVF: dept={departement}, commune={commune}, "
            f"dates={date_debut} -> {date_fin}, types={type_local}"
        )

        # Déterminer quelles années télécharger
        years_to_fetch = []
        if date_debut and date_fin:
            start_year = int(date_debut[:4])
            end_year = int(date_fin[:4])
            for y in range(start_year, end_year + 1):
                if str(y) in DVF_ANNUAL_URLS:
                    years_to_fetch.append(str(y))
        else:
            years_to_fetch = list(DVF_ANNUAL_URLS.keys())

        # Télécharger chaque année
        all_dfs = []
        for year in years_to_fetch:
            df = self._download_year(year)
            if not df.empty:
                all_dfs.append(df)
            time.sleep(1)

        if not all_dfs:
            logger.warning("Aucune donnée récupérée !")
            return pd.DataFrame()

        # Combiner toutes les années
        df = pd.concat(all_dfs, ignore_index=True)
        print(f"\n  📊 Total brut: {len(df):,} lignes")

        # Filtrer par département
        if departement:
            dept_col = None
            for col in ["code_departement", "Code departement"]:
                if col in df.columns:
                    dept_col = col
                    break

            if dept_col:
                df[dept_col] = df[dept_col].astype(str).str.strip()
                df = df[df[dept_col] == departement]
                print(f"  🔍 Après filtre dept {departement}: {len(df):,} lignes")

        # Filtrer par commune
        if commune:
            comm_col = None
            for col in ["code_commune", "Code commune"]:
                if col in df.columns:
                    comm_col = col
                    break

            if comm_col:
                df[comm_col] = df[comm_col].astype(str).str.strip()
                df = df[df[comm_col] == commune]

        # Filtrer par date
        date_col = None
        for col in ["date_mutation", "Date mutation"]:
            if col in df.columns:
                date_col = col
                break

        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
            if date_debut:
                df = df[df[date_col] >= date_debut]
            if date_fin:
                df = df[df[date_col] <= date_fin]
            print(f"  🔍 Après filtre dates: {len(df):,} lignes")

        # Filtrer par type de bien
        if type_local:
            type_col = None
            for col in ["type_local", "Type local"]:
                if col in df.columns:
                    type_col = col
                    break

            if type_col:
                df = df[df[type_col].isin(type_local)]
                print(f"  🔍 Après filtre types {type_local}: {len(df):,} lignes")

        # Limiter le nombre de records
        if len(df) > max_records:
            df = df.head(max_records)
            print(f"  ✂️ Limité à {max_records:,} records")

        self.total_records += len(df)
        logger.info(f"✅ Résultat final: {len(df):,} transactions")

        return df

    def fetch_by_department(
        self,
        departement: str,
        date_debut: str = None,
        date_fin: str = None,
        max_records: int = 10000,
    ) -> pd.DataFrame:
        """Récupère toutes les ventes d'un département."""
        logger.info(f"📍 Fetch département {departement}...")

        if not date_debut:
            date_debut = DVF_CONFIG["default_start_date"]
        if not date_fin:
            date_fin = DVF_CONFIG["default_end_date"]

        return self.fetch_sales(
            departement=departement,
            date_debut=date_debut,
            date_fin=date_fin,
            type_local=DVF_CONFIG["default_types"],
            max_records=max_records,
        )

    def fetch_multiple_departments(
        self,
        departements: Optional[List[Tuple[str, str]]] = None,
        date_debut: str = None,
        date_fin: str = None,
        max_records_per_dept: int = 10000,
    ) -> pd.DataFrame:
        """Récupère les ventes de plusieurs départements."""
        if departements is None:
            departements = DVF_CONFIG["default_cities"]

        all_dfs = []

        for dept_code, city_name in departements:
            print(f"\n📍 Récupération: {city_name} (département {dept_code})...")

            df = self.fetch_by_department(
                departement=dept_code,
                date_debut=date_debut,
                date_fin=date_fin,
                max_records=max_records_per_dept,
            )

            if df.empty:
                print(f"  ⚠️ Pas de données pour {city_name}")
                continue

            df["ville_recherche"] = city_name
            df["dept_recherche"] = dept_code

            print(f"  ✅ {len(df):,} transactions pour {city_name}")
            all_dfs.append(df)

            # Sauvegarde par département
            filename = f"dvf_{dept_code}_{datetime.now().strftime('%Y%m%d')}.csv"
            filepath = RAW_DATA_DIR / filename
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
            print(f"  💾 Sauvegardé: {filepath.name}")

        if not all_dfs:
            print("\n❌ Aucune donnée récupérée !")
            return pd.DataFrame()

        df_combined = pd.concat(all_dfs, ignore_index=True)

        # Sauvegarde combinée
        combined_file = RAW_DATA_DIR / f"dvf_combined_{datetime.now().strftime('%Y%m%d')}.csv"
        df_combined.to_csv(combined_file, index=False, encoding="utf-8-sig")

        # Résumé
        print(f"\n{'=' * 50}")
        print(f"📊 RÉSUMÉ DE LA COLLECTE DVF")
        print(f"{'=' * 50}")
        print(f"  Total transactions: {len(df_combined):,}")
        print(f"  Départements: {len(all_dfs)}")
        print(f"  Requêtes: {self.total_requests}")
        print(f"  Fichier: {combined_file.name}")

        date_col = None
        for col in ["date_mutation", "Date mutation"]:
            if col in df_combined.columns:
                date_col = col
                break
        if date_col:
            dates = df_combined[date_col].dropna()
            if len(dates) > 0:
                print(f"  Période: {dates.min()} -> {dates.max()}")

        type_col = None
        for col in ["type_local", "Type local"]:
            if col in df_combined.columns:
                type_col = col
                break
        if type_col:
            print(f"\n  Par type de bien:")
            for name, count in df_combined[type_col].value_counts().items():
                print(f"    {name}: {count:,}")

        print(f"{'=' * 50}")

        return df_combined

    def fetch_recent(
        self,
        months: int = 6,
        departements: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Récupère les ventes récentes."""
        date_fin = datetime.now().strftime("%Y-%m-%d")
        date_debut = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        print(f"\n📅 Derniers {months} mois ({date_debut} -> {date_fin})")

        if departements:
            cities = [(d, f"Dept_{d}") for d in departements]
        else:
            cities = None

        return self.fetch_multiple_departments(
            departements=cities,
            date_debut=date_debut,
            date_fin=date_fin,
        )

    def get_stats(self) -> dict:
        """Retourne les statistiques du client."""
        return {
            "total_requests": self.total_requests,
            "total_records": self.total_records,
        }


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DVF Data Fetcher")
    parser.add_argument(
        "--mode",
        choices=["test", "full"],
        default="test",
        help="test = Paris 2023 / 100 records, full = 5 villes / 10000 chacune"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    client = DVFClient()

    if args.mode == "test":
        print("\n🧪 MODE TEST — Paris 2023, 100 records max")
        print("=" * 50)

        df = client.fetch_sales(
            departement="75",
            date_debut="2023-01-01",
            date_fin="2023-12-31",
            type_local=["Appartement", "Maison"],
            max_records=100,
        )

        if not df.empty:
            print(f"\n✅ Test réussi ! {len(df)} transactions récupérées")

            print(f"\nColonnes ({len(df.columns)}):")
            for col in sorted(df.columns):
                print(f"  - {col}")

            print(f"\nAperçu (5 premières lignes):")
            print(df.head().to_string(index=False, max_cols=8))

            test_file = RAW_DATA_DIR / "dvf_test.csv"
            df.to_csv(test_file, index=False, encoding="utf-8-sig")
            print(f"\n💾 Sauvegardé: {test_file}")
        else:
            print("\n❌ Aucune donnée récupérée !")

    elif args.mode == "full":
        print("\n🚀 MODE COMPLET — 5 villes, 10000 records max chacune")
        print("=" * 50)
        print("⏱️  Temps estimé: 5-15 minutes\n")

        df = client.fetch_multiple_departments(max_records_per_dept=10000)

        if not df.empty:
            print(f"\n🎉 Collecte terminée ! {len(df):,} transactions")
        else:
            print("\n❌ Aucune donnée récupérée !")

    stats = client.get_stats()
    print(f"\n📈 Stats: {stats['total_requests']} requêtes, {stats['total_records']:,} records")