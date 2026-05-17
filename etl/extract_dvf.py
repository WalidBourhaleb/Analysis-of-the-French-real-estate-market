"""
=============================================================================
EXTRACT DVF — Charger les données DVF dans PostgreSQL
=============================================================================
Utilisation:
    python etl/extract_dvf.py              # Charge toutes les données
    python etl/extract_dvf.py --test       # Mode test (1000 lignes)
=============================================================================
"""

import pandas as pd
import psycopg2
import psycopg2.extras
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE, RAW_DATA_DIR

logger = logging.getLogger(__name__)


class DVFLoader:
    """Charge les données DVF (CSV) dans PostgreSQL."""

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
        self.inserted = 0
        self.skipped = 0
        self.errors = 0
        logger.info("DVFLoader connecté à PostgreSQL")

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Connexion fermée")

    def _standardize_columns(self, df):
        """Renomme les colonnes DVF avec des noms standards."""
        rename_map = {
            "Date mutation": "date_mutation",
            "Nature mutation": "nature_mutation",
            "Valeur fonciere": "valeur_fonciere",
            "No voie": "adresse_numero",
            "B/T/Q": "adresse_suffixe",
            "Type de voie": "type_voie",
            "Code voie": "code_voie",
            "Voie": "adresse_nom_voie",
            "Code postal": "code_postal",
            "Commune": "commune_nom",
            "Code departement": "code_departement",
            "Code commune": "code_commune",
            "Section": "section",
            "No plan": "no_plan",
            "Nombre de lots": "nombre_lots",
            "Code type local": "code_type_local",
            "Type local": "type_local",
            "Surface reelle bati": "surface_reelle_bati",
            "Nombre pieces principales": "nb_pieces",
            "Surface terrain": "surface_terrain",
            "ville_recherche": "ville_recherche",
            "dept_recherche": "dept_recherche",
        }

        # Renommer les colonnes qui existent
        columns_to_rename = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=columns_to_rename)

        print(f"  ✅ {len(columns_to_rename)} colonnes renommées")
        return df

    def _clean_data(self, df):
        """Nettoie les données avant insertion."""
        print(f"  🧹 Nettoyage des données...")
        initial_count = len(df)

        # 1. Convertir date_mutation
        df["date_mutation"] = pd.to_datetime(
            df["date_mutation"], errors="coerce", dayfirst=True
        )
        before = len(df)
        df = df.dropna(subset=["date_mutation"])
        print(f"    Dates invalides supprimées: {before - len(df)}")

        # 2. Convertir valeur_fonciere (virgules → points)
        df["valeur_fonciere"] = (
            df["valeur_fonciere"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace(" ", "", regex=False)
            .str.strip()
        )
        df["valeur_fonciere"] = pd.to_numeric(df["valeur_fonciere"], errors="coerce")
        before = len(df)
        df = df.dropna(subset=["valeur_fonciere"])
        df = df[df["valeur_fonciere"] > 0]
        print(f"    Prix invalides supprimés: {before - len(df)}")

        # 3. Convertir surfaces
        df["surface_reelle_bati"] = pd.to_numeric(
            df["surface_reelle_bati"], errors="coerce"
        )
        df["surface_terrain"] = pd.to_numeric(
            df["surface_terrain"], errors="coerce"
        )

        # 4. Convertir nb_pieces et nombre_lots
        df["nb_pieces"] = pd.to_numeric(df["nb_pieces"], errors="coerce")
        df["nombre_lots"] = pd.to_numeric(df["nombre_lots"], errors="coerce")

        # 5. Nettoyer code_commune
        df["code_commune"] = df["code_commune"].astype(str).str.strip()
        # Enlever le .0 si présent (ex: "75056.0" -> "75056")
        df["code_commune"] = df["code_commune"].str.replace(r"\.0$", "", regex=True)
        df["code_commune"] = df["code_commune"].str.zfill(5)

        # 6. Nettoyer code_postal
        df["code_postal"] = df["code_postal"].astype(str).str.strip()
        df["code_postal"] = df["code_postal"].str.replace(r"\.0$", "", regex=True)
        df["code_postal"] = df["code_postal"].str.zfill(5)
        df.loc[df["code_postal"].isin(["nan", "00nan", "None"]), "code_postal"] = None

        # 7. Nettoyer code_departement
        df["code_departement"] = df["code_departement"].astype(str).str.strip()
        df["code_departement"] = df["code_departement"].str.replace(r"\.0$", "", regex=True)

        # 8. Créer dvf_id unique
        df = df.reset_index(drop=True)
        df["dvf_id"] = (
            df["date_mutation"].dt.strftime("%Y%m%d")
            + "_"
            + df["code_commune"].astype(str)
            + "_"
            + df["valeur_fonciere"].astype(int).astype(str)
            + "_"
            + df.index.astype(str)
        )

        cleaned_count = len(df)
        removed = initial_count - cleaned_count
        print(f"  ✅ Nettoyage terminé: {cleaned_count:,} lignes conservées ({removed:,} supprimées)")

        return df

    def _link_communes(self, df):
        """Rattache les ventes aux communes dans la DB."""
        print(f"  🔗 Rattachement aux communes...")

        self.cursor.execute("SELECT id, code_commune FROM communes")
        communes_db = {row[1]: row[0] for row in self.cursor.fetchall()}

        df["commune_id"] = df["code_commune"].map(communes_db)

        linked = df["commune_id"].notna().sum()
        total = len(df)
        print(f"  ✅ {linked:,}/{total:,} ventes rattachées à une commune connue")

        return df

    def _insert_batch(self, df, batch_size=500):
        """Insère les données dans la table sales par batch."""
        print(f"  💾 Insertion dans PostgreSQL ({len(df):,} lignes)...")

        insert_sql = """
            INSERT INTO sales (
                dvf_id, date_mutation, nature_mutation, valeur_fonciere,
                type_local, nb_pieces, surface_reelle_bati, surface_terrain,
                nombre_lots, code_commune, commune_id,
                adresse_numero, adresse_suffixe, adresse_nom_voie,
                code_postal, source
            ) VALUES (
                %(dvf_id)s, %(date_mutation)s, %(nature_mutation)s, %(valeur_fonciere)s,
                %(type_local)s, %(nb_pieces)s, %(surface_reelle_bati)s, %(surface_terrain)s,
                %(nombre_lots)s, %(code_commune)s, %(commune_id)s,
                %(adresse_numero)s, %(adresse_suffixe)s, %(adresse_nom_voie)s,
                %(code_postal)s, 'DVF'
            )
            ON CONFLICT (dvf_id) DO NOTHING
        """

        total_batches = (len(df) // batch_size) + 1

        for i in range(0, len(df), batch_size):
            batch = df.iloc[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            records = []
            for _, row in batch.iterrows():
                try:
                    record = {
                        "dvf_id": str(row.get("dvf_id", ""))[:50],
                        "date_mutation": row.get("date_mutation"),
                        "nature_mutation": str(row.get("nature_mutation", ""))[:50] if pd.notna(row.get("nature_mutation")) else None,
                        "valeur_fonciere": float(row["valeur_fonciere"]) if pd.notna(row.get("valeur_fonciere")) else None,
                        "type_local": str(row.get("type_local", ""))[:50] if pd.notna(row.get("type_local")) else None,
                        "nb_pieces": int(row["nb_pieces"]) if pd.notna(row.get("nb_pieces")) else None,
                        "surface_reelle_bati": float(row["surface_reelle_bati"]) if pd.notna(row.get("surface_reelle_bati")) else None,
                        "surface_terrain": float(row["surface_terrain"]) if pd.notna(row.get("surface_terrain")) else None,
                        "nombre_lots": int(row["nombre_lots"]) if pd.notna(row.get("nombre_lots")) else None,
                        "code_commune": str(row.get("code_commune", ""))[:5] if pd.notna(row.get("code_commune")) else None,
                        "commune_id": int(row["commune_id"]) if pd.notna(row.get("commune_id")) else None,
                        "adresse_numero": str(row.get("adresse_numero", ""))[:10] if pd.notna(row.get("adresse_numero")) else None,
                        "adresse_suffixe": str(row.get("adresse_suffixe", ""))[:10] if pd.notna(row.get("adresse_suffixe")) else None,
                        "adresse_nom_voie": str(row.get("adresse_nom_voie", ""))[:500] if pd.notna(row.get("adresse_nom_voie")) else None,
                        "code_postal": str(row.get("code_postal", ""))[:5] if pd.notna(row.get("code_postal")) else None,
                    }
                    records.append(record)
                except Exception as e:
                    self.errors += 1
                    continue

            try:
                psycopg2.extras.execute_batch(self.cursor, insert_sql, records, page_size=100)
                self.conn.commit()
                self.inserted += len(records)

                if batch_num % 10 == 0 or batch_num == total_batches:
                    pct = (batch_num / total_batches) * 100
                    print(f"    [{pct:5.1f}%] Batch {batch_num}/{total_batches}: {self.inserted:,} insérées")

            except Exception as e:
                self.conn.rollback()
                logger.error(f"    ❌ Erreur batch {batch_num}: {e}")
                self.errors += len(records)

    def load_csv_to_db(self, filepath=None, max_rows=None):
        """Pipeline complet: CSV → Nettoyage → PostgreSQL"""

        # 1. Trouver le fichier
        if filepath is None:
            csv_files = sorted(RAW_DATA_DIR.glob("dvf_combined_*.csv"), reverse=True)
            if not csv_files:
                csv_files = sorted(RAW_DATA_DIR.glob("dvf_*.csv"), reverse=True)
            if not csv_files:
                print("❌ Aucun fichier DVF trouvé dans data/raw/")
                return
            filepath = csv_files[0]

        print(f"\n{'=' * 60}")
        print(f"📥 CHARGEMENT DVF → PostgreSQL")
        print(f"{'=' * 60}")
        print(f"  Fichier: {filepath.name}")
        size_mb = filepath.stat().st_size / (1024 * 1024)
        print(f"  Taille: {size_mb:.1f} MB")

        # 2. Lire le CSV
        print(f"\n  📖 Lecture du fichier CSV...")
        if max_rows:
            df = pd.read_csv(filepath, low_memory=False, nrows=max_rows)
        else:
            df = pd.read_csv(filepath, low_memory=False)
        print(f"  ✅ {len(df):,} lignes lues, {len(df.columns)} colonnes")

        # 3. Standardiser les colonnes
        print(f"\n  🔄 Standardisation des colonnes...")
        df = self._standardize_columns(df)

        # 4. Nettoyer
        df = self._clean_data(df)

        if df.empty:
            print("❌ Aucune donnée valide après nettoyage")
            return

        # 5. Rattacher aux communes
        df = self._link_communes(df)

        # 6. Insérer
        self._insert_batch(df)

        # 7. Rafraîchir vues
        print(f"\n  🔄 Rafraîchissement des vues matérialisées...")
        for view in ["vw_price_stats", "vw_monthly_trends"]:
            try:
                self.cursor.execute(f"REFRESH MATERIALIZED VIEW {view}")
                self.conn.commit()
                print(f"  ✅ {view} rafraîchie")
            except Exception as e:
                self.conn.rollback()
                logger.warning(f"  ⚠️ Erreur refresh {view}: {e}")

        # 8. Vérification
        self.cursor.execute("SELECT COUNT(*) FROM sales")
        total_in_db = self.cursor.fetchone()[0]

        self.cursor.execute("""
            SELECT type_local, COUNT(*) as nb
            FROM sales WHERE type_local IS NOT NULL
            GROUP BY type_local ORDER BY nb DESC
        """)
        types = self.cursor.fetchall()

        self.cursor.execute("SELECT MIN(date_mutation), MAX(date_mutation) FROM sales")
        date_range = self.cursor.fetchone()

        print(f"\n{'=' * 60}")
        print(f"📊 RÉSUMÉ DU CHARGEMENT")
        print(f"{'=' * 60}")
        print(f"  ✅ Insérées: {self.inserted:,}")
        print(f"  ❌ Erreurs: {self.errors:,}")
        print(f"  📊 Total en base: {total_in_db:,}")

        if date_range[0]:
            print(f"  📅 Période: {date_range[0]} -> {date_range[1]}")

        if types:
            print(f"\n  Par type de bien:")
            for type_name, count in types:
                print(f"    {type_name}: {count:,}")

        print(f"{'=' * 60}")


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Charge DVF dans PostgreSQL")
    parser.add_argument("--test", action="store_true", help="Mode test: 1000 lignes")
    parser.add_argument("--file", type=str, default=None, help="Fichier CSV")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    loader = DVFLoader()

    try:
        filepath = Path(args.file) if args.file else None
        max_rows = 1000 if args.test else None

        if args.test:
            print("\n🧪 MODE TEST — 1000 lignes maximum")
        else:
            print("\n🚀 MODE COMPLET — Chargement de toutes les données")

        loader.load_csv_to_db(filepath=filepath, max_rows=max_rows)

    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        logger.error(f"Erreur: {e}", exc_info=True)

    finally:
        loader.close()