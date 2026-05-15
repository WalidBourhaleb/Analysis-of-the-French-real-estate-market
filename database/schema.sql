-- =============================================================================
-- SCHÉMA BASE DE DONNÉES - ANALYSE MARCHÉ IMMOBILIER FRANÇAIS
-- =============================================================================
-- PostgreSQL 14+ avec extension PostGIS
-- Auteur: Walid Bourhaleb
-- Date: Janvier 2025
-- =============================================================================

-- Active l'extension PostGIS pour les données géospatiales
CREATE EXTENSION IF NOT EXISTS postgis;

-- =============================================================================
-- TABLE: communes (référentiel géographique)
-- =============================================================================
-- Contient toutes les communes françaises avec leurs données
CREATE TABLE IF NOT EXISTS communes (
    id SERIAL PRIMARY KEY,
    code_commune VARCHAR(5) UNIQUE NOT NULL,  -- Code INSEE (ex: '75056' pour Paris)
    nom_commune VARCHAR(100) NOT NULL,
    code_postal VARCHAR(5),
    departement VARCHAR(3),
    region VARCHAR(50),
    
    -- Données démographiques (INSEE)
    population INT,
    superficie_km2 DECIMAL(10,2),
    densite_pop DECIMAL(10,2),
    revenu_median DECIMAL(10,2),
    taux_chomage DECIMAL(5,2),
    
    -- Géolocalisation (centre-ville)
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    geometry GEOMETRY(Point, 4326),  -- PostGIS - SRID 4326 (WGS84)
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_communes_code ON communes(code_commune);
CREATE INDEX IF NOT EXISTS idx_communes_nom ON communes(nom_commune);
CREATE INDEX IF NOT EXISTS idx_communes_dept ON communes(departement);
CREATE INDEX IF NOT EXISTS idx_communes_geom ON communes USING GIST(geometry);

COMMENT ON TABLE communes IS 'Référentiel des communes françaises avec données démographiques INSEE';


-- =============================================================================
-- TABLE: quartiers (sous-divisions des communes)
-- =============================================================================
CREATE TABLE IF NOT EXISTS quartiers (
    id SERIAL PRIMARY KEY,
    commune_id INT REFERENCES communes(id) ON DELETE CASCADE,
    nom_quartier VARCHAR(100),
    code_iris VARCHAR(10),  -- Code IRIS INSEE (découpage infra-communal)
    
    -- Géométrie du quartier (polygone)
    geometry GEOMETRY(Polygon, 4326),
    
    -- Scoring (calculé)
    score_qualite_vie DECIMAL(3,2) CHECK (score_qualite_vie BETWEEN 0 AND 10),
    proximite_transports DECIMAL(5,2),  -- Distance moyenne en km
    nb_commerces INT DEFAULT 0,
    nb_ecoles INT DEFAULT 0,
    nb_parcs INT DEFAULT 0,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quartiers_commune ON quartiers(commune_id);
CREATE INDEX IF NOT EXISTS idx_quartiers_nom ON quartiers(nom_quartier);
CREATE INDEX IF NOT EXISTS idx_quartiers_geom ON quartiers USING GIST(geometry);

COMMENT ON TABLE quartiers IS 'Quartiers et zones IRIS avec indicateurs de qualité de vie';


-- =============================================================================
-- TABLE: sales (ventes DVF - données officielles)
-- =============================================================================
-- Contient toutes les transactions immobilières issues de DVF (data.gouv.fr)
CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    dvf_id VARCHAR(50) UNIQUE,  -- ID unique DVF
    
    -- Date et type de transaction
    date_mutation DATE NOT NULL,
    nature_mutation VARCHAR(50),  -- Vente, Échange, Adjudication, etc.
    valeur_fonciere DECIMAL(12,2) NOT NULL CHECK (valeur_fonciere > 0),
    
    -- Bien immobilier
    type_local VARCHAR(50) NOT NULL,  -- Maison, Appartement, Local, Terrain
    nb_pieces INT,
    surface_reelle_bati DECIMAL(10,2) CHECK (surface_reelle_bati > 0),  -- m²
    surface_terrain DECIMAL(10,2) CHECK (surface_terrain >= 0),  -- m²
    nombre_lots INT,
    
    -- Localisation
    code_commune VARCHAR(5),
    commune_id INT REFERENCES communes(id) ON DELETE SET NULL,
    quartier_id INT REFERENCES quartiers(id) ON DELETE SET NULL,
    adresse_numero VARCHAR(10),
    adresse_suffixe VARCHAR(10),
    adresse_nom_voie TEXT,
    code_postal VARCHAR(5),
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    geometry GEOMETRY(Point, 4326),
    
    -- Features calculées
    prix_m2 DECIMAL(10,2),  -- Prix au m² (calculé)
    distance_centre_ville DECIMAL(10,2),  -- Distance au centre en km
    
    -- Features temporelles (extraites de date_mutation)
    annee INT,
    mois INT CHECK (mois BETWEEN 1 AND 12),
    trimestre INT CHECK (trimestre BETWEEN 1 AND 4),
    jour_semaine INT CHECK (jour_semaine BETWEEN 0 AND 6),
    
    -- Métadonnées
    source VARCHAR(20) DEFAULT 'DVF',
    data_quality_score INT CHECK (data_quality_score BETWEEN 0 AND 100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Contraintes
    CHECK (valeur_fonciere > 0),
    CHECK (surface_reelle_bati IS NULL OR surface_reelle_bati > 0)
);

-- Index multiples pour optimiser les requêtes fréquentes
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date_mutation);
CREATE INDEX IF NOT EXISTS idx_sales_annee_mois ON sales(annee, mois);
CREATE INDEX IF NOT EXISTS idx_sales_commune ON sales(commune_id);
CREATE INDEX IF NOT EXISTS idx_sales_quartier ON sales(quartier_id);
CREATE INDEX IF NOT EXISTS idx_sales_type ON sales(type_local);
CREATE INDEX IF NOT EXISTS idx_sales_prix ON sales(valeur_fonciere);
CREATE INDEX IF NOT EXISTS idx_sales_prix_m2 ON sales(prix_m2);
CREATE INDEX IF NOT EXISTS idx_sales_geom ON sales USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_sales_code_commune ON sales(code_commune);

COMMENT ON TABLE sales IS 'Transactions immobilières officielles DVF (Demandes de Valeurs Foncières)';


-- =============================================================================
-- TABLE: listings (annonces en cours - web scraping)
-- =============================================================================
CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(100) UNIQUE NOT NULL,  -- ID source (PAP, Bienici)
    url TEXT NOT NULL,
    source VARCHAR(50) NOT NULL,  -- 'PAP', 'Bienici', etc.
    
    -- Dates
    date_scraped TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_published DATE,
    is_active BOOLEAN DEFAULT TRUE,
    date_sold DATE,  -- Si vendu (pour tracking)
    
    -- Prix
    prix_affiche DECIMAL(12,2) NOT NULL,
    prix_m2 DECIMAL(10,2),
    evolution_prix JSON,  -- Historique des changements de prix
    
    -- Bien
    type_bien VARCHAR(50),  -- Maison, Appartement, Terrain
    nb_pieces INT,
    nb_chambres INT,
    surface_habitable DECIMAL(10,2),
    surface_terrain DECIMAL(10,2),
    annee_construction INT CHECK (annee_construction >= 1800),
    etage INT,
    nb_etages_immeuble INT,
    
    -- Caractéristiques détaillées
    dpe_classe VARCHAR(1) CHECK (dpe_classe IN ('A','B','C','D','E','F','G')),  -- Diagnostic Performance Énergétique
    ges_classe VARCHAR(1) CHECK (ges_classe IN ('A','B','C','D','E','F','G')),  -- Gaz à Effet de Serre
    chauffage VARCHAR(50),
    climatisation BOOLEAN DEFAULT FALSE,
    parking BOOLEAN DEFAULT FALSE,
    balcon BOOLEAN DEFAULT FALSE,
    terrasse BOOLEAN DEFAULT FALSE,
    cave BOOLEAN DEFAULT FALSE,
    ascenseur BOOLEAN DEFAULT FALSE,
    piscine BOOLEAN DEFAULT FALSE,
    
    -- Localisation
    commune_id INT REFERENCES communes(id) ON DELETE SET NULL,
    quartier_id INT REFERENCES quartiers(id) ON DELETE SET NULL,
    adresse TEXT,
    code_postal VARCHAR(5),
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    geometry GEOMETRY(Point, 4326),
    
    -- Contenu textuel
    titre TEXT,
    description TEXT,
    photos_urls TEXT[],  -- Array d'URLs des photos
    nb_photos INT DEFAULT 0,
    
    -- Vendeur
    type_vendeur VARCHAR(50),  -- Particulier, Agence, Promoteur
    nom_agence VARCHAR(200),
    telephone VARCHAR(20),
    
    -- Métadonnées
    nb_vues INT DEFAULT 0,
    data_quality_score INT CHECK (data_quality_score BETWEEN 0 AND 100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_commune ON listings(commune_id);
CREATE INDEX IF NOT EXISTS idx_listings_quartier ON listings(quartier_id);
CREATE INDEX IF NOT EXISTS idx_listings_type ON listings(type_bien);
CREATE INDEX IF NOT EXISTS idx_listings_prix ON listings(prix_affiche);
CREATE INDEX IF NOT EXISTS idx_listings_date_scraped ON listings(date_scraped);
CREATE INDEX IF NOT EXISTS idx_listings_date_published ON listings(date_published);
CREATE INDEX IF NOT EXISTS idx_listings_geom ON listings USING GIST(geometry);

COMMENT ON TABLE listings IS 'Annonces immobilières actuelles collectées via web scraping';


-- =============================================================================
-- TABLE: price_history (tracking prix annonces)
-- =============================================================================
CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    listing_id INT REFERENCES listings(id) ON DELETE CASCADE,
    prix DECIMAL(12,2) NOT NULL,
    date_observation TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    variation_pct DECIMAL(5,2),  -- % de variation vs prix précédent
    
    UNIQUE(listing_id, date_observation)
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(date_observation);

COMMENT ON TABLE price_history IS 'Historique des changements de prix pour les annonces';


-- =============================================================================
-- TABLE: poi (Points of Interest - OpenStreetMap)
-- =============================================================================
CREATE TABLE IF NOT EXISTS poi (
    id SERIAL PRIMARY KEY,
    type_poi VARCHAR(50) NOT NULL,  -- transport, ecole, commerce, sante, loisir
    nom VARCHAR(200),
    categorie VARCHAR(100),  -- Ex: métro, bus, tram / primaire, collège, lycée
    adresse TEXT,
    commune_id INT REFERENCES communes(id) ON DELETE SET NULL,
    
    -- Géolocalisation
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    geometry GEOMETRY(Point, 4326),
    
    -- Métadonnées flexibles (JSON)
    metadata JSONB,  -- Infos supplémentaires variables selon le type
    
    source VARCHAR(50) DEFAULT 'OSM',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_poi_type ON poi(type_poi);
CREATE INDEX IF NOT EXISTS idx_poi_categorie ON poi(categorie);
CREATE INDEX IF NOT EXISTS idx_poi_commune ON poi(commune_id);
CREATE INDEX IF NOT EXISTS idx_poi_geom ON poi USING GIST(geometry);

COMMENT ON TABLE poi IS 'Points d\'intérêt (transports, écoles, commerces) depuis OpenStreetMap';


-- =============================================================================
-- TABLE: ml_predictions (cache des prédictions ML)
-- =============================================================================
CREATE TABLE IF NOT EXISTS ml_predictions (
    id SERIAL PRIMARY KEY,
    model_version VARCHAR(50) NOT NULL,
    
    -- Input features
    type_bien VARCHAR(50),
    surface_habitable DECIMAL(10,2),
    nb_pieces INT,
    commune_id INT REFERENCES communes(id) ON DELETE CASCADE,
    quartier_id INT REFERENCES quartiers(id) ON DELETE SET NULL,
    latitude DECIMAL(10,8),
    longitude DECIMAL(11,8),
    annee_construction INT,
    
    -- Features dérivées/calculées
    distance_centre_ville DECIMAL(10,2),
    score_quartier DECIMAL(3,2),
    nb_transports_500m INT,
    prix_m2_moyen_quartier DECIMAL(10,2),
    
    -- Output du modèle
    prix_predit DECIMAL(12,2) NOT NULL,
    prix_min DECIMAL(12,2),  -- Borne inférieure intervalle confiance (95%)
    prix_max DECIMAL(12,2),  -- Borne supérieure intervalle confiance (95%)
    confiance_score DECIMAL(3,2) CHECK (confiance_score BETWEEN 0 AND 1),
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    features_json JSONB  -- Stockage complet des features utilisées
);

CREATE INDEX IF NOT EXISTS idx_predictions_commune ON ml_predictions(commune_id);
CREATE INDEX IF NOT EXISTS idx_predictions_model ON ml_predictions(model_version);
CREATE INDEX IF NOT EXISTS idx_predictions_date ON ml_predictions(created_at);

COMMENT ON TABLE ml_predictions IS 'Cache des prédictions du modèle ML avec intervalles de confiance';


-- =============================================================================
-- VUES MATÉRIALISÉES (agrégations pré-calculées)
-- =============================================================================

-- Vue 1: Statistiques de prix par commune et type de bien
CREATE MATERIALIZED VIEW IF NOT EXISTS vw_price_stats AS
SELECT 
    c.code_commune,
    c.nom_commune,
    c.departement,
    c.region,
    s.type_local,
    COUNT(*) as nb_ventes,
    AVG(s.prix_m2) as prix_m2_moyen,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.prix_m2) as prix_m2_median,
    MIN(s.prix_m2) as prix_m2_min,
    MAX(s.prix_m2) as prix_m2_max,
    STDDEV(s.prix_m2) as prix_m2_stddev,
    AVG(s.valeur_fonciere) as prix_moyen,
    MAX(s.date_mutation) as derniere_vente
FROM sales s
JOIN communes c ON s.commune_id = c.id
WHERE 
    s.date_mutation >= CURRENT_DATE - INTERVAL '12 months'
    AND s.prix_m2 IS NOT NULL
    AND s.prix_m2 > 0
GROUP BY c.code_commune, c.nom_commune, c.departement, c.region, s.type_local;

CREATE UNIQUE INDEX IF NOT EXISTS idx_vw_price_stats 
    ON vw_price_stats(code_commune, type_local);

COMMENT ON MATERIALIZED VIEW vw_price_stats IS 'Statistiques de prix agrégées par commune et type (12 derniers mois)';


-- Vue 2: Évolution mensuelle des prix (time series)
CREATE MATERIALIZED VIEW IF NOT EXISTS vw_monthly_trends AS
SELECT 
    DATE_TRUNC('month', s.date_mutation) as mois,
    c.departement,
    c.nom_commune,
    s.type_local,
    COUNT(*) as nb_ventes,
    AVG(s.prix_m2) as prix_m2_moyen,
    SUM(s.valeur_fonciere) as volume_total_euros
FROM sales s
JOIN communes c ON s.commune_id = c.id
WHERE s.prix_m2 IS NOT NULL
GROUP BY DATE_TRUNC('month', s.date_mutation), c.departement, c.nom_commune, s.type_local;

CREATE INDEX IF NOT EXISTS idx_vw_trends_date ON vw_monthly_trends(mois);
CREATE INDEX IF NOT EXISTS idx_vw_trends_dept ON vw_monthly_trends(departement);

COMMENT ON MATERIALIZED VIEW vw_monthly_trends IS 'Évolution mensuelle des prix par commune et type';


-- Vue 3: Analyse des quartiers avec données enrichies
CREATE MATERIALIZED VIEW IF NOT EXISTS vw_quartier_analysis AS
SELECT 
    q.id as quartier_id,
    q.nom_quartier,
    c.nom_commune,
    c.departement,
    
    -- Statistiques ventes DVF
    COUNT(DISTINCT s.id) as nb_ventes_12m,
    AVG(s.prix_m2) as prix_m2_moyen_ventes,
    
    -- Statistiques annonces actuelles
    COUNT(DISTINCT l.id) as nb_annonces_actives,
    AVG(l.prix_m2) as prix_m2_moyen_annonces,
    
    -- Écart entre demandé et réalisé
    (AVG(l.prix_m2) - AVG(s.prix_m2)) as ecart_prix_m2,
    ((AVG(l.prix_m2) - AVG(s.prix_m2)) / NULLIF(AVG(s.prix_m2), 0) * 100) as ecart_pct,
    
    -- POI proximité (rayon 500m)
    (SELECT COUNT(*) FROM poi p 
     WHERE ST_DWithin(p.geometry::geography, q.geometry::geography, 500) 
     AND p.type_poi = 'transport') as nb_transports_500m,
    
    (SELECT COUNT(*) FROM poi p 
     WHERE ST_DWithin(p.geometry::geography, q.geometry::geography, 500) 
     AND p.type_poi = 'ecole') as nb_ecoles_500m,
    
    (SELECT COUNT(*) FROM poi p 
     WHERE ST_DWithin(p.geometry::geography, q.geometry::geography, 500) 
     AND p.type_poi = 'commerce') as nb_commerces_500m,
    
    -- Score qualité de vie
    q.score_qualite_vie,
    
    -- Dates
    MAX(s.date_mutation) as derniere_vente,
    MAX(l.date_scraped) as derniere_maj_annonces,
    CURRENT_TIMESTAMP as updated_at
    
FROM quartiers q
JOIN communes c ON q.commune_id = c.id
LEFT JOIN sales s ON s.quartier_id = q.id 
    AND s.date_mutation >= CURRENT_DATE - INTERVAL '12 months'
LEFT JOIN listings l ON l.quartier_id = q.id 
    AND l.is_active = TRUE
GROUP BY q.id, q.nom_quartier, c.nom_commune, c.departement, q.score_qualite_vie;

COMMENT ON MATERIALIZED VIEW vw_quartier_analysis IS 'Analyse complète des quartiers avec POI et comparaison ventes/annonces';


-- =============================================================================
-- FONCTIONS UTILITAIRES PostGIS
-- =============================================================================

-- Fonction 1: Calculer distance entre 2 points en km
CREATE OR REPLACE FUNCTION distance_km(
    lat1 DECIMAL, 
    lon1 DECIMAL, 
    lat2 DECIMAL, 
    lon2 DECIMAL
) RETURNS DECIMAL AS $$
BEGIN
    RETURN ST_Distance(
        ST_MakePoint(lon1, lat1)::geography,
        ST_MakePoint(lon2, lat2)::geography
    ) / 1000.0;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION distance_km IS 'Calcule la distance entre 2 coordonnées GPS en kilomètres';


-- Fonction 2: Trouver le quartier d'un point
CREATE OR REPLACE FUNCTION find_quartier(
    p_lat DECIMAL, 
    p_lon DECIMAL
) RETURNS INT AS $$
DECLARE
    v_quartier_id INT;
BEGIN
    SELECT id INTO v_quartier_id
    FROM quartiers
    WHERE ST_Contains(
        geometry, 
        ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)
    )
    LIMIT 1;
    
    RETURN v_quartier_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION find_quartier IS 'Trouve le quartier contenant un point GPS donné';


-- Fonction 3: Calculer prix/m² avec filtrage outliers
CREATE OR REPLACE FUNCTION clean_price_per_m2(
    p_prix DECIMAL,
    p_surface DECIMAL
) RETURNS DECIMAL AS $$
DECLARE
    v_price_m2 DECIMAL;
BEGIN
    IF p_surface IS NULL OR p_surface <= 0 THEN
        RETURN NULL;
    END IF;
    
    v_price_m2 := p_prix / p_surface;
    
    -- Filtrer outliers (< 500€ ou > 20000€/m²)
    IF v_price_m2 < 500 OR v_price_m2 > 20000 THEN
        RETURN NULL;
    END IF;
    
    RETURN v_price_m2;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION clean_price_per_m2 IS 'Calcule le prix/m² avec filtrage automatique des outliers';


-- Fonction 4: Compter POI dans un rayon
CREATE OR REPLACE FUNCTION count_poi_within_radius(
    p_lat DECIMAL,
    p_lon DECIMAL,
    p_radius_meters INT,
    p_type_poi VARCHAR DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM poi
    WHERE ST_DWithin(
        geometry::geography,
        ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326)::geography,
        p_radius_meters
    )
    AND (p_type_poi IS NULL OR type_poi = p_type_poi);
    
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION count_poi_within_radius IS 'Compte les POI dans un rayon donné (en mètres) autour d''un point';


-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger 1: Auto-update timestamp updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Appliquer le trigger sur les tables concernées
CREATE TRIGGER trigger_communes_updated_at
    BEFORE UPDATE ON communes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_quartiers_updated_at
    BEFORE UPDATE ON quartiers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_listings_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- Trigger 2: Auto-calculer geometry depuis lat/lon
CREATE OR REPLACE FUNCTION set_geometry_from_coords()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.geometry = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sales_set_geometry
    BEFORE INSERT OR UPDATE ON sales
    FOR EACH ROW
    EXECUTE FUNCTION set_geometry_from_coords();

CREATE TRIGGER trigger_listings_set_geometry
    BEFORE INSERT OR UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION set_geometry_from_coords();

CREATE TRIGGER trigger_communes_set_geometry
    BEFORE INSERT OR UPDATE ON communes
    FOR EACH ROW
    EXECUTE FUNCTION set_geometry_from_coords();


-- Trigger 3: Auto-calculer prix_m2 pour sales
CREATE OR REPLACE FUNCTION calculate_prix_m2_sales()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.surface_reelle_bati > 0 THEN
        NEW.prix_m2 = clean_price_per_m2(NEW.valeur_fonciere, NEW.surface_reelle_bati);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sales_calculate_prix_m2
    BEFORE INSERT OR UPDATE ON sales
    FOR EACH ROW
    EXECUTE FUNCTION calculate_prix_m2_sales();


-- Trigger 4: Auto-calculer prix_m2 pour listings
CREATE OR REPLACE FUNCTION calculate_prix_m2_listings()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.surface_habitable > 0 THEN
        NEW.prix_m2 = NEW.prix_affiche / NEW.surface_habitable;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_listings_calculate_prix_m2
    BEFORE INSERT OR UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION calculate_prix_m2_listings();


-- Trigger 5: Extraire features temporelles de date_mutation
CREATE OR REPLACE FUNCTION extract_temporal_features()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.date_mutation IS NOT NULL THEN
        NEW.annee = EXTRACT(YEAR FROM NEW.date_mutation);
        NEW.mois = EXTRACT(MONTH FROM NEW.date_mutation);
        NEW.trimestre = EXTRACT(QUARTER FROM NEW.date_mutation);
        NEW.jour_semaine = EXTRACT(DOW FROM NEW.date_mutation);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sales_temporal_features
    BEFORE INSERT OR UPDATE ON sales
    FOR EACH ROW
    EXECUTE FUNCTION extract_temporal_features();


-- =============================================================================
-- DONNÉES INITIALES (exemples)
-- =============================================================================

-- Insérer quelques communes principales (exemples)
INSERT INTO communes (code_commune, nom_commune, code_postal, departement, region, latitude, longitude) VALUES
('75056', 'Paris', '75000', '75', 'Île-de-France', 48.8566, 2.3522),
('69123', 'Lyon', '69000', '69', 'Auvergne-Rhône-Alpes', 45.7640, 4.8357),
('13055', 'Marseille', '13000', '13', 'Provence-Alpes-Côte d''Azur', 43.2965, 5.3698),
('33063', 'Bordeaux', '33000', '33', 'Nouvelle-Aquitaine', 44.8378, -0.5792),
('59350', 'Lille', '59000', '59', 'Hauts-de-France', 50.6292, 3.0573)
ON CONFLICT (code_commune) DO NOTHING;


-- =============================================================================
-- COMMANDES DE MAINTENANCE
-- =============================================================================

-- Rafraîchir les vues matérialisées (à exécuter régulièrement)
-- REFRESH MATERIALIZED VIEW CONCURRENTLY vw_price_stats;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY vw_monthly_trends;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY vw_quartier_analysis;

-- Analyser les tables pour mettre à jour les statistiques (optimisation)
-- ANALYZE sales;
-- ANALYZE listings;
-- ANALYZE communes;
-- ANALYZE quartiers;
-- ANALYZE poi;

-- Vacuum pour récupérer l'espace disque
-- VACUUM ANALYZE;


-- =============================================================================
-- FIN DU SCHÉMA
-- =============================================================================

-- Afficher un message de succès
DO $$ 
BEGIN 
    RAISE NOTICE 'Schéma de base de données créé avec succès !';
    RAISE NOTICE 'Tables : communes, quartiers, sales, listings, price_history, poi, ml_predictions';
    RAISE NOTICE 'Vues matérialisées : vw_price_stats, vw_monthly_trends, vw_quartier_analysis';
    RAISE NOTICE 'Fonctions : distance_km, find_quartier, clean_price_per_m2, count_poi_within_radius';
END $$;