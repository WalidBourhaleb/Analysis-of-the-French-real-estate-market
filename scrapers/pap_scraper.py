"""
=============================================================================
PAP SCRAPER — Scraping d'annonces immobilières depuis PAP.fr
=============================================================================
Scraping respectueux:
- Maximum 30 annonces/jour
- Délai 3-7 secondes entre chaque requête
- User-Agent réaliste
- Respect du robots.txt

Utilisation:
    python scrapers/pap_scraper.py                    # Mode test (5 annonces)
    python scrapers/pap_scraper.py --mode full         # Mode complet (30 annonces)
=============================================================================
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import logging
import time
import random
import os
import sys
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import SCRAPING_CONFIG, RAW_DATA_DIR

logger = logging.getLogger(__name__)


class PAPScraper:
    """
    Scraper pour PAP.fr (Particulier à Particulier).
    Collecte les annonces de vente immobilière.
    """

    def __init__(self):
        """Initialise le scraper PAP."""
        self.base_url = "https://www.pap.fr"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPING_CONFIG["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.pap.fr/",
        })

        self.delay_min = SCRAPING_CONFIG["delay_min"]
        self.delay_max = SCRAPING_CONFIG["delay_max"]
        self.max_per_day = SCRAPING_CONFIG["max_listings_per_day"]
        self.total_scraped = 0

        logger.info("PAPScraper initialisé")

    def _wait(self):
        """Pause aléatoire entre les requêtes (respectueux)."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    def _get_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Récupère et parse une page HTML.
        Gère les erreurs et le rate limiting.
        """
        try:
            self._wait()
            response = self.session.get(url, timeout=15)

            if response.status_code == 200:
                return BeautifulSoup(response.content, "html.parser")
            elif response.status_code == 403:
                logger.warning("⚠️ 403 Forbidden - PAP bloque les requêtes")
                logger.warning("   Conseil: attendez quelques heures et réessayez")
                return None
            elif response.status_code == 429:
                logger.warning("⚠️ 429 Too Many Requests - Rate limit atteint")
                logger.warning("   Attente 60 secondes...")
                time.sleep(60)
                return None
            else:
                logger.warning(f"⚠️ HTTP {response.status_code} pour {url}")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Timeout pour {url}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Erreur réseau: {e}")
            return None

    def _parse_listing_card(self, card) -> Optional[dict]:
        """
        Parse une carte d'annonce depuis la page de résultats.
        Extrait: titre, prix, surface, localisation, URL.
        """
        try:
            listing = {
                "source": "PAP",
                "date_scraped": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # URL de l'annonce
            link = card.find("a", href=True)
            if link:
                href = link.get("href", "")
                if href.startswith("/"):
                    listing["url"] = f"{self.base_url}{href}"
                elif href.startswith("http"):
                    listing["url"] = href
                else:
                    listing["url"] = f"{self.base_url}/{href}"

            # Titre
            title_tag = card.find(["h2", "h3", "a"], class_=lambda x: x and "title" in str(x).lower()) or card.find(["h2", "h3"])
            if title_tag:
                listing["titre"] = title_tag.get_text(strip=True)

            # Prix
            price_tag = card.find(class_=lambda x: x and "price" in str(x).lower()) or card.find(class_=lambda x: x and "prix" in str(x).lower())
            if price_tag:
                price_text = price_tag.get_text(strip=True)
                price_clean = "".join(c for c in price_text if c.isdigit())
                if price_clean:
                    listing["prix_affiche"] = int(price_clean)

            # Surface et pièces (souvent dans les tags de description)
            details_tags = card.find_all(class_=lambda x: x and ("detail" in str(x).lower() or "tag" in str(x).lower() or "item" in str(x).lower()))
            for tag in details_tags:
                text = tag.get_text(strip=True).lower()
                if "m²" in text or "m2" in text:
                    surface_clean = "".join(c for c in text.split("m")[0] if c.isdigit() or c == ".")
                    if surface_clean:
                        listing["surface_habitable"] = float(surface_clean)
                elif "pièce" in text or "piece" in text:
                    pieces_clean = "".join(c for c in text if c.isdigit())
                    if pieces_clean:
                        listing["nb_pieces"] = int(pieces_clean)

            # Localisation
            location_tag = card.find(class_=lambda x: x and ("location" in str(x).lower() or "city" in str(x).lower() or "lieu" in str(x).lower()))
            if location_tag:
                listing["localisation"] = location_tag.get_text(strip=True)

            # Type de bien (dans le titre ou les tags)
            titre = listing.get("titre", "").lower()
            if "appartement" in titre:
                listing["type_bien"] = "Appartement"
            elif "maison" in titre:
                listing["type_bien"] = "Maison"
            elif "terrain" in titre:
                listing["type_bien"] = "Terrain"
            elif "studio" in titre:
                listing["type_bien"] = "Appartement"

            # Vérifier qu'on a au minimum un prix ou un titre
            if "prix_affiche" in listing or "titre" in listing:
                return listing

            return None

        except Exception as e:
            logger.debug(f"Erreur parsing carte: {e}")
            return None

    def _parse_listing_detail(self, url: str) -> Optional[dict]:
        """
        Visite la page détaillée d'une annonce pour extraire plus d'infos.
        """
        soup = self._get_page(url)
        if not soup:
            return None

        details = {}

        try:
            # Description complète
            desc_tag = soup.find(class_=lambda x: x and "description" in str(x).lower()) or soup.find("div", {"itemprop": "description"})
            if desc_tag:
                details["description"] = desc_tag.get_text(strip=True)[:2000]

            # DPE
            dpe_tag = soup.find(class_=lambda x: x and "dpe" in str(x).lower())
            if dpe_tag:
                dpe_text = dpe_tag.get_text(strip=True).upper()
                for letter in "ABCDEFG":
                    if letter in dpe_text:
                        details["dpe_classe"] = letter
                        break

            # Photos (nombre)
            photos = soup.find_all("img", class_=lambda x: x and "photo" in str(x).lower()) or soup.find_all("img", {"data-src": True})
            details["nb_photos"] = len(photos)

            # Caractéristiques (parking, balcon, etc.)
            text_full = soup.get_text().lower()
            details["parking"] = "parking" in text_full or "garage" in text_full
            details["balcon"] = "balcon" in text_full
            details["terrasse"] = "terrasse" in text_full
            details["cave"] = "cave" in text_full
            details["ascenseur"] = "ascenseur" in text_full

        except Exception as e:
            logger.debug(f"Erreur parsing détail: {e}")

        return details

    def scrape_search(
        self,
        city: str = "paris-75",
        property_type: str = "appartement",
        max_listings: int = 10,
        get_details: bool = False,
    ) -> pd.DataFrame:
        """
        Scrape les annonces de vente sur PAP.fr.

        Args:
            city:          Ville (ex: "paris-75", "lyon-69", "marseille-13")
            property_type: Type de bien ("appartement", "maison")
            max_listings:  Nombre max d'annonces à scraper
            get_details:   Si True, visite chaque annonce pour plus de détails

        Returns:
            DataFrame avec les annonces
        """
        # Respecter la limite journalière
        if self.total_scraped >= self.max_per_day:
            print(f"  ⚠️ Limite journalière atteinte ({self.max_per_day} annonces)")
            return pd.DataFrame()

        # Limiter au maximum journalier
        max_listings = min(max_listings, self.max_per_day - self.total_scraped)

        # Construire l'URL de recherche
        search_url = f"{self.base_url}/annonce/vente-{property_type}-{city}"
        print(f"  🔍 Recherche: {search_url}")

        # Récupérer la page de résultats
        soup = self._get_page(search_url)
        if not soup:
            print(f"  ❌ Impossible d'accéder à la page")
            return pd.DataFrame()

        # Chercher les cartes d'annonces
        # PAP utilise différentes classes CSS selon les versions
        cards = []
        for selector in [
            {"class_": lambda x: x and "search-list-item" in str(x)},
            {"class_": lambda x: x and "item-listing" in str(x)},
            {"class_": lambda x: x and "annonce" in str(x).lower()},
            {"class_": lambda x: x and "ad-card" in str(x).lower()},
        ]:
            cards = soup.find_all("div", **selector)
            if cards:
                break

        # Si aucun sélecteur ne marche, essayer de trouver des liens d'annonces
        if not cards:
            # Chercher les liens qui contiennent "annonce" dans l'URL
            links = soup.find_all("a", href=lambda x: x and "/annonces/" in str(x))
            if links:
                # Remonter au parent pour avoir la carte complète
                cards = [link.parent for link in links[:max_listings]]

        if not cards:
            print(f"  ⚠️ Aucune annonce trouvée (structure HTML peut avoir changé)")
            print(f"     Essayez de visiter {search_url} dans votre navigateur")

            # Sauvegarder le HTML pour debug
            debug_file = RAW_DATA_DIR / f"pap_debug_{city}.html"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(str(soup.prettify()[:50000]))
            print(f"     HTML sauvegardé pour debug: {debug_file.name}")

            return pd.DataFrame()

        print(f"  📄 {len(cards)} cartes d'annonces trouvées")

        # Parser chaque carte
        listings = []
        for i, card in enumerate(cards[:max_listings]):
            listing = self._parse_listing_card(card)

            if listing:
                # Optionnel: visiter la page détaillée
                if get_details and "url" in listing:
                    print(f"    [{i+1}/{min(len(cards), max_listings)}] Visite détail: {listing.get('titre', 'N/A')[:50]}...")
                    details = self._parse_listing_detail(listing["url"])
                    if details:
                        listing.update(details)

                listing["city_search"] = city
                listing["property_type_search"] = property_type
                listings.append(listing)
                self.total_scraped += 1

        print(f"  ✅ {len(listings)} annonces extraites")

        if not listings:
            return pd.DataFrame()

        return pd.DataFrame(listings)

    def scrape_multiple_cities(
        self,
        cities: Optional[List[dict]] = None,
        max_per_city: int = 5,
        get_details: bool = False,
    ) -> pd.DataFrame:
        """
        Scrape plusieurs villes.

        Args:
            cities: Liste de dicts {"city": "paris-75", "type": "appartement"}
            max_per_city: Max annonces par ville
            get_details: Visiter les pages détaillées
        """
        if cities is None:
            cities = [
                {"city": "paris-75", "type": "appartement"},
                {"city": "paris-75", "type": "maison"},
                {"city": "lyon-69", "type": "appartement"},
                {"city": "marseille-13", "type": "appartement"},
                {"city": "bordeaux-33", "type": "appartement"},
                {"city": "lille-59", "type": "appartement"},
            ]

        all_dfs = []

        for config in cities:
            city = config["city"]
            prop_type = config["type"]

            print(f"\n📍 Scraping {city} — {prop_type}...")

            df = self.scrape_search(
                city=city,
                property_type=prop_type,
                max_listings=max_per_city,
                get_details=get_details,
            )

            if not df.empty:
                all_dfs.append(df)

            # Vérifier limite journalière
            if self.total_scraped >= self.max_per_day:
                print(f"\n⚠️ Limite journalière ({self.max_per_day}) atteinte !")
                break

            # Pause entre les villes
            time.sleep(random.uniform(5, 10))

        if not all_dfs:
            print("\n❌ Aucune annonce récupérée")
            return pd.DataFrame()

        df_combined = pd.concat(all_dfs, ignore_index=True)

        # Sauvegarder
        filename = f"pap_listings_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        filepath = RAW_DATA_DIR / filename
        df_combined.to_csv(filepath, index=False, encoding="utf-8-sig")

        # Résumé
        print(f"\n{'=' * 50}")
        print(f"📊 RÉSUMÉ SCRAPING PAP")
        print(f"{'=' * 50}")
        print(f"  Total annonces: {len(df_combined)}")
        print(f"  Fichier: {filepath.name}")

        if "type_bien" in df_combined.columns:
            print(f"\n  Par type:")
            for t, c in df_combined["type_bien"].value_counts().items():
                print(f"    {t}: {c}")

        if "prix_affiche" in df_combined.columns:
            prix = df_combined["prix_affiche"].dropna()
            if len(prix) > 0:
                print(f"\n  Prix:")
                print(f"    Moyen: {prix.mean():,.0f} €")
                print(f"    Min: {prix.min():,.0f} €")
                print(f"    Max: {prix.max():,.0f} €")

        print(f"{'=' * 50}")

        return df_combined


# =============================================================================
# EXÉCUTION DIRECTE
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PAP.fr Scraper")
    parser.add_argument(
        "--mode",
        choices=["test", "full"],
        default="test",
        help="test = 1 ville/5 annonces, full = 6 villes/5 annonces chacune"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Visiter chaque annonce pour plus de détails"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    scraper = PAPScraper()

    if args.mode == "test":
        print("\n🧪 MODE TEST — Paris, 5 annonces max")
        print("=" * 50)

        df = scraper.scrape_search(
            city="paris-75",
            property_type="appartement",
            max_listings=5,
            get_details=args.details,
        )

        if not df.empty:
            print(f"\n✅ {len(df)} annonces récupérées")
            print(f"\nColonnes:")
            for col in sorted(df.columns):
                print(f"  - {col}")
            print(f"\nAperçu:")
            print(df.to_string(index=False, max_cols=6))

            test_file = RAW_DATA_DIR / "pap_test.csv"
            df.to_csv(test_file, index=False, encoding="utf-8-sig")
            print(f"\n💾 Sauvegardé: {test_file}")
        else:
            print("\n⚠️ Aucune annonce récupérée")
            print("   PAP.fr peut bloquer les requêtes automatiques")
            print("   Réessayez plus tard ou vérifiez manuellement le site")

    elif args.mode == "full":
        print("\n🚀 MODE COMPLET — 6 villes, 5 annonces chacune")
        print("=" * 50)

        df = scraper.scrape_multiple_cities(
            max_per_city=5,
            get_details=args.details,
        )

        if not df.empty:
            print(f"\n🎉 Scraping terminé ! {len(df)} annonces")
        else:
            print("\n⚠️ Scraping échoué — PAP bloque probablement les requêtes")

    print(f"\n📈 Stats: {scraper.total_scraped} annonces scrapées au total")