"""
Test de connexion à la base de données PostgreSQL + PostGIS
Exécuter: python tests/test_db_connection.py
"""

import sys
import os

# Ajouter le dossier racine au PATH Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE


def test_connection():
    """Teste la connexion à PostgreSQL"""
    import psycopg2

    print("\n🔌 Test de connexion à PostgreSQL...")
    print(f"   Host: {DATABASE['host']}:{DATABASE['port']}")
    print(f"   Database: {DATABASE['database']}")
    print(f"   User: {DATABASE['user']}")

    try:
        conn = psycopg2.connect(
            host=DATABASE["host"],
            port=DATABASE["port"],
            dbname=DATABASE["database"],
            user=DATABASE["user"],
            password=DATABASE["password"],
        )
        cursor = conn.cursor()

        # 1. Version PostgreSQL
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"\n✅ PostgreSQL connecté !")
        print(f"   Version: {version[:60]}...")

        # 2. Version PostGIS
        cursor.execute("SELECT PostGIS_version();")
        postgis = cursor.fetchone()[0]
        print(f"✅ PostGIS activé !")
        print(f"   Version: {postgis}")

        # 3. Lister les tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        print(f"\n📋 Tables trouvées ({len(tables)}) :")
        for table in tables:
            print(f"   ✅ {table[0]}")

        # 4. Lister les vues matérialisées
        cursor.execute("""
            SELECT matviewname 
            FROM pg_matviews 
            WHERE schemaname = 'public'
            ORDER BY matviewname;
        """)
        views = cursor.fetchall()
        print(f"\n📊 Vues matérialisées ({len(views)}) :")
        for view in views:
            print(f"   ✅ {view[0]}")

        # 5. Vérifier les données initiales (communes)
        cursor.execute("SELECT COUNT(*) FROM communes;")
        count = cursor.fetchone()[0]
        print(f"\n🏘️  Communes insérées : {count}")

        if count > 0:
            cursor.execute("SELECT nom_commune, departement FROM communes ORDER BY nom_commune;")
            communes = cursor.fetchall()
            for commune in communes:
                print(f"   📍 {commune[0]} (dept {commune[1]})")

        # Fermer la connexion
        cursor.close()
        conn.close()

        print("\n" + "=" * 50)
        print("🎉 TOUS LES TESTS PASSÉS AVEC SUCCÈS !")
        print("=" * 50)
        return True

    except psycopg2.OperationalError as e:
        print(f"\n❌ ERREUR DE CONNEXION : {e}")
        print("\n💡 Solutions possibles :")
        print("   1. Vérifiez que PostgreSQL est démarré")
        print("   2. Vérifiez le mot de passe dans .env")
        print("   3. Vérifiez que la base immobilier_db existe")
        return False

    except Exception as e:
        print(f"\n❌ ERREUR : {e}")
        return False


if __name__ == "__main__":
    test_connection()